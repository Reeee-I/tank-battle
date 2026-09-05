/*==============================================================================
 * 双人坦克对战 - 485 中转板程序（STC_B 学习板 / STC15F2K60S2）
 *------------------------------------------------------------------------------
 * 功能：第三块板作为 RS-485 总线"轮询主机 + USB 转发"：
 *   - 每 100ms 周期点名两块 485 手柄板（玩家1 → 玩家2）；
 *   - 手柄被点名后应答 3 字节数据包（AA/玩家号/按键掩码，协议与旧 USB
 *     直连方案完全一致）；
 *   - 中转板收到合法应答后，经串口1（板载 USB 口）原样转发给 PC。
 *   PC 端程序无需任何修改：两块玩家都以 ~100ms 一包的节奏从本板所在
 *   的同一个 COM 口上报，PC 按"包内容自动绑定玩家"即可正常工作。
 *
 * 板间轮询协议（485 总线，9600 bps，8 数据位 1 停止位 无校验，半双工）：
 *     本板点名帧（3 字节，固定）：
 *         点名玩家1 : AA E1 00
 *         点名玩家2 : AA E2 00
 *     手柄应答帧（3 字节，原样转发 PC，不做任何改动）：
 *         AA 01 xx（玩家1） / AA 02 xx（玩家2）
 *   所有帧固定 3 字节，保证总线上字节流按帧对齐；本板自己的点名回声
 *   （AA E1 00 / AA E2 00）在收包回调中按 buf[1]∈{01,02} 过滤丢弃。
 *
 * 轮询时序（100ms 周期，10ms 事件做超时计数，全部非阻塞）：
 *   t=0       : 发点名 AA E1 00，等玩家1 应答（超时 30ms）；
 *   收到玩家1 : 校验通过 → 串口1 转发 PC → 立即发点名 AA E2 00，等玩家2；
 *   t=30ms 无应答: 玩家1 记为缺包 → 同样发点名 AA E2 00（掉线手柄不阻塞
 *                 另一玩家，缺包与否由 PC 侧 0.6s 心跳超时判定）；
 *   收到玩家2 : 转发 PC → 周期结束，等下一个 100ms；
 *   t=70ms 仍无应答: 玩家2 记为缺包，周期结束。
 *
 * 数码管身份显示：上电最左位显示 'C'（= 中转/集中板），与手柄板
 *                 （'1'/'2'）、无线发送端（'A'）、无线接收端（'b'）相区分。
 * 工作指示：每次成功向 PC 转发一包时 L0 点亮。
 *
 * 下行血量转发（手柄 LED 血量联动）：PC 把 AA D1/D2 HP 帧写入本板串口1
 *   → 本板缓存后在 485 总线"空闲窗口"（本轮点名/应答结束 ≥20ms，每
 *   10ms 至多一帧）原样转发给对应手柄；手柄按命令码刷新 LED 血条
 *   （满血3=六灯…死亡=全灭）。中转板本身不显示血量（非玩家板）。
 *
 * 注意：
 *   1) SysClock 必须与实际下载频率一致（STC-B 板为 11.0592MHz 晶振）；
 *   2) 主循环中只允许 MySTC_OS()（BSP 铁律），业务全部放入事件回调；
 *   3) 串口1(USB, 上行 PC) 与串口2(485, 下行总线) 可同时工作互不影响；
 *      转发前检查 Uart1 发送空闲，避免覆盖发送队列；
 *   4) 串口2 用于 485 时为半双工（发送时不能接收），收发方向由板/库管理；
 *   5) 事件回调内总耗时须 <1mS：本程序回调只做状态位翻转与发包请求。
 *
 * 编译环境：Keil uVision4/5 + C51（C89 规范，代码优化 Level 8，内存模式 Small）
 * 工程文件：main_hub.c + MCU\STC_BSP.lib + MCU\inc 头文件目录（共享引用）
 * 生成文件：..\HEX\485_Relay.hex（统一 HEX 目录，用 STC-ISP 烧录）
 *============================================================================*/
#include "STC15F2K60S2.H"   /* 必须：STC15 系列寄存器定义 */
#include "sys.H"            /* 必须：系统初始化/调度/事件回调 */
#include "displayer.h"      /* 显示模块：DisplayerInit / LedPrint / Seg7Print */
#include "adc.h"            /* ADC 模块：ADCexpEXT 保留 485(UART2) 用 P1.0/P1.1 */
#include "uart1.h"          /* 串口1（板载 USB）：Uart1Init / Uart1Print（上行 PC） */
#include "uart2.h"          /* 串口2（485 接口）：Uart2Init / Uart2Print（点名） */

/*--------------------------- 协议常量（勿改动） ------------------------------*/
#define PKT_HEADER      0xAA    /* 数据包包头 */
#define PKT_P1          0x01    /* 玩家1 号 */
#define PKT_P2          0x02    /* 玩家2 号 */

#define POLL_P1         0xE1    /* 点名码：玩家1 手柄 */
#define POLL_P2         0xE2    /* 点名码：玩家2 手柄 */

/* PC → 中转板 下行命令码（LED 血量联动，3 字节 AA + 命令码 + 血量 0~3）：
 *   中转板经串口1(USB) 收到后，在 485 总线"空闲窗口"把同一帧转发给
 *   对应手柄（本板与手柄间字节原样：AA D1/D2 HP）；D 前缀与玩家号
 *   01/02、点名码 E1/E2 永不冲突。中转板本身不显示血量（非玩家板）。 */
#define DL_HP_P1        0xD1    /* 下行命令码：玩家1 血量 */
#define DL_HP_P2        0xD2    /* 下行命令码：玩家2 血量 */
#define DL_HP_MAX       3       /* 血量上限（满血=3 命） */

/* 轮询时序常量（10ms 计数单位，集中可调） */
#define P1_WAIT_TICKS   3       /* 玩家1 应答等待上限 = 30ms（点名前必须留出
                                   手柄应答+总线换向时间，实测正常 ~5ms） */
#define P2_WAIT_TICKS   4       /* 玩家2 应答等待上限 = 40ms */
#define DL_SEND_TICKS   2       /* 空闲 ≥20ms 后才允许发下行帧（总线静默余量） */

/*--------------------------- 系统变量（必须定义） ---------------------------*/
/* 系统工作时钟频率(Hz)，必须与 STC-ISP 下载时选择的频率一致。
 * STC-B 学习板默认外部晶振 11.0592MHz。 */
code unsigned long SysClock = 11059200;

/* 选用显示模块时必须：数码管显示译码表（displayer 模块会引用该表）。
 * 索引 0~9：数字0~9；10：空；11~15：下/中/上 横杠段；16~25：带小数点的0~9；
 * 追加索引 26：'A'、27：'b'（无线方案占用）、28：'C'（本板=中转/集中板）。 */
#ifdef _displayer_H_
code char decode_table[] = {0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f,
                            0x00,0x08,0x40,0x01,0x41,0x48,
                            0x3f|0x80,0x06|0x80,0x5b|0x80,0x4f|0x80,0x66|0x80,
                            0x6d|0x80,0x7d|0x80,0x07|0x80,0x7f|0x80,0x6f|0x80,
                            0x77,0x7c,0x39};  /* 26:'A' 27:'b' 28:'C' 中转板 */
#endif

/* 数码管标识索引（对应上面译码表追加段） */
#define SEG_C       28      /* 'C'：485 中转板 */

/*--------------------------------- 用户全局变量 ----------------------------*/
static unsigned char rxBuf[3];      /* UART2(485) 接收缓冲：手柄应答帧 */
static unsigned char headAA[1] = {PKT_HEADER};  /* UART2 包头匹配：AA */

static unsigned char u1rxBuf[3];    /* UART1(USB, PC) 接收缓冲：下行血量帧 */
static unsigned char u1headAA[1] = {PKT_HEADER}; /* UART1 包头匹配：AA */

static unsigned char pollP1[3] = {PKT_HEADER, POLL_P1, 0x00};  /* 点名玩家1 帧 */
static unsigned char pollP2[3] = {PKT_HEADER, POLL_P2, 0x00};  /* 点名玩家2 帧 */

/* 待转发给各手柄的下行血量帧（AA D1/D2 HP）与待发标志 */
static unsigned char downP1[3] = {PKT_HEADER, DL_HP_P1, 0x00};
static unsigned char downP2[3] = {PKT_HEADER, DL_HP_P2, 0x00};
static unsigned char downP1Pend;    /* =1：玩家1 血量帧待转发 */
static unsigned char downP2Pend;    /* =1：玩家2 血量帧待转发 */

static unsigned char waitP1;        /* =1：已点名玩家1，正在等其应答 */
static unsigned char waitP2;        /* =1：已点名玩家2，正在等其应答 */
static unsigned char tickCnt;       /* 最近一次点名后的 10ms 计数（超时用） */

/*--------------------------------- 本地工具函数 -----------------------------*/
/* 点名玩家1：串口2(485) 空闲则发出 3 字节点名帧，进入等待态并重置超时计数 */
static void poll_player1(void)
{
    if (GetUart2TxStatus() == enumUart2TxFree)
    {
        Uart2Print(pollP1, 3);
    }
    waitP1 = 1;
    waitP2 = 0;
    tickCnt = 0;
}

/* 点名玩家2：同上 */
static void poll_player2(void)
{
    if (GetUart2TxStatus() == enumUart2TxFree)
    {
        Uart2Print(pollP2, 3);
    }
    waitP1 = 0;
    waitP2 = 1;
    tickCnt = 0;
}

/* 转发 3 字节应答帧给 PC（串口1 空闲才转发；转发成功点亮 L0 作工作指示）。
 * 上一包未发完（USB 侧忙）时放弃本包——PC 以 0.6s 心跳判在线，偶发丢包
 * 不影响；下次点名会带来新包，单发键事件若恰在丢包帧内至多延迟一拍。 */
static void forward_to_pc(unsigned char *pkt)
{
    if (GetUart1TxStatus() == enumUart1TxFree)
    {
        if (Uart1Print(pkt, 3) != enumUart1TxFailure)
        {
            LedPrint(0x01);         /* 转发成功指示 */
        }
    }
}

/*----------------------------- 485 收包事件回调 -----------------------------*/
/* 收到一个 3 字节、AA 开头的帧（本板点名回声 AA E1/E2 00、或手柄应答
 * AA 01/02 xx）时调用。只处理"正在等待"的合法玩家应答并转发；点名回声
 * （buf[1]=E1/E2）与重复/杂散帧一律丢弃。 */
void myUart2Rxd_callback(void)
{
    if (rxBuf[0] != PKT_HEADER)
    {
        return;
    }

    /* 玩家1 应答：转发 → 立即点名玩家2 */
    if ((rxBuf[1] == PKT_P1) && (waitP1 != 0))
    {
        waitP1 = 0;
        forward_to_pc(rxBuf);
        poll_player2();
        return;
    }

    /* 玩家2 应答：转发 → 周期完成，等下一个 100ms */
    if ((rxBuf[1] == PKT_P2) && (waitP2 != 0))
    {
        waitP2 = 0;
        forward_to_pc(rxBuf);
        return;
    }

    /* 其它（点名回声/非等待态应答）：丢弃 */
}

/*----------------------------- 串口1 收包事件回调 ----------------------------*/
/* 收到 PC 下行的血量帧 AA D1/D2 HP（串口1/USB）时调用：
 * 只把血量值缓到对应待发帧并置待发标志——真正发送放在 10ms 空闲窗口
 * （半双工 485：不能在点名/应答收发期间插入下行帧，避免总线碰撞）。 */
void myUart1Rxd_callback(void)
{
    unsigned char hp;

    if (u1rxBuf[0] != PKT_HEADER)
    {
        return;
    }
    if (u1rxBuf[1] == DL_HP_P1)
    {
        hp = u1rxBuf[2];
        if (hp > DL_HP_MAX)
        {
            hp = DL_HP_MAX;
        }
        downP1[2] = hp;
        downP1Pend = 1;
    }
    else if (u1rxBuf[1] == DL_HP_P2)
    {
        hp = u1rxBuf[2];
        if (hp > DL_HP_MAX)
        {
            hp = DL_HP_MAX;
        }
        downP2[2] = hp;
        downP2Pend = 1;
    }
    /* 其它命令码：丢弃 */
}

/*----------------------------- 10ms 周期回调 --------------------------------*/
/* 每 10ms 由系统调用一次：
 *  ① 应答超时推进（保证掉线手柄不阻塞另一玩家）；
 *  ② 总线空闲窗口（本轮点名/应答全部结束 ≥20ms）转发下行血量帧：
 *     每个 10ms tick 至多转发一帧（每帧 ~3.1ms，间隔 ≥10ms 满足 BSP
 *     收包 ≥1ms 间距要求），两条命令码依次送完；点名前总线必已静默。 */
void my10mS_callback(void)
{
    tickCnt++;

    if ((waitP1 != 0) && (tickCnt >= P1_WAIT_TICKS))
    {
        /* 玩家1 无应答：本轮缺包，照常点名玩家2 */
        waitP1 = 0;
        poll_player2();
        return;
    }

    if ((waitP2 != 0) && (tickCnt >= P2_WAIT_TICKS))
    {
        /* 玩家2 无应答：本轮缺包，周期结束 */
        waitP2 = 0;
        tickCnt = 0;
        return;
    }

    /* 空闲窗口下行转发（先玩家1、后玩家2，一 tick 一帧） */
    if ((waitP1 == 0) && (waitP2 == 0) && (tickCnt >= DL_SEND_TICKS))
    {
        if ((downP1Pend != 0) && (GetUart2TxStatus() == enumUart2TxFree))
        {
            if (Uart2Print(downP1, 3) != enumUart2TxFailure)
            {
                downP1Pend = 0;         /* 请求被接受 → 清待发标志 */
            }
            return;
        }
        if ((downP2Pend != 0) && (GetUart2TxStatus() == enumUart2TxFree))
        {
            if (Uart2Print(downP2, 3) != enumUart2TxFailure)
            {
                downP2Pend = 0;
            }
            return;
        }
    }
}

/*----------------------------- 100ms 周期回调 -------------------------------*/
/* 每 100ms 由系统调用一次：开始新一轮点名（先点名玩家1，随后在应答回调
 * 或 10ms 超时回调中推进点名玩家2）。正常情况下周期在 ~10ms 内完成，
 * 剩余时间总线空闲，保证两玩家对 PC 都以 ~100ms 一包稳定上报。 */
void my100mS_callback(void)
{
    poll_player1();
}

/*----------------------------------- 主函数 ---------------------------------*/
void main(void)
{
    DisplayerInit();                /* 1. 显示模块加载 */
    SetDisplayerArea(0, 7);         /*    启用 8 个扫描位（LED/数码管正常刷新） */
    LedPrint(0x00);                 /*    初始：LED 全灭 */

    /* 2. 数码管显示本板身份：最左位显示 'C'（= 485 中转板）。
     *    与手柄板('1'/'2')、无线发送端('A')、无线接收端('b') 均不同。 */
    Seg7Print(SEG_C, 10, 10, 10, 10, 10, 10, 10);

    AdcInit(ADCexpEXT);             /* 3. ADC 模块加载：ADCexpEXT 保留
                                           485(UART2) 所用 P1.0/P1.1 数字功能 */

    Uart1Init(9600UL);              /* 4. 串口1：板载 USB 口，9600bps 8N1（上行 PC） */
    Uart2Init(9600UL, Uart2Usedfor485); /* 5. 串口2：485 接口，9600bps 8N1 半双工 */

    SetUart1Rxd(u1rxBuf, 3, u1headAA, 1);   /* 5b. 串口1 收 PC 下行血量帧 */
    SetUart2Rxd(rxBuf, 3, headAA, 1);   /* 6. 485 收 3 字节、AA 开头的帧 */

    SetEventCallBack(enumEventSys10mS, my10mS_callback);    /* 7. 超时计数/下行转发 */
    SetEventCallBack(enumEventSys100mS, my100mS_callback);  /* 8. 轮询节拍 */
    SetEventCallBack(enumEventUart1Rxd, myUart1Rxd_callback);/* 8b. 下行血量接收 */
    SetEventCallBack(enumEventUart2Rxd, myUart2Rxd_callback);/* 9. 应答接收 */

    MySTC_Init();                   /* 10. 系统初始化（必须，只执行一次） */

    while (1)                       /* 11. 主循环：铁律——只允许 MySTC_OS() */
    {
        MySTC_OS();
    }
}

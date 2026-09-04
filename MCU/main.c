/*==============================================================================
 * 双人坦克对战 - 手柄端程序（STC_B 学习板 / STC15F2K60S2）
 *------------------------------------------------------------------------------
 * 功能：两块完全相同的开发板分别作为玩家1/玩家2 的手柄，
 *       通过串口每 100ms 向 PC 发送一次按键状态数据包；
 *       并接收 PC 下行的"血量帧"，把板载 LED(L0~L5) 显示为所控坦克的血条
 *       （满血3=6灯全亮；每掉 1 血灭右侧 2 灯；死亡=全灭）。
 *
 * 区分玩家：仅通过编译宏 PLAYER_ID 区分（见下方宏定义）：
 *     PLAYER_ID = 1  → 数码管最左位显示"1"，发送包头玩家号 0x01（玩家1）
 *     PLAYER_ID = 2  → 数码管最左位显示"2"，发送包头玩家号 0x02（玩家2）
 *   （身份显示 = 数码管 1/2；LED 专用于血量——用户需求）
 *   （推荐做法：Keil 工程建两个 Target，在 C51 编译选项 Define 中分别写
 *     PLAYER_ID=1 与 PLAYER_ID=2，编译出两个 HEX：Tank_P1.hex / Tank_P2.hex）
 *
 * 通信协议（3 字节数据包，9600 bps，8 数据位 1 停止位 无校验）：
 *     上行（本板 → PC，每 100ms 一次）：
 *         字节0 : 0xAA                        包头（固定）
 *         字节1 : 0x01(玩家1) / 0x02(玩家2)   玩家号
 *         字节2 : 按键位掩码
 *                 bit0=1 左(导航左按, 左转)   bit1=1 右(导航右按, 右转)
 *                 bit2=1 上(导航上按, 前进)   bit3=1 下(导航下按, 后退)
 *                 bit4=1 开火(K1按下瞬间, 单发一次)
 *                 bit5=1 重开请求(K2按下瞬间, 单发一次; PC 仅在结算画面处理)
 *                 bit6=1 K3(按下瞬间, 单发一次; PC 仅在开始界面当作"任意键开始"
 *                   输入, 对战中忽略——K3 上报让开始界面"任一手柄按键可开始"完整生效)
 *     下行（PC → 本板，仅 UART_IF=0 板载 USB 通道启用）：
 *         字节0 : 0xAA                        包头（固定）
 *         字节1 : 0xD1(玩家1) / 0xD2(玩家2)   下行命令码（血量）
 *         字节2 : 血量 0~3（满血=3）→ 按下方"LED 血条语义"刷新 LED
 *
 * 串口通道（编译宏 UART_IF 选择）：
 *     UART_IF = 0（默认）：板载 USB 串口1（CH340，与电脑直接USB线相连），
 *                同时启用 PC → 板 血量下行（LED 血条联动）
 *     UART_IF = 1       ：EXT 扩展口 UART2（需外接 USB-TTL 模块，P1.1=TXD2；
 *                RX 可不接 → 无血量下行，LED 保持全灭）
 *
 * 注意：
 *   1) SysClock 必须与实际下载频率一致（STC-B 板为 11.0592MHz 晶振，
 *      若用内部IRC或改频率，请同步修改 SysClock 并在 STC-ISP 中选择一致频率）；
 *   2) 主循环中只允许 MySTC_OS()（BSP 铁律），业务全部放入事件回调；
 *   3) 查询型 API（GetKeyAct/GetAdcNavAct）返回的是"一次性"边沿事件，
 *      查询后自动复位，因此方向键采用"Press 置位 / Release 清位"的状态位
 *      方式实现"按住持续发送"；K1 开火、K2 重开、K3 均只在 Press 瞬间置
 *      单发标志（K2 仅在结算画面被 PC 处理，K3 仅在开始界面被当作开始输入）。
 *
 * 编译环境：Keil uVision4/5 + C51（C89 规范，代码优化 Level 8，内存模式 Small）
 * 工程文件：main.c + STC_BSP.lib + inc 头文件目录
 *============================================================================*/
#include "STC15F2K60S2.H"   /* 必须：STC15 系列寄存器定义 */
#include "sys.H"            /* 必须：系统初始化/调度/事件回调 */
#include "displayer.h"      /* 显示模块：DisplayerInit / LedPrint */
#include "Key.H"            /* 按键模块：K1~K3（K1 用作开火） */
#include "adc.h"            /* ADC 模块：导航按键（上/下/左/右/中） */

/*------------------------------- 玩家/通道配置 ------------------------------*/
#ifndef PLAYER_ID
#define PLAYER_ID   1       /* 玩家号：板1 编译时置 1，板2 编译时置 2 */
#endif

/* 编译期校验：PLAYER_ID 只允许 1 或 2，防止两板同号静默冲突 */
#if (PLAYER_ID != 1) && (PLAYER_ID != 2)
#error "PLAYER_ID must be 1 (玩家1) or 2 (玩家2) !"
#endif

#ifndef UART_IF
#define UART_IF     0       /* 0 = 板载USB串口1（默认，USB线直连电脑） */
#endif                      /* 1 = EXT 扩展口 UART2（外接 USB-TTL）     */

#if (UART_IF == 0)
    #include "uart1.h"      /* 串口1：固定在板载 USB 口 */
#else
    #include "uart2.h"      /* 串口2：EXT 扩展插座 */
#endif

/*--------------------------- 协议常量（勿改动） ------------------------------*/
#define PKT_HEADER      0xAA    /* 数据包包头 */
#define PKT_P1          0x01    /* 玩家1 号 */
#define PKT_P2          0x02    /* 玩家2 号 */

#define KEY_LEFT        0x01    /* bit0：左  */
#define KEY_RIGHT       0x02    /* bit1：右  */
#define KEY_UP          0x04    /* bit2：上  */
#define KEY_DOWN        0x08    /* bit3：下  */
#define KEY_FIRE        0x10    /* bit4：开火（K1，单发） */
#define KEY_RESTART     0x20    /* bit5：重开请求（K2，单发；PC 结算画面处理） */
#define KEY_K3          0x40    /* bit6：K3（单发；PC 开始界面"任意键开始"用，对战中忽略） */

/* PC → 板 下行帧（LED 血量联动，9600 8N1，3 字节：AA + 命令码 + 血量 0~3）：
 *     命令码 0xD1 = 玩家1 血量、0xD2 = 玩家2 血量（与玩家号 01/02、点名码
 *     E1/E2 永不冲突）。USB 直连接法下每块板只收到发给自己的下行帧；
 *     本板只响应"AA + 本板命令码"的帧（接收包头已按此匹配，回调双保险）。
 * LED 血条语义：满血(3) = L0~L5 六灯全亮；每掉 1 血灭右侧 2 灯
 * （3→0x3F、2→0x0F、1→0x03）；死亡(0) = 全灭。身份由数码管 1/2 承担。 */
#define DL_HP_P1        0xD1    /* 下行命令码：玩家1 血量 */
#define DL_HP_P2        0xD2    /* 下行命令码：玩家2 血量 */
#define DL_HP_MAX       3       /* 血量上限（满血=3 命） */

/*--------------------------- 系统变量（必须定义） ---------------------------*/
/* 必须：定义系统工作时钟频率(Hz)，与实际工作频率（STC-ISP 下载时选择）一致。
 * STC-B 学习板默认外部晶振 11.0592MHz；若改用内部IRC等频率，
 * 需同步修改此处与 STC-ISP 中的频率选择。 */
code unsigned long SysClock = 11059200;

/* 选用显示模块时必须：数码管显示译码表（用户可修改/增减）。
 * 数码管用于身份显示（最左位 1/2），LED 用于血量条（见下行血量部分）。 */
#ifdef _displayer_H_
code char decode_table[] = {0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f,
                            0x00,0x08,0x40,0x01,0x41,0x48,
                            0x3f|0x80,0x06|0x80,0x5b|0x80,0x4f|0x80,0x66|0x80,
                            0x6d|0x80,0x7d|0x80,0x07|0x80,0x7f|0x80,0x6f|0x80};
#endif

/*--------------------------------- 用户全局变量 ----------------------------*/
static unsigned char navHold;       /* 导航键按住状态：bit0左 bit1右 bit2上 bit3下 */
static unsigned char firePending;   /* K1 开火待发标志（按下瞬间置1，发完清0）   */
static unsigned char restartPending;/* K2 重开待发标志（按下瞬间置1，发完清0）   */
static unsigned char k3Pending;     /* K3 待发标志（按下瞬间置1，发完清0）       */
static unsigned char txBuf[3];      /* 待发送的 3 字节数据包                     */

/* ---- LED 血量下行（UART_IF=0 板载 USB 才启用接收；EXT 备选无下行）---- */
#if (UART_IF == 0)
static unsigned char dlRxBuf[3];    /* 串口1 接收缓冲：PC 下行血量帧 */
/* 接收包头匹配：AA + 本板命令码（只对发给自己的血量帧产生收包事件） */
static unsigned char dlHead[2] = {PKT_HEADER, (PLAYER_ID == 1) ? DL_HP_P1 : DL_HP_P2};

/* LED 血条译码：血量 0/1/2/3 → LedPrint 值（bit=1 亮）：
 *   3 满血：L0~L5 六灯全亮；2：L0~L3；1：L0~L1；0（死亡）：全灭 */
static code unsigned char hpLedTable[4] = {0x00, 0x03, 0x0F, 0x3F};

/* 应用一帧血量：夹取 0~3 后按血条规则刷新 LED */
static void hpLedApply(unsigned char hp)
{
    if (hp > DL_HP_MAX)
    {
        hp = DL_HP_MAX;
    }
    LedPrint(hpLedTable[hp]);
}

/* 串口1 收包事件：收到 AA + 本板命令码 + 血量 的 3 字节帧 → 刷新 LED 血条 */
void myUart1Rxd_callback(void)
{
    if (dlRxBuf[0] != PKT_HEADER)
    {
        return;
    }
#if (PLAYER_ID == 1)
    if (dlRxBuf[1] != DL_HP_P1)
    {
        return;
    }
#else
    if (dlRxBuf[1] != DL_HP_P2)
    {
        return;
    }
#endif
    hpLedApply(dlRxBuf[2]);
}
#endif  /* UART_IF == 0 */

/*--------------------------------- 串口发送层 -------------------------------*/
/* 按 UART_IF 选择串口1/2，统一发送接口，业务代码不感知差异 */
#if (UART_IF == 0)
    /* 查询串口1发送是否空闲 */
    static unsigned char uart_tx_free(void)
    {
        return (GetUart1TxStatus() == enumUart1TxFree);
    }
    /* 发送 3 字节数据包：只要未返回"发送失败"即视为请求已被系统接受。
     * （发送前已确保 TxFree，正常必然成功；此处用 !=Failure 而非 ==OK，
     *   避免对 BSP 返回值的数值语义做过度假设，保证开火位可靠清除） */
    static unsigned char uart_send_packet(void)
    {
        return (Uart1Print(txBuf, 3) != enumUart1TxFailure);
    }
#else
    /* 查询串口2发送是否空闲 */
    static unsigned char uart_tx_free(void)
    {
        return (GetUart2TxStatus() == enumUart2TxFree);
    }
    /* 发送 3 字节数据包：只要未返回"发送失败"即视为请求已被系统接受 */
    static unsigned char uart_send_packet(void)
    {
        return (Uart2Print(txBuf, 3) != enumUart2TxFailure);
    }
#endif

/*----------------------------- 100ms 周期回调 -------------------------------*/
/* 每 100ms 由系统调用一次：
 *  ① 轮询导航四方向（边沿事件，按住持续通过状态位保持）
 *  ② 检测 K1/K2/K3 按下瞬间 → 置各自单发待发标志（K3 供 PC 开始界面用）
 *  ③ 组包并发往 PC（开火/重开/K3 位仅随本包发送一次，单发不重发）
 * 已知边界：按键事件为"查询一次有效"，本回调按 100ms 周期轮询，
 *  极短(<100ms)的"点一下立刻松开"可能只捕获到 Release 事件而漏掉 Press；
 *  游戏方向键均为"按住持续"操作，实际不受影响；如需更灵敏可在 10mS
 *  回调中轮询导航键（代价是回调更频繁），当前实现按题目要求保持在 100mS。 */
void my100mS_callback(void)
{
    unsigned char act;          /* 查询到的按键动作 */

    /* ① 左：按住置 bit0，抬起清 bit0 */
    act = GetAdcNavAct(enumAdcNavKeyLeft);
    if (act == enumKeyPress)         navHold |=  KEY_LEFT;
    else if (act == enumKeyRelease)  navHold &= (unsigned char)~KEY_LEFT;

    /* ① 右：按住置 bit1，抬起清 bit1 */
    act = GetAdcNavAct(enumAdcNavKeyRight);
    if (act == enumKeyPress)         navHold |=  KEY_RIGHT;
    else if (act == enumKeyRelease)  navHold &= (unsigned char)~KEY_RIGHT;

    /* ① 上：按住置 bit2，抬起清 bit2 */
    act = GetAdcNavAct(enumAdcNavKeyUp);
    if (act == enumKeyPress)         navHold |=  KEY_UP;
    else if (act == enumKeyRelease)  navHold &= (unsigned char)~KEY_UP;

    /* ① 下：按住置 bit3，抬起清 bit3 */
    act = GetAdcNavAct(enumAdcNavKeyDown);
    if (act == enumKeyPress)         navHold |=  KEY_DOWN;
    else if (act == enumKeyRelease)  navHold &= (unsigned char)~KEY_DOWN;

    /* ② K1 开火：仅响应"按下"瞬间，置单发待发标志（消抖由 Key 模块完成，
     *    Key 模块内部已完成软件消抖；事件查询一次有效） */
    if (GetKeyAct(enumKey1) == enumKeyPress)
    {
        firePending = 1;
    }

    /* ② K2 重开请求：同上，按下瞬间置位，只随一个包发送 */
    if (GetKeyAct(enumKey2) == enumKeyPress)
    {
        restartPending = 1;
    }

    /* ② K3（PC 开始界面"任意键开始"用）：按下瞬间置位，只随一个包发送；
     *    对战中 PC 忽略 bit6，无任何副作用 */
    if (GetKeyAct(enumKey3) == enumKeyPress)
    {
        k3Pending = 1;
    }

    /* ③ 组包：方向位(0~3) + 开火位(bit4) + 重开位(bit5) + K3 位(bit6) */
    txBuf[0] = PKT_HEADER;
    txBuf[1] = (PLAYER_ID == 1) ? PKT_P1 : PKT_P2;
    txBuf[2] = navHold;
    if (firePending != 0)
    {
        txBuf[2] |= KEY_FIRE;
    }
    if (restartPending != 0)
    {
        txBuf[2] |= KEY_RESTART;
    }
    if (k3Pending != 0)
    {
        txBuf[2] |= KEY_K3;
    }

    /* ④ 发送：发送口空闲才发起；请求被系统成功接收后才清除开火/重开/K3 标志，
     *    保证三者各只随一个数据包发送一次（单发不丢、不重复） */
    if (uart_tx_free() != 0)
    {
        if (uart_send_packet() != 0)
        {
            firePending = 0;
            restartPending = 0;
            k3Pending = 0;
        }
    }
}

/*----------------------------------- 主函数 ---------------------------------*/
void main(void)
{
    DisplayerInit();                /* 1. 显示模块加载 */
    SetDisplayerArea(0, 7);         /*    启用 8 个扫描位（LED L0~L7 正常刷新） */

    /* 2. LED 默认全灭：LED 专用于血量血条（满血6灯/掉血灭灯/死亡全灭），
     *    上电未收到 PC 血量前全灭；身份由数码管最左位 1/2 承担（见 2b）。
     *    （旧版 L0/L7 身份亮灯已由"数码管身份 + LED 血量"取代——用户需求） */
    LedPrint(0x00);
    /* 2b. 数码管显示手柄号：最左一位显示 1 或 2，其余位熄灭
     *     （10 = 译码表"空"，避免上电默认的 00000000 无法区分身份） */
    Seg7Print((PLAYER_ID == 1) ? 1 : 2, 10, 10, 10, 10, 10, 10, 10);

    KeyInit();                      /* 3. 按键模块加载（K1 开火键） */
    AdcInit(ADCexpEXT);             /* 4. ADC 模块加载：导航按键；ADCexpEXT 保留
                                           EXT 口 P1.0/P1.1 数字功能供 UART2 使用 */

#if (UART_IF == 0)
    Uart1Init(9600UL);              /* 5. 串口1：板载 USB 口，9600bps 8N1 */
    SetUart1Rxd(dlRxBuf, 3, dlHead, 2); /* 5b. 串口1 收 PC 下行血量帧
                                             （AA+本板命令码+血量） */
#else
    Uart2Init(9600UL, Uart2UsedforEXT); /* 5. 串口2：EXT 扩展口，9600bps 8N1 */
#endif

    SetEventCallBack(enumEventSys100mS, my100mS_callback);   /* 6. 注册100ms回调 */
#if (UART_IF == 0)
    SetEventCallBack(enumEventUart1Rxd, myUart1Rxd_callback);/* 6b. 下行血量事件 */
#endif

    MySTC_Init();                   /* 7. 系统初始化（必须，只执行一次） */

    while (1)                       /* 8. 主循环：铁律——只允许 MySTC_OS() */
    {
        MySTC_OS();
    }
}

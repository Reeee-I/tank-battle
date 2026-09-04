/*==============================================================================
 * 双人坦克对战 - 485 手柄端程序（STC_B 学习板 / STC15F2K60S2）
 *------------------------------------------------------------------------------
 * 功能：作为 RS-485 总线上的一台"从机手柄"。两块完全相同的开发板分别作为
 *       玩家1/玩家2 的手柄，被第三块"中转板"（485 轮询主机，485_Relay.hex）
 *       每 100ms 点名一次；被点到名时，本板把当前按键状态打包成 3 字节数据包
 *       应答给中转板，由中转板经 USB(串口1) 原样转发给 PC。
 *       PC 端协议与旧"USB 直连"方案完全一致，PC 端程序无需任何修改。
 *
 * 区分玩家：仅通过编译宏 PLAYER_ID 区分（见下方宏定义）：
 *     PLAYER_ID = 1  → 数码管最左位显示"1"，应答包玩家号 0x01，
 *                      被点名码 0xE1（玩家1 手柄）
 *     PLAYER_ID = 2  → 数码管最左位显示"2"，应答包玩家号 0x02，
 *                      被点名码 0xE2（玩家2 手柄）
 *   （身份显示 = 数码管 1/2；LED 专用于血量：显示本板所控坦克的血条——
 *     满血3=L0~L5 六灯、每掉 1 血灭右侧 2 灯、死亡全灭——用户需求）
 *
 * 板间轮询协议（485 总线，9600 bps，8 数据位 1 停止位 无校验，半双工）：
 *     中转板点名帧（3 字节）：
 *         字节0 : 0xAA              包头（固定）
 *         字节1 : 0xE1 / 0xE2       点名玩家1 / 玩家2（0xE 前缀与玩家号
 *                                   0x01/0x02 永不冲突）
 *         字节2 : 0x00              填充（对齐 3 字节，保持总线帧对齐）
 *     本板应答帧（3 字节，与原有线协议完全一致，中转板原样转发 PC）：
 *         字节0 : 0xAA              包头（固定）
 *         字节1 : 0x01 / 0x02       玩家号
 *         字节2 : 按键位掩码
 *                 bit0=1 左(左转)   bit1=1 右(右转)   bit2=1 上(前进)
 *                 bit3=1 下(后退)   bit4=1 开火(K1,单发)
 *                 bit5=1 重开请求(K2,单发; PC 仅在结算画面处理)
 *                 bit6=1 K3(单发; PC 开始界面"任意键开始"用, 对战中忽略)
 *     下行血量帧（中转板在总线空闲窗口广播；仅命令码与本板玩家号匹配时生效）：
 *         字节0 : 0xAA              包头（固定）
 *         字节1 : 0xD1 / 0xD2       命令码：玩家1 / 玩家2 血量
 *         字节2 : 血量 0~3（满血=3）→ LED 血条（见上方说明）
 *
 * 发送策略（被点名才应答，杜绝两板自主发包在总线上碰撞）：
 *   - 本板自己的 100ms 定时回调只负责"采样按键"（导航按住状态位 +
 *     K1/K2/K3 按下单发标志），不再自行发送；
 *   - UART2(485) 收包回调按帧第 2 字节分发：收到"本板点名码"的点名帧 →
 *     立即组包应答，应答请求被 Uart2Print 成功接受后才清除开火/重开/K3
 *     单发标志（单发不丢、不重复）；收到"本板血量命令码(D1/D2)"的下行帧
 *     → 只刷新 LED 血条，不应答；
 *   - 其它帧（另一玩家的点名/应答/血量、本板应答回声）在回调内按码过滤
 *     丢弃，不会误应答。
 *
 * 硬件连接：本板 485 接口（A/B）并联到三块板共享的 485 总线；本板不再
 *           直连 PC 数据（板载 USB 仅可作供电）。
 *
 * 注意：
 *   1) SysClock 必须与实际下载频率一致（STC-B 板为 11.0592MHz 晶振）；
 *   2) 主循环中只允许 MySTC_OS()（BSP 铁律），业务全部放入事件回调；
 *   3) 查询型 API（GetKeyAct/GetAdcNavAct）返回"一次性"边沿事件，查询后
 *      自动复位，因此方向键采用"Press 置位 / Release 清位"状态位实现
 *      "按住持续"；100ms 轮询周期与旧方案一致；
 *   4) 串口2 用于 485 时为半双工：发送时不能接收（收发方向由板/库管理）；
 *      总线上任意时刻仅一个发送者（点名由中转板、应答由被点名手柄、
 *      下行血量帧由中转板在空闲窗口发）。
 *
 * 编译环境：Keil uVision4/5 + C51（C89 规范，代码优化 Level 8，内存模式 Small）
 * 工程文件：main_handle.c + MCU\STC_BSP.lib + MCU\inc 头文件目录（共享引用）
 * 生成文件：..\HEX\485_Player1.hex / 485_Player2.hex（统一 HEX 目录）
 *============================================================================*/
#include "STC15F2K60S2.H"   /* 必须：STC15 系列寄存器定义 */
#include "sys.H"            /* 必须：系统初始化/调度/事件回调 */
#include "displayer.h"      /* 显示模块：DisplayerInit / LedPrint / Seg7Print */
#include "Key.H"            /* 按键模块：K1（开火）/K2（重开）/K3（开始用） */
#include "adc.h"            /* ADC 模块：导航按键（上/下/左/右/中） */
#include "uart2.h"          /* 串口2（485 接口）：Uart2Init / Uart2Print */

/*------------------------------- 玩家配置 -----------------------------------*/
#ifndef PLAYER_ID
#define PLAYER_ID   1       /* 玩家号：手柄1 编译时置 1，手柄2 编译时置 2 */
#endif

/* 编译期校验：PLAYER_ID 只允许 1 或 2，防止两板同号静默冲突 */
#if (PLAYER_ID != 1) && (PLAYER_ID != 2)
#error "PLAYER_ID must be 1 (玩家1) or 2 (玩家2) !"
#endif

/*--------------------------- 协议常量（勿改动） ------------------------------*/
#define PKT_HEADER      0xAA    /* 数据包包头 */
#define PKT_P1          0x01    /* 玩家1 号 */
#define PKT_P2          0x02    /* 玩家2 号 */

#define POLL_P1         0xE1    /* 中转板点名码：玩家1 手柄 */
#define POLL_P2         0xE2    /* 中转板点名码：玩家2 手柄 */

/* PC → 中转板 → 485 → 本板 的下行帧（LED 血量联动，3 字节）：
 *     字节0 : 0xAA              包头（固定）
 *     字节1 : 0xD1 / 0xD2       命令码：玩家1 / 玩家2 血量
 *             （D 前缀与玩家号 01/02、点名码 E1/E2 永不冲突）
 *     字节2 : 血量 0~3
 * 中转板在总线空闲窗口把该帧广播到 485 总线，只有命令码与"本板玩家号"
 * 匹配的手柄才会更新 LED；点名应答逻辑不受影响。
 * LED 血条语义：满血(3) = L0~L5 六灯全亮；每掉 1 血灭右侧 2 灯
 * （3→0x3F、2→0x0F、1→0x03）；死亡(0) = 全灭。身份由数码管 1/2 承担。 */
#define DL_HP_P1        0xD1    /* 下行命令码：玩家1 血量 */
#define DL_HP_P2        0xD2    /* 下行命令码：玩家2 血量 */
#define DL_HP_MAX       3       /* 血量上限（满血=3 命） */

#define KEY_LEFT        0x01    /* bit0：左  */
#define KEY_RIGHT       0x02    /* bit1：右  */
#define KEY_UP          0x04    /* bit2：上  */
#define KEY_DOWN        0x08    /* bit3：下  */
#define KEY_FIRE        0x10    /* bit4：开火（K1，单发） */
#define KEY_RESTART     0x20    /* bit5：重开请求（K2，单发；PC 结算画面处理） */
#define KEY_K3          0x40    /* bit6：K3（单发；PC 开始界面"任意键开始"用） */

/*--------------------------- 系统变量（必须定义） ---------------------------*/
/* 系统工作时钟频率(Hz)，必须与 STC-ISP 下载时选择的频率一致。
 * STC-B 学习板默认外部晶振 11.0592MHz。 */
code unsigned long SysClock = 11059200;

/* 选用显示模块时必须：数码管显示译码表（displayer 模块会引用该表）。
 * 索引 0~9：数字0~9；10：空；11~15：下/中/上 横杠段；16~25：带小数点的0~9。 */
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
static unsigned char rxBuf[3];      /* UART2(485) 接收缓冲：点名帧 / 血量帧     */
static unsigned char txBuf[3];      /* 待应答的 3 字节数据包                    */

/* 485 接收包头匹配：只匹配 1 字节 AA，收到完整 3 字节帧后由回调按
 * 第 2 字节（点名码 / 血量命令码）分发——点名与血量帧共用接收通道。 */
static unsigned char headAA[1] = {PKT_HEADER};

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

/*----------------------------- 100ms 周期回调 -------------------------------*/
/* 每 100ms 由系统调用一次，只负责"采样按键"：
 *  ① 轮询导航四方向（边沿事件，按住持续通过状态位保持）
 *  ② 检测 K1/K2/K3 按下瞬间 → 置各自单发待发标志（K3 供 PC 开始界面用）
 * 不发包：应答发送在被点名时（见 myUart2Rxd_callback）进行。
 * 已知边界：按键事件为"查询一次有效"，本回调按 100ms 周期轮询，
 *  极短(<100ms)的"点一下立刻松开"可能只捕获到 Release 而漏掉 Press；
 *  游戏方向键均为"按住持续"操作，实际不受影响（与旧方案行为一致）。 */
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

    /* ② K1 开火：仅响应"按下"瞬间，置单发待发标志（消抖由 Key 模块完成） */
    if (GetKeyAct(enumKey1) == enumKeyPress)
    {
        firePending = 1;
    }

    /* ② K2 重开请求：同上，按下瞬间置位，只随一个应答包发送（PC 结算画面处理） */
    if (GetKeyAct(enumKey2) == enumKeyPress)
    {
        restartPending = 1;
    }

    /* ② K3（PC 开始界面"任意键开始"用）：按下瞬间置位，只随一个应答包发送；
     *    对战中 PC 忽略 bit6，无任何副作用 */
    if (GetKeyAct(enumKey3) == enumKeyPress)
    {
        k3Pending = 1;
    }
}

/*---------------------------- 485 收包事件回调 ------------------------------*/
/* 收到一个 3 字节、AA 开头的帧（中转板点名 / 下行血量帧）时由系统调用，
 * 按第 2 字节分发：
 *   - 本板血量命令码（D1/D2）→ 刷新 LED 血条（不应答）；
 *   - 本板点名码（E1/E2）   → 组包应答给中转板（原有逻辑）；
 *   - 其它（他人点名/他人应答帧）→ 丢弃。
 * 应答请求被 Uart2Print 成功接受后才清除开火/重开/K3 标志，保证三者
 * 各只随一个应答包发送一次（单发不丢、不重复）。 */
void myUart2Rxd_callback(void)
{
    unsigned char code2;        /* 帧第 2 字节：点名码 或 血量命令码 */

    /* 防御性复核：包头必须匹配（接收层已按 AA 过滤，此处双保险） */
    if (rxBuf[0] != PKT_HEADER)
    {
        return;
    }
    code2 = rxBuf[1];

    /* 下行血量帧：AA + 本板命令码 + 血量 → LED 血条（满血6灯…死亡全灭） */
#if (PLAYER_ID == 1)
    if (code2 == DL_HP_P1)
#else
    if (code2 == DL_HP_P2)
#endif
    {
        hpLedApply(rxBuf[2]);
        return;
    }

    /* 点名帧：只有"本板点名码"才应答；他人点名 / 他人应答 / 杂散帧丢弃 */
#if (PLAYER_ID == 1)
    if (code2 != POLL_P1)
#else
    if (code2 != POLL_P2)
#endif
    {
        return;
    }

    /* 发送口空闲才发起应答（9600bps 下 3 字节约 3.1ms，轮询间隔 100ms，
     * 正常情况下恒为空闲；若忙则放弃本次应答，等下一次点名，不阻塞） */
    if (GetUart2TxStatus() != enumUart2TxFree)
    {
        return;
    }

    /* 组包：方向位(0~3) + 开火位(bit4) + 重开位(bit5) + K3 位(bit6)，
     * 与原有线协议完全一致，中转板原样转发给 PC */
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

    /* 应答发送：只要未返回"发送失败"即视为请求已被系统接受
     * （发送前已确保 TxFree，正常必然成功；此处用 !=Failure 而非 ==OK，
     *   避免对 BSP 返回值的数值语义做过度假设） */
    if (Uart2Print(txBuf, 3) != enumUart2TxFailure)
    {
        firePending = 0;
        restartPending = 0;
        k3Pending = 0;
    }
}

/*----------------------------------- 主函数 ---------------------------------*/
void main(void)
{
    DisplayerInit();                /* 1. 显示模块加载 */
    SetDisplayerArea(0, 7);         /*    启用 8 个扫描位（LED/数码管正常刷新） */

    /* 2. LED 默认全灭：LED 专用于血量血条（满血6灯/掉血灭灯/死亡全灭），
     *    上电未收到 PC 血量前全灭；身份由数码管最左位 1/2 承担（见 2b）。
     *    （旧版 L0/L7 身份亮灯已由"数码管身份 + LED 血量"取代——用户需求） */
    LedPrint(0x00);
    /* 2b. 数码管显示手柄号：最左一位显示 1 或 2，其余位熄灭
     *     （10 = 译码表"空"） */
    Seg7Print((PLAYER_ID == 1) ? 1 : 2, 10, 10, 10, 10, 10, 10, 10);

    KeyInit();                      /* 3. 按键模块加载（K1 开火 / K2 重开 / K3 开始） */
    AdcInit(ADCexpEXT);             /* 4. ADC 模块加载：导航按键；ADCexpEXT 保留
                                           485(UART2) 所用 P1.0/P1.1 数字功能 */

    Uart2Init(9600UL, Uart2Usedfor485); /* 5. 串口2：485 接口，9600bps 8N1 半双工 */

    SetUart2Rxd(rxBuf, 3, headAA, 1); /* 6. 485 收 3 字节、AA 开头的帧
                                             （点名帧 / 下行血量帧） */

    SetEventCallBack(enumEventSys100mS, my100mS_callback);   /* 7. 100ms 采样 */
    SetEventCallBack(enumEventUart2Rxd, myUart2Rxd_callback);/* 8. 点名应答 */

    MySTC_Init();                   /* 9. 系统初始化（必须，只执行一次） */

    while (1)                       /* 10. 主循环：铁律——只允许 MySTC_OS() */
    {
        MySTC_OS();
    }
}

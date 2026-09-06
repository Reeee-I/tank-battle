/*==============================================================================
 * 双人坦克对战 - 蓝牙手柄端程序【测试开发版】（STC_B 学习板 / STC15F2K60S2）
 *------------------------------------------------------------------------------
 * 【测试开发说明】
 *   本文件是"第三种通信方式：蓝牙无线通信"的【测试开发】固件，按开发原则
 *   暂存于 测试开发-蓝牙模块\01_蓝牙手柄固件\，不替代、不修改任何既有方案
 *   源文件；待测试完成、确认通过后再按目录规则并入正式结构。
 *   底本 = 01_下位机程序/01_有线模式/main.c（音效版）。与原版唯一差异是
 *   通信通道：由"板载 USB 串口1"改为"EXT 扩展口 串口2(TTL) + 外接蓝牙
 *   透传模块"；因蓝牙透传为全双工，本版同时支持 PC → 板下行血量帧
 *   （LED 血条 + 被击中/结束音效），优于有线版 EXT 备选(UART_IF=1)
 *   的"纯上行"接法。
 *
 * 功能：两块完全相同的开发板分别作为玩家1/玩家2 的"蓝牙手柄"：
 *   - 板载 USB 仅作供电（接充电头/充电宝），不连电脑数据线；
 *   - 按键状态经 板 UART2(EXT) → 蓝牙模块 → PC 蓝牙虚拟 COM，
 *     每 100ms 上报一次（9600 bps 8N1，3 字节帧与既有协议完全一致，
 *     PC 端程序零改动，按包内容自动绑定玩家）；
 *   - 接收 PC 下行"血量帧"AA D1/D2 HP，把板载 LED(L0~L5) 显示为所控
 *     坦克的血条（满血3=6灯全亮；每掉 1 血灭右侧 2 灯；死亡=全灭），
 *     并在血量下降沿播"被击中/游戏结束"音效（与有线/485 手柄一致）。
 *
 * 区分玩家：仅通过编译宏 PLAYER_ID 区分（同既有方案）：
 *     PLAYER_ID = 1  → 数码管最左位显示"1"，发送玩家号 0x01
 *     PLAYER_ID = 2  → 数码管最左位显示"2"，发送玩家号 0x02
 *   （身份显示 = 数码管 1/2；LED 专用于血量条——用户需求）
 *
 * 通信协议（9600 bps、8 数据位、1 停止位、无校验，3 字节定长帧）：
 *   上行（本板 → PC，每 100ms 一次，不按键也发=心跳）：
 *       字节0 : 0xAA                        包头（固定）
 *       字节1 : 0x01(玩家1)/0x02(玩家2)     玩家号
 *       字节2 : 按键位掩码
 *               bit0=1 左(左转)  bit1=1 右(右转)  bit2=1 上(前进)
 *               bit3=1 下(后退)  bit4=1 开火(K1,单发)  bit5=1 重开请求(K2,单发)
 *               bit6=1 K3(单发; PC 开始界面"任意键开始"用, 对战中忽略)
 *   下行（PC → 本板，LED 血量联动）：
 *       字节0 : 0xAA                        包头（固定）
 *       字节1 : 0xD1(玩家1)/0xD2(玩家2)     下行命令码（血量）
 *       字节2 : 血量 0~3（满血=3）
 *
 * 硬件连接（蓝牙模块 <-> 开发板 EXT 扩展口，杜邦线交叉）：
 *       蓝牙模块 RXD ← 板 TXD2（P1.1）
 *       蓝牙模块 TXD → 板 RXD2（P1.0，具体位置以板面丝印为准）
 *       蓝牙模块 GND <-> 板 GND（必须共地）
 *       蓝牙模块 VCC ← 5V（HC-05/06 常见供电方式，以模块说明书为准）
 *   详见测试文档《02_测试文档/接线与模块配置.md》。
 *   若板面未引出 RXD2（下行无通路），本固件仍可正常上行遥控，仅 LED
 *   血量下行不可用（等同既有"纯上行"接法，不属固件缺陷）。
 *
 * 注意（与既有方案相同的 BSP 铁律）：
 *   1) SysClock 必须与 STC-ISP 下载时选择的频率一致
 *      （STC-B 板为 11.0592MHz 外部晶振）；
 *   2) 主循环中只允许 MySTC_OS()，业务全部放入事件回调；
 *   3) 查询型 API（GetKeyAct/GetAdcNavAct）返回"一次性"边沿事件，
 *      查询后自动复位；因此方向键用"Press 置位 / Release 清位"状态位
 *      实现"按住持续发送"；K1 开火、K2 重开、K3 均只在 Press 瞬间置
 *      单发标志。
 *
 * 编译环境：Keil uVision4/5 + C51（C89 规范，代码优化 Level 8，Small 内存）
 * 工程文件：BT_Player1.uvproj（Define PLAYER_ID=1）
 *           BT_Player2.uvproj（Define PLAYER_ID=2）
 *           共享资源引用（不在本目录复制）：
 *             ..\..\01_下位机程序\common\inc        （头文件 Include 路径）
 *             ..\..\01_下位机程序\common\STC_BSP.lib
 *             ..\..\01_下位机程序\04_音效模块\sound_effect.c
 * 输出 HEX：测试开发-蓝牙模块\HEX\BT_Player1.hex / BT_Player2.hex（测试期专用）
 *============================================================================*/
#include "STC15F2K60S2.H"   /* 必须：STC15 系列寄存器定义 */
#include "sys.H"            /* 必须：系统初始化/调度/事件回调 */
#include "displayer.h"      /* 显示模块：DisplayerInit / LedPrint / Seg7Print */
#include "Key.H"            /* 按键模块：K1（开火）/K2（重开）/K3（开始用） */
#include "adc.h"            /* ADC 模块：导航按键（上/下/左/右/中） */
#include "uart2.h"          /* 串口2（EXT 扩展口 TTL）：Uart2Init / Uart2Print /
                               SetUart2Rxd —— 外接蓝牙透传模块 */
#include "sound_effect.h"  /* 【音效】蜂鸣器音效模块（玩家手边板启用） */

/*------------------------------- 玩家配置 -----------------------------------*/
#ifndef PLAYER_ID
#define PLAYER_ID   1       /* 玩家号：蓝牙手柄1 编译时置 1，手柄2 编译时置 2 */
#endif

/* 编译期校验：PLAYER_ID 只允许 1 或 2，防止两板同号静默冲突 */
#if (PLAYER_ID != 1) && (PLAYER_ID != 2)
#error "PLAYER_ID must be 1 (玩家1) or 2 (玩家2) !"
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
 *     E1/E2 永不冲突）。蓝牙为"一块板一条独立链路"，PC 只往本板 COM 下发
 *     本玩家的血量帧；接收层按"AA 包头"收满 3 字节后，由回调按第 2 字节
 *     过滤：仅处理发给本板（PLAYER_ID 对应命令码）的帧，其余一律丢弃。
 * LED 血条语义：满血(3) = L0~L5 六灯全亮；每掉 1 血灭右侧 2 灯
 * （3→0x3F、2→0x0F、1→0x03）；死亡(0) = 全灭。身份由数码管 1/2 承担。 */
#define DL_HP_P1        0xD1    /* 下行命令码：玩家1 血量 */
#define DL_HP_P2        0xD2    /* 下行命令码：玩家2 血量 */
#define DL_HP_MAX       3       /* 血量上限（满血=3 命） */

/*--------------------------- 系统变量（必须定义） ---------------------------*/
/* 系统工作时钟频率(Hz)，必须与 STC-ISP 下载时选择的频率一致。
 * STC-B 学习板默认外部晶振 11.0592MHz。 */
code unsigned long SysClock = 11059200;

/* 选用显示模块时必须：数码管显示译码表（displayer 模块会引用该表）。
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

/* ---- LED 血量下行（蓝牙全双工链路，经串口2 EXT 接收）---- */
static unsigned char rxBuf[3];      /* 串口2 接收缓冲：PC 下行血量帧 */
/* 接收包头匹配：只匹配 1 字节 AA，收到完整 3 字节帧后由回调按
 * 第 2 字节（血量命令码）过滤——本链路只会有发给本板的下行帧，
 * 过滤作双保险，也杜绝误把杂散字节当血量。 */
static unsigned char headAA[1] = {PKT_HEADER};

/* LED 血条译码：血量 0/1/2/3 → LedPrint 值（bit=1 亮）：
 *   3 满血：L0~L5 六灯全亮；2：L0~L3；1：L0~L1；0（死亡）：全灭 */
static code unsigned char hpLedTable[4] = {0x00, 0x03, 0x0F, 0x3F};
/* 【音效】上次血量（0xFF=尚未收到第一帧，用于血量下降沿判音） */
static unsigned char lastHp = 0xFF;

/* 应用一帧血量：夹取 0~3 后按血条规则刷新 LED */
static void hpLedApply(unsigned char hp)
{
    if (hp > DL_HP_MAX)
    {
        hp = DL_HP_MAX;
    }
    LedPrint(hpLedTable[hp]);
}

/*----------------------------- 串口2 发送层 --------------------------------*/
/* 查询串口2(EXT/蓝牙)发送是否空闲 */
static unsigned char uart_tx_free(void)
{
    return (GetUart2TxStatus() == enumUart2TxFree);
}

/* 发送 3 字节数据包：只要未返回"发送失败"即视为请求已被系统接受
 * （发送前已确保 TxFree，正常必然成功；此处用 !=Failure 而非 ==OK，
 *   避免对 BSP 返回值的数值语义做过度假设，保证开火位可靠清除） */
static unsigned char uart_send_packet(void)
{
    return (Uart2Print(txBuf, 3) != enumUart2TxFailure);
}

/*--------------------------- 串口2 收包事件回调 -----------------------------*/
/* 收到一帧 3 字节、AA 开头的下行帧（PC → 蓝牙 → 本板）时由系统调用：
 *   第 2 字节 = 本板玩家对应的血量命令码（D1/D2）→ 刷新 LED 血条，
 *              并在血量下降沿触发被击中/游戏结束音效（同既有方案）；
 *   其它码 → 直接丢弃（本链路理论不会出现，双保险而已）。 */
void myUart2Rxd_callback(void)
{
    /* 防御性复核：包头必须匹配（接收层已按 AA 过滤，此处双保险） */
    if (rxBuf[0] != PKT_HEADER)
    {
        return;
    }
#if (PLAYER_ID == 1)
    if (rxBuf[1] != DL_HP_P1)
    {
        return;
    }
#else
    if (rxBuf[1] != DL_HP_P2)
    {
        return;
    }
#endif
    hpLedApply(rxBuf[2]);

    /* 【音效】下行血量联动发声（规则与有线/485 手柄一致）：
     *   - 血量下降（本车被击中）→ SOUND_DAMAGE（500Hz/200ms 低鸣）；
     *   - 血量归零（游戏结束） → SOUND_GAMEOVER（1500→500Hz 下扫，高优先级）；
     *   - 首帧只建立血量基线不发声；回血上升、重发相同血量均不发声，
     *     只在"血量下降沿"触发——PC 反复补发当前血量也不会重复响。 */
    if ((lastHp != 0xFF) && (rxBuf[2] < lastHp))
    {
        if (rxBuf[2] == 0)
        {
            Sound_Play(SOUND_GAMEOVER);
        }
        else
        {
            Sound_Play(SOUND_DAMAGE);
        }
    }
    lastHp = rxBuf[2];
}

/*----------------------------- 10ms 周期回调（音效） ------------------------*/
/* 每 10ms 由系统调用一次，驱动蜂鸣器音效状态机。 */
void my10mS_callback(void)
{
    Sound_Tick();
}

/*----------------------------- 100ms 周期回调 -------------------------------*/
/* 每 100ms 由系统调用一次（与既有手柄方案完全一致）：
 *  ① 轮询导航四方向（边沿事件，按住持续通过状态位保持）
 *  ② 检测 K1/K2/K3 按下瞬间 → 置各自单发待发标志（K3 供 PC 开始界面用）
 *  ③ 组包并发往 PC（蓝牙链路为"一板一链路"，本板自主定时发包，无需点名）
 * 已知边界：按键事件为"查询一次有效"，本回调按 100ms 周期轮询，
 *  极短(<100ms)的"点一下立刻松开"可能只捕获到 Release 而漏掉 Press；
 *  游戏方向键均为"按住持续"操作，实际不受影响（与既有方案行为一致）。 */
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
        Sound_Play(SOUND_FIRE);     /* 【音效】K1 开火瞬间：1500Hz/50ms 短促"哒" */
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

    /* 【音效】方向键按住期间：每 100ms 请求一次"移动"音
     * （800Hz/20ms；忙时由音效模块按优先级裁决，本处先查忙避免无效请求） */
    if ((navHold != 0) && (Sound_IsBusy() == 0))
    {
        Sound_Play(SOUND_MOVE);
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

    /* ④ 发送：发送口空闲才发起；请求被系统成功接受后才清除开火/重开/K3 标志，
     *    保证三者各只随一个数据包发送一次（单发不丢、不重复）。
     *    9600bps 下 3 字节约 3.1ms，100ms 周期内恒为空闲；若偶发忙则放弃
     *    本次发包（心跳下一周期自然补上），不阻塞。 */
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
    SetDisplayerArea(0, 7);         /*    启用 8 个扫描位（LED/数码管正常刷新） */

    /* 2. LED 默认全灭：LED 专用于血量血条（满血6灯/掉血灭灯/死亡全灭），
     *    上电未收到 PC 血量前全灭；身份由数码管最左位 1/2 承担（见 2b）。
     *    （旧版 L0/L7 身份亮灯已由"数码管身份 + LED 血量"取代——用户需求） */
    LedPrint(0x00);
    /* 2b. 数码管显示手柄号：最左一位显示 1 或 2，其余位熄灭
     *     （10 = 译码表"空"，避免上电默认的 00000000 无法区分身份） */
    Seg7Print((PLAYER_ID == 1) ? 1 : 2, 10, 10, 10, 10, 10, 10, 10);

    KeyInit();                      /* 3. 按键模块加载（K1 开火 / K2 重开 / K3 开始） */
    AdcInit(ADCexpEXT);             /* 4. ADC 模块加载：导航按键；ADCexpEXT 保留
                                           串口2(EXT) 所用 P1.0/P1.1 数字功能 */

    Uart2Init(9600UL, Uart2UsedforEXT); /* 5. 串口2：EXT 扩展口(TTL) 外接蓝牙
                                             透传模块，9600bps 8N1 全双工 */
    SetUart2Rxd(rxBuf, 3, headAA, 1); /* 5b. 串口2 收 PC 下行血量帧（AA 开头，
                                             3 字节，回调内按命令码过滤） */

    Sound_Init();                       /* 【音效】蜂鸣器音效模块加载（内部 BeepInit） */
    SetEventCallBack(enumEventSys10mS, my10mS_callback); /* 【音效】注册 10ms 音序驱动 */
    SetEventCallBack(enumEventSys100mS, my100mS_callback);   /* 6. 100ms 采样上报 */
    SetEventCallBack(enumEventUart2Rxd, myUart2Rxd_callback);/* 7. 下行血量事件 */

    MySTC_Init();                   /* 8. 系统初始化（必须，只执行一次） */

    while (1)                       /* 9. 主循环：铁律——只允许 MySTC_OS() */
    {
        MySTC_OS();
    }
}

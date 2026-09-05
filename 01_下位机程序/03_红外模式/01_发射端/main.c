/*==============================================================================
 * ========================  【音效测试版】  ==================================
 *
 * 本文件由 无线手柄/HEX_A_IR_Tx/main.c 派生，仅叠加"蜂鸣器音效"，其余代码与原版逐行一致。
 * 角色：红外无线发送端（HEX-A，玩家手边）→ SOUND_ENABLED = 1
 *
 * 修改点总览（代码内改动处均带【音效】标注）：
 *   ① 包含音效模块头文件 sound_effect.h；
 *   ② main() 增加 Sound_Init()（内部自动调用 BSP BeepInit()）；
 *   ③ 新增 my10mS_callback() 并注册到 10ms 系统事件，驱动 Sound_Tick() 音序状态机；
 *   ④ K1（开火）按下瞬间 → Sound_Play(SOUND_FIRE)（1500Hz/50ms 高优先级）；
 *   ⑤ 方向键按住期间每 100ms → Sound_Play(SOUND_MOVE)（800Hz/20ms "嗒"声）。
 *   注：红外无线链路为单向（发送端无下行通道），被击中/击中/结束等远端音效
 *      不触发；若以后增加下行通道，可参照有线版用 Sound_Play 触发。
 *   编译：本工程 C51 Define 原为 WIRELESS_TX，无需改动。
 *
 * 使用：把本文件改名 main.c 覆盖到对应 Keil 工程源目录（先备份原文件），
 *  *      并把 sound_effect.c 加入工程、sound_effect.h 与 main.c 放同一目录；
 *  *      详见 sound 目录下的《音效测试与集成说明.md》。
 *============================================================================*/

/*==============================================================================
 * 双人坦克对战 - 红外无线手柄（HEX-A：红外发送端 / 玩家2无线手柄）
 *------------------------------------------------------------------------------
 * 功能：本程序替代原有的"玩家2有线手柄"。板载导航按键（上/下/左/右）作为
 *       移动/转向输入，K1 作为开火键（按下瞬间单发），K2 作为对局结束后的
 *       重开请求键（按下瞬间单发，PC 仅在结算画面处理），K3 供 PC 开始界面
 *       "任意键开始"使用（按下瞬间单发，对战中忽略）。按键状态每 100ms
 *       打包成 3 字节数据包，通过红外（IR 模块，NEC_R05d 协议）发送给
 *       HEX-B 红外接收端，由 HEX-B 通过串口1（USB）转发给 PC。
 *
 *       数据包格式与现有有线协议完全一致，PC 端无需任何修改即可识别：
 *           字节0 : 0xAA                        包头（固定）
 *           字节1 : 0x02                        玩家号（固定为玩家2）
 *           字节2 : 按键状态位掩码
 *                   bit0=1 左(左转)  bit1=1 右(右转)  bit2=1 上(前进)
 *                   bit3=1 下(后退)  bit4=1 开火(K1,单发)  bit5=1 重开请求(K2,单发)
 *                   bit6=1 K3(单发；PC 开始界面"任意键开始"用，对战中忽略)
 *
 * 发送策略：注册 enumEventSys100mS 定时回调，每 100ms 采集一次按键状态并
 *          调用 IrPrint() 非阻塞发送 3 字节数据包（不按键时也照发，作心跳）。
 *          开火/重开标志只在"发送请求被 IR 模块成功接受"后清除，保证单发不丢。
 *
 * 硬件连接：本板红外发射管（IR_TXD）对准 HEX-B 接收板红外接收管（IR_RXD）；
 *          本板不再需要连接电脑 USB（供电仍可走板载 USB 口）。
 *
 * 注意：
 *   1) SysClock 必须与实际下载频率一致（STC-B 板为 11.0592MHz 晶振）；
 *   2) 主循环只允许 MySTC_OS()（BSP 铁律），业务全部放入事件回调；
 *   3) IR 模块为单工：本板仅发送，不调用 SetIrRxd()，无需接收；
 *   4) 方向键采用"Press 置位 / Release 清位"状态位实现按住持续发送；
 *      K1/K2/K3 只在按下瞬间置单发标志（消抖由 Key/ADC 模块完成）。
 *
 * 编译环境：Keil uVision4/5 + C51（C89 规范，内存模式 Small）
 * 工程文件：main.c + STC_BSP.lib + inc 头文件目录（本工程自包含副本）
 * 生成文件：..\..\HEX\IR_Player2.hex（统一 HEX 目录，用 STC-ISP 烧录）
 *
 * 数码管身份显示：上电最左位显示 'A'（= 无线发送端 HEX-A），与有线玩家2
 *                （显示 '2'）、无线接收端（显示 'b'）相区分；L7 常亮表示
 *                本机属于玩家2 通道（与原有线玩家2板一致）。
 *============================================================================*/
#include "STC15F2K60S2.H"   /* 必须：STC15 系列寄存器定义 */
#include "sys.H"            /* 必须：系统初始化/调度/事件回调 */
#include "displayer.h"      /* 显示模块：DisplayerInit / LedPrint / Seg7Print */
#include "Key.H"            /* 按键模块：K1（开火）/ K2（重开请求）/ K3（开始用） */
#include "adc.h"            /* ADC 模块：导航按键（上/下/左/右/中） */
#include "IR.h"             /* 红外模块：IrInit / IrPrint（NEC_R05d） */
#include "sound_effect.h"  /* 【音效】蜂鸣器音效模块（玩家手边板启用） */

/*--------------------------- 协议常量（勿改动） ------------------------------*/
#define PKT_HEADER      0xAA    /* 数据包包头 */
#define PKT_P2          0x02    /* 玩家2 号（本无线手柄固定为玩家2） */

#define KEY_LEFT        0x01    /* bit0：左  */
#define KEY_RIGHT       0x02    /* bit1：右  */
#define KEY_UP          0x04    /* bit2：上  */
#define KEY_DOWN        0x08    /* bit3：下  */
#define KEY_FIRE        0x10    /* bit4：开火（K1，单发） */
#define KEY_RESTART     0x20    /* bit5：重开请求（K2，单发；PC 结算画面处理） */
#define KEY_K3          0x40    /* bit6：K3（单发；PC 开始界面"任意键开始"用，对战中忽略） */

/*--------------------------- 系统变量（必须定义） ---------------------------*/
/* 系统工作时钟频率(Hz)，必须与 STC-ISP 下载时选择的频率一致。
 * STC-B 学习板默认外部晶振 11.0592MHz。 */
code unsigned long SysClock = 11059200;

/* 选用显示模块时必须：数码管显示译码表（displayer 模块会引用该表）。
 * 索引 0~9：数字0~9；10：空；11~15：下/中/上 横杠段；16~25：带小数点的0~9；
 * 追加索引 26：'A'（无线发送端标识）、27：'b'（无线接收端标识），
 * 用于把本板与有线玩家1("1")、玩家2("2") 区分开。 */
#ifdef _displayer_H_
code char decode_table[] = {0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f,
                            0x00,0x08,0x40,0x01,0x41,0x48,
                            0x3f|0x80,0x06|0x80,0x5b|0x80,0x4f|0x80,0x66|0x80,
                            0x6d|0x80,0x7d|0x80,0x07|0x80,0x7f|0x80,0x6f|0x80,
                            0x77,0x7c};   /* 26:'A' 发送端  27:'b' 接收端 */
#endif

/* 数码管标识索引（对应上面译码表的追加段） */
#define SEG_A       26      /* 'A'：无线发送端（HEX-A） */
#define SEG_b       27      /* 'b'：无线接收端（HEX-B，本工程不使用） */

/*--------------------------------- 用户全局变量 ----------------------------*/
static unsigned char navHold;       /* 导航键按住状态：bit0左 bit1右 bit2上 bit3下 */
static unsigned char firePending;   /* K1 开火待发标志（按下瞬间置1，发完清0）   */
static unsigned char restartPending;/* K2 重开待发标志（按下瞬间置1，发完清0）   */
static unsigned char k3Pending;     /* K3 待发标志（按下瞬间置1，发完清0）       */
static unsigned char txBuf[3];      /* 待发送的 3 字节红外数据包                 */

/*----------------------------- 10ms 周期回调（音效） ------------------------*/
/* 【音效·测试新增】每 10ms 由系统调用一次，驱动蜂鸣器音效状态机。
 * 注意：若日后工程中已有其它 10ms 逻辑，请把 Sound_Tick() 并入既有 10ms
 * 回调，不要在同一个事件上重复注册（sys 模块每个事件只保存一个用户回调）。 */
void my10mS_callback(void)
{
    Sound_Tick();
}

/*----------------------------- 100ms 周期回调 -------------------------------*/
/* 每 100ms 由系统调用一次：
 *  ① 轮询导航四方向（边沿事件，按住持续通过状态位保持）
 *  ② 检测 K1 按下瞬间 → 置开火待发标志；检测 K2 按下瞬间 → 置重开待发标志
 *  ③ 组包（AA, 0x02, 按键状态）并调用 IrPrint() 红外发送
 *  ④ 仅当红外发送请求被系统接受后才清除开火/重开标志（单发不丢、不重复）
 * 已知边界：按键事件为"查询一次有效"，本回调按 100ms 周期轮询，
 *  极短(<100ms)的"点一下立刻松开"可能漏检；方向键均为按住持续操作，
 *  实际不受影响（与原有线手柄程序行为一致）。 */
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
        Sound_Play(SOUND_FIRE);     /* 【音效】K1 开火瞬间：1500Hz/50ms 短促"哒" */
    }

    /* ② K2 重开请求：同上，按下瞬间置位，只随一个包发送（PC 结算画面处理） */
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

    /* 【音效·测试新增】方向键按住期间：每 100ms 请求一次"移动"音
     * （800Hz/20ms；忙时由音效模块按优先级裁决，本处先查忙避免无效请求） */
    if ((navHold != 0) && (Sound_IsBusy() == 0))
    {
        Sound_Play(SOUND_MOVE);
    }

    /* ③ 组包：方向位(0~3) + 开火位(bit4) + 重开位(bit5) + K3 位(bit6)，
     *    与原有线协议一致 */
    txBuf[0] = PKT_HEADER;
    txBuf[1] = PKT_P2;
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

    /* ④ 红外发送：IrPrint() 为 NEC PWM 编码、非阻塞发送（约 1uS 返回）。
     * 返回 enumIrTxFailure 表示红外正忙（上一包未发完），此时不清除
     * 开火/重开/K3 标志，下一 100ms 周期自动重发，保证单发事件不丢失。
     * （每包 3 字节约需 30ms 发送，100ms 周期留有充足余量。） */
    if (IrPrint(txBuf, 3) != enumIrTxFailure)
    {
        firePending = 0;
        restartPending = 0;
        k3Pending = 0;
    }
}

/*----------------------------------- 主函数 ---------------------------------*/
void main(void)
{
    DisplayerInit();                /* 1. 显示模块加载（提供显示刷新定时基准） */
    SetDisplayerArea(0, 7);         /*    启用 8 个扫描位（LED L0~L7 正常刷新） */

    /* 2. 点亮身份 LED：L7 亮 = 玩家2 无线手柄（与原玩家2有线板一致） */
    LedPrint(0x80);                 /* bit7=1 → L7 亮 */

    /* 2b. 数码管显示本板身份：最左位显示 'A'（= 无线发送端 HEX-A）。
     *     与有线玩家1("1")、有线玩家2("2")、无线接收端("b") 均不同，
     *     一眼即可区分当前板子用途。其余位熄灭（10 = 译码表"空"）。 */
    Seg7Print(SEG_A, 10, 10, 10, 10, 10, 10, 10);

    KeyInit();                      /* 3. 按键模块加载（K1 开火 / K2 重开 / K3 开始） */
    AdcInit(ADCexpEXT);             /* 4. ADC 模块加载：导航按键（方向键） */

    IrInit(NEC_R05d);               /* 5. 红外模块加载：NEC_R05d 协议 */

    Sound_Init();                       /* 【音效】蜂鸣器音效模块加载（内部 BeepInit） */
    SetEventCallBack(enumEventSys10mS, my10mS_callback); /* 【音效】注册 10ms 音序驱动 */
    SetEventCallBack(enumEventSys100mS, my100mS_callback);  /* 6. 注册100ms回调 */

    MySTC_Init();                   /* 7. 系统初始化（必须，只执行一次） */

    while (1)                       /* 8. 主循环：铁律——只允许 MySTC_OS() */
    {
        MySTC_OS();
    }
}

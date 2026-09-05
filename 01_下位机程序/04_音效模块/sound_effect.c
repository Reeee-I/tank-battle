/*==============================================================================
 * 蜂鸣器音效模块实现 sound_effect.c（STC_B 学习板 / STC15F2K60S2）
 *------------------------------------------------------------------------------
 * 本文件与 sound_effect.h 配套。宏 SOUND_ENABLED（在 sound_effect.h 中定义，
 * 默认 1）控制全部实现：
 *   - SOUND_ENABLED = 1：编译真实的音效状态机，仅通过 BSP BeepInit /
 *     SetBeep / GetBeepStatus 操作蜂鸣器；
 *   - SOUND_ENABLED = 0：四个对外函数全部编译为空操作，不包含 Beep.h、
 *     不初始化蜂鸣器，程序行为与未加音效功能时完全一致（无线接收端用）。
 *
 * 时间基准：
 *   Sound_Tick() 由 main 注册的"10ms 系统事件回调"周期性调用，模块内部以
 *   10ms 为基本节拍。BSP 时长换算关系：SetBeep(freq, time) 的发声时长 =
 *   time×10ms，故本模块所有音步时长都取 10ms 的整数倍：
 *     50ms→5、20ms→2、200ms→20、80ms→8、100ms→10。
 *
 * 状态机（同一时刻只播放一个音效，见头文件优先级说明）：
 *   空闲 → 发声 → （音步间隔）→ 发声 … → 空闲
 *   发声期间到达的高优先级请求 → 置"等待空闲"状态，蜂鸣器一空闲立即接播
 *   新音，旧音剩余音步作废（正在响的那一音无法 API 截停，自然响完）。
 *
 * 音量：本模块不改变 BSP 内部 PWM 占空比（无公开接口且禁止直写寄存器），
 *   实际响度由蜂鸣器回路串联限流电阻控制，参见 sound_effect.h 头注释。
 *============================================================================*/
#include "sound_effect.h"

#if (SOUND_ENABLED == 1)

/* BSP 蜂鸣器模块：BeepInit（加载驱动）/ SetBeep（非阻塞发声，忙时返回 Fail）
 * / GetBeepStatus（enumBeepFree 空闲 / enumBeepBusy 发声）。 */
#include "Beep.h"

/*------------------------------ 音效参数表 ----------------------------------*/
/* 一个"音步"：freq=频率(Hz)，ms10=时长参数，实际时长 = ms10×10ms。
 * 所有音步时长均取 10ms 整数倍（BSP 时长参数单位为 10ms）。 */
typedef struct
{
    unsigned int  freq;     /* 发声频率 Hz */
    unsigned char ms10;     /* 时长参数（×10ms） */
} SndTone;

/* 全部音效的音步序列，顺序与音效 ID 一致：
 *   0 FIRE / 1 MOVE / 2 DAMAGE / 3 HIT / 4 GAMEOVER */
static code SndTone sndToneList[] =
{
    {1500,  5},                     /* SOUND_FIRE    ：1500Hz×50ms      单音   */
    { 800,  2},                     /* SOUND_MOVE    ： 800Hz×20ms      单音   */
    { 500, 20},                     /* SOUND_DAMAGE  ： 500Hz×200ms     单音   */
    {1200,  8}, {1200,  8},         /* SOUND_HIT     ：1200Hz×80ms×2    双短促 */
    {1500, 10}, { 500, 10}          /* SOUND_GAMEOVER：1500→500Hz 各100ms 下扫 */
};

/* 各音效在 sndToneList 中的首音步下标 */
static code unsigned char sndStart[SOUND_NUM] = {0, 1, 2, 3, 5};
/* 各音效的音步个数（单音=1，双音/音阶=2） */
static code unsigned char sndStepNum[SOUND_NUM] = {1, 1, 1, 2, 2};
/* 各音效优先级：数值大=优先级高（3高 / 2中 / 1低） */
static code unsigned char sndPrio[SOUND_NUM] = {3, 1, 2, 2, 3};

/*----------------------------- 状态机常量/变量 ------------------------------*/
#define SND_TICK_MS        10      /* Sound_Tick 周期(ms)，与 BSP 时长单位一致 */
#define SND_GAP_MS         10      /* 同一音效相邻音步之间的静音(ms)，使"哒哒"可辨 */
#define SND_GAP_TICKS      1       /* = SND_GAP_MS / SND_TICK_MS（10ms/10ms） */
#define SND_GUARD_MS       100     /* 发声看门狗余量(ms)：防 BSP 状态异常卡死 */

#define SND_ST_IDLE        0       /* 空闲：无音效在播 */
#define SND_ST_WAIT_START  1       /* 已接管音效，正等蜂鸣器空闲后开播（抢占接续） */
#define SND_ST_RINGING     2       /* 蜂鸣器正在发声（等其自然结束） */
#define SND_ST_GAP         3       /* 音步间静音间隔（倒计时） */

static unsigned char sndState;      /* 当前状态（见上状态定义） */
static unsigned char sndId;         /* 当前音效 ID（仅状态非空闲时有效） */
static unsigned char sndStep;       /* 当前音步下标 */
static unsigned char sndGap;        /* 音步间隔剩余计数（单位：个 10ms） */
static unsigned char sndGuard;      /* 发声看门狗剩余计数（单位：个 10ms） */

/*-------------------------- 内部函数（状态机） -------------------------------*/
/* 取当前音步的频率（读 code 表） */
static unsigned int snd_step_freq(void)
{
    return sndToneList[sndStart[sndId] + sndStep].freq;
}

/* 取当前音步的时长参数（单位 10ms，读 code 表） */
static unsigned char snd_step_time(void)
{
    return sndToneList[sndStart[sndId] + sndStep].ms10;
}

/* 向 BSP 申请播放当前音步。
 * 成功返回 1（进入"发声"状态并设置看门狗）；失败返回 0（蜂鸣器仍忙，
 * 调用方保持"等待空闲"状态，下一 10ms tick 自动重试）。 */
static unsigned char snd_start_current_step(void)
{
    unsigned char time;             /* 当前音步时长参数（10ms 单位） */

    time = snd_step_time();
    if (SetBeep(snd_step_freq(), time) == enumSetBeepOK)
    {
        sndState = SND_ST_RINGING;
        sndGuard = (unsigned char)(time + (SND_GUARD_MS / SND_TICK_MS));
        return 1;
    }
    return 0;
}

/* 当前音步已播完（蜂鸣器空闲）：进入下一音步；全部播完则回到空闲 */
static void snd_step_next(void)
{
    sndStep++;
    if (sndStep >= sndStepNum[sndId])
    {
        /* 整个音效播完，复位为空闲 */
        sndState = SND_ST_IDLE;
        sndId = SOUND_NONE;
    }
    else
    {
        /* 音步之间插入一小段静音，让双短促/下扫音阶听感清晰 */
        sndState = SND_ST_GAP;
        sndGap = SND_GAP_TICKS;
    }
}

/* 10ms 状态机主体：按当前状态推进音序 */
static void snd_state_machine(void)
{
    switch (sndState)
    {
    case SND_ST_WAIT_START:
        /* 等待空闲：被抢占的旧音自然响完后，本音立刻接播 */
        if (GetBeepStatus() == enumBeepFree)
        {
            snd_start_current_step();   /* 若仍失败保持本状态，下一 tick 再试 */
        }
        break;

    case SND_ST_RINGING:
        if (GetBeepStatus() == enumBeepFree)
        {
            snd_step_next();            /* 本音已按设定时长响完（BSP 自动停） */
        }
        else
        {
            /* 看门狗倒计时：超过"设定时长+余量"仍 busy 则放弃剩余音步，
             * 避免 BSP 状态异常时模块永远卡在发声态 */
            if (sndGuard != 0)
            {
                sndGuard--;
                if (sndGuard == 0)
                {
                    sndState = SND_ST_IDLE;
                    sndId = SOUND_NONE;
                }
            }
        }
        break;

    case SND_ST_GAP:
        /* 音步间静音倒计时结束 → 请求开播下一音步 */
        if (sndGap != 0)
        {
            sndGap--;
        }
        if (sndGap == 0)
        {
            sndState = SND_ST_WAIT_START;
        }
        break;

    default:
        /* 未知状态兜底：回到空闲，保证模块永不锁死 */
        sndState = SND_ST_IDLE;
        break;
    }
}

/*------------------------------ 对外 API ------------------------------------*/
/* 音效模块初始化：加载 BSP 蜂鸣器驱动并把状态机复位到空闲。
 * 必须在任何 Sound_Play 之前调用一次（在 main() 的 MySTC_Init() 之前）。 */
void Sound_Init(void)
{
    BeepInit();                     /* BSP 蜂鸣器驱动加载（仅此处调用一次） */
    sndState = SND_ST_IDLE;
    sndId = SOUND_NONE;
    sndStep = 0;
    sndGap = 0;
    sndGuard = 0;
}

/* 请求播放一个音效。
 * 裁决规则（详见 sound_effect.h 头注释）：
 *   空闲                     → 立即开始；
 *   忙 + 优先级使能(默认)    → 新音优先级 >= 当前音则抢占（丢弃旧音剩余
 *                              音步，蜂鸣器一空闲立即接播），否则丢弃；
 *   忙 + 优先级关闭          → 直接丢弃（先来先服务，不打断）。
 * 注意：BSP 无 StopBeep 接口，正在响的那一个单音无法 API 截停，只能自然
 * 响完后立刻接新音（详见文件头说明）。 */
void Sound_Play(unsigned char sound_id)
{
    if (sound_id >= SOUND_NUM)
    {
        return;                     /* 非法音效 ID：忽略 */
    }

#if (SOUND_PRIORITY_ENABLE == 1)
    if ((sndState != SND_ST_IDLE) && (sndPrio[sound_id] < sndPrio[sndId]))
    {
        return;                     /* 低优先级不能打断当前音效 */
    }
#else
    if (sndState != SND_ST_IDLE)
    {
        return;                     /* 未开优先级：忙则丢弃本次请求 */
    }
#endif

    /* 接管音效（空闲开播 / 高优先级抢占）：一律从第 0 音步开始 */
    sndId = sound_id;
    sndStep = 0;
    if (GetBeepStatus() == enumBeepFree)
    {
        if (snd_start_current_step() == 0)
        {
            sndState = SND_ST_WAIT_START;   /* 竞态保护：下一 tick 重试 */
        }
    }
    else
    {
        sndState = SND_ST_WAIT_START;       /* 忙：空闲瞬间立即接播新音 */
    }
}

/* 查询音效忙闲：状态机非空闲（正在响 / 等待接播 / 音步间隔）均视为忙。
 * main 可据此避免在忙时重复请求低优先级音（例如方向键每 100ms 的移动音）。 */
unsigned char Sound_IsBusy(void)
{
    return (sndState != SND_ST_IDLE);
}

/* 10ms 周期回调入口：由 main 注册的 10ms 系统事件回调调用。
 * 若工程日后已有其它 10ms 回调，请把本函数并入该回调，不要在同一事件上
 * 重复注册（sys 模块每个事件只保存一个用户回调）。 */
void Sound_Tick(void)
{
    snd_state_machine();
}

#else   /* SOUND_ENABLED == 0：全部编译为空操作，行为与原工程完全一致 */

void Sound_Init(void)
{
}

void Sound_Play(unsigned char sound_id)
{
    /* 空操作：禁用态下不产生任何代码与告警（C51 不对未使用形参告警） */
    sound_id = sound_id;
}

unsigned char Sound_IsBusy(void)
{
    return 0;                       /* 恒空闲（无音效） */
}

void Sound_Tick(void)
{
}

#endif  /* SOUND_ENABLED */

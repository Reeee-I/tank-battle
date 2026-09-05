/*==============================================================================
 * 蜂鸣器音效模块 sound_effect.h（STC_B 学习板 / STC15F2K60S2 / Keil C51 C89）
 *------------------------------------------------------------------------------
 * 功能：
 *   - 为"双人坦克对战"中【玩家手边的所有板子】提供统一蜂鸣器音效接口；
 *   - 有线手柄板、无线红外发送端（都在玩家手边）共用本模块与同一套音效
 *     定义，发声风格完全一致；
 *   - 无线接收端 / 485 中转板（在电脑旁）不启用音效：编译时把 SOUND_ENABLED
 *     置 0（建议在 Keil 工程 C51 Define 中统一写 SOUND_ENABLED=0，或在包含
 *     本头文件的 main.c 顶部先 #define SOUND_ENABLED 0），此时本模块所有
 *     函数编译为空操作，程序行为与未加音效时完全一致。
 *
 * 硬件：STC-B 学习板板载无源蜂鸣器，由 BSP Beep 模块驱动（内部占用 STC
 *       CCP1 通道）。本模块只通过 BSP 公开接口 BeepInit / SetBeep /
 *       GetBeepStatus 操作蜂鸣器，不直接操作任何硬件寄存器（PWM/定时器等），
 *       完全符合"仅使用 BSP API"的约束。
 *
 * 音量控制说明（重要，先读）：
 *   BSP 的 SetBeep(freq, time) 只能设置"频率 + 时长"两个参数；内部 PWM
 *   占空比由库固定为 50%，且库没有提供占空比/幅度调节的公开接口（约束又
 *   不允许直接写 PWM 寄存器），因此音量采用【硬件方案】：在蜂鸣器驱动输出
 *   回路串联 100Ω ~ 1kΩ 限流电阻，使 20~30cm 内清晰可听又不刺耳。
 *     SOUND_VOLUME = 1~2  → 建议串 1kΩ 左右（贴脸桌面对战）
 *     SOUND_VOLUME = 3~5  → 建议串 470Ω ~ 680Ω（默认 3）
 *     SOUND_VOLUME = 6~10 → 建议串 100Ω ~ 220Ω 或直连（需要更响的场合）
 *   调试时从 1kΩ 试起，偏轻则逐档换小（680/510/330/220/100Ω），直到 20cm
 *   距离"清晰可听、不刺耳"为止。SOUND_VOLUME 宏保留为全局音量档位描述，
 *   方便按板子统一标注与将来扩展（默认 3 即 20cm 可听档）。
 *
 * 音效定义（所有玩家手边板子相同，时长均为 10ms 的整数倍以匹配 BSP）：
 *     开火   SOUND_FIRE     1500Hz×50ms     高优先级（可打断其它音）
 *     移动   SOUND_MOVE      800Hz×20ms     低优先级（方向键按住时每 100ms 重复）
 *     被击中 SOUND_DAMAGE    500Hz×200ms    中优先级
 *     击中敌 SOUND_HIT      1200Hz×80ms×2   中优先级（双短促"哒哒"）
 *     游戏结 SOUND_GAMEOVER 1500→500Hz ×100ms×2  高优先级（下扫音阶）
 *
 * 优先级 / 打断规则：
 *   同一时间只播放一个音效。新请求到达时：
 *     - 其优先级 ≥ 当前音效优先级 → 抢占：当前音效"尚未开始"的剩余音步
 *       被丢弃，新音效在蜂鸣器空闲的第一时间接播；
 *     - 其优先级 < 当前音效优先级 → 本次请求直接丢弃（不排队、不积累）。
 *   受 BSP 限制（蜂鸣器发声期间再次调用 SetBeep 会返回 Fail，库无 StopBeep，
 *   又不允许直接操作寄存器），【正在响的单音无法硬性截停】，只能等它按
 *   设定时长自然响完再立刻接新音。因此抢占的实际听感为"最小延迟接续 +
 *   丢弃旧音剩余音步"，对 50~200ms 的短促音效已足够利落（详见 .c 说明）。
 *
 * 集成方法（侵入性最小，具体见各 main 源文件内的【音效】标注）：
 *   1) main() 中调用一次 Sound_Init()；            // 内部自动调用 BSP BeepInit
 *   2) 注册 10ms 周期事件回调，在其中调用 Sound_Tick()；// 驱动音序状态机
 *   3) 在按键/串口事件处调用 Sound_Play(SOUND_XXX)。
 *   SOUND_ENABLED=0 时上述调用均为空操作，代码可以保留不删，不影响原功能。
 *============================================================================*/
#ifndef _SOUND_EFFECT_H_
#define _SOUND_EFFECT_H_

/*----------------------------- 编译开关与参数 --------------------------------*/
/* 全局使能：0=禁用（所有函数编译为空操作）  1=启用（默认）
 * 推荐在 Keil 工程 C51 的 Define 里统一配置，保证 main.c 与 sound_effect.c
 * 两个源文件看到的宏值一致。 */
#ifndef SOUND_ENABLED
#define SOUND_ENABLED           1
#endif

/* 音量档位 1~10（默认 3，对应 20cm 距离清晰可听）。实际响度由蜂鸣器输出
 * 回路的串联限流电阻决定，对应关系见文件头注释。 */
#ifndef SOUND_VOLUME
#define SOUND_VOLUME            3
#endif
#if (SOUND_VOLUME < 1) || (SOUND_VOLUME > 10)
#error "SOUND_VOLUME must be 1..10 !"
#endif

/* 优先级机制开关：1=启用（高优先级抢占低优先级，见文件头规则）
 *                   0=关闭（忙则丢弃新请求，先来先服务，不打断） */
#ifndef SOUND_PRIORITY_ENABLE
#define SOUND_PRIORITY_ENABLE   1
#endif

/*--------------------------------- 音效 ID ----------------------------------*/
#define SOUND_FIRE      0       /* 开火：1500Hz，50ms，高优先级 */
#define SOUND_MOVE      1       /* 移动：800Hz，20ms，低优先级 */
#define SOUND_DAMAGE    2       /* 被击中：500Hz，200ms，中优先级 */
#define SOUND_HIT       3       /* 击中敌人：1200Hz，80ms×2（双短促），中优先级 */
#define SOUND_GAMEOVER  4       /* 游戏结束：1500→500Hz 各 100ms，高优先级 */
#define SOUND_NUM       5       /* 音效总数 */
#define SOUND_NONE      0xFF    /* 无音效（模块内部状态用） */

/*----------------------------------- API ------------------------------------*/
extern void Sound_Init(void);           /* 音效模块初始化（内部含 BSP BeepInit） */
extern void Sound_Play(unsigned char sound_id); /* 请求播放一个音效（带优先级裁决） */
extern unsigned char Sound_IsBusy(void);/* 查询是否有音效正在播放/接续/间隔（1=忙） */
extern void Sound_Tick(void);           /* 10ms 定时回调，驱动音效状态机 */

#endif  /* _SOUND_EFFECT_H_ */

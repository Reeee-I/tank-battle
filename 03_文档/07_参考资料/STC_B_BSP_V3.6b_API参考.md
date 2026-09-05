# STC-B学习板 BSP Ver3.6b — API 开发参考手册

> 依据：《STC_B学习板BSP_Ver3.6b说明_20250325.docx》（湖南大学 徐成，2025-03-25）
> MCU：STC15F2K60S2。**所有后续开发必须以此文档为准。**

---

## 0. 总体说明（STCBSP 架构）

### 0.1 系统时钟
- 系统工作时钟频率在 `main.c` 中通过 `code long SysClock=11059200;` 定义（单位 Hz）。
- 例：`SysClock=11059200` 表示 11.0592MHz。
- **系统工作频率必须与实际下载时选择的频率一致**，否则所有与定时相关的功能都会出错。

### 0.2 使用方法
1. 工程中加载 `main.c` 和 `STC_BSP.lib` 库文件。
2. `main.c` 中包含头文件：
   - **必须**：`#include "STC15F2K60S2.H"`、`#include "sys.H"`
   - **可选**（用到哪个模块就包含哪个）：
     `display.H`、`key.H`、`hall.H`、`Vib.h`、`beep.H`、`music.h`、`adc.h`、`uart1.h`、`uart2.h`、`IR.h`、`stepmotor.h`、`DS1302.h`、`M24C02.h`、`FM_Radio.h`、`EXT.h`
3. `MySTC_Init()` 为 sys 初始化函数，**必须执行一次**；`MySTC_OS()` 为调度函数，**必须置于 `while(1)` 主循环中**。
4. 每个被选用的可选模块，使用其函数前必须调用一次对应驱动/初始化函数（见各模块）。
5. 事件用 **回调函数** 响应：`SetEventCallBack(事件, 回调函数)`。
6. sys 基本调度时间为 1mS，**非抢占式**：用户程序单次循环累计执行时间必须 < 1mS。

### 0.3 事件列表（enum event，sys.H 中定义，顺序固定）
| 事件 | 含义 |
|---|---|
| `enumEventSys1mS` | 1 毫秒时间间隔到 |
| `enumEventSys10mS` | 10 毫秒时间间隔到 |
| `enumEventSys100mS` | 100 毫秒时间间隔到 |
| `enumEventSys1S` | 1 秒时间间隔到 |
| `enumEventKey` | 按键事件（K1、K2、K3 按下/抬起） |
| `enumEventHall` | 霍尔传感器事件（磁场接近/离开） |
| `enumEventVib` | 振动传感器事件 |
| `enumEventNav` | 导航按键事件（5 个方向 + K3 按下/抬起） |
| `enumEventXADC` | 扩展接口 P1.0/P1.1 完成一次 ADC 转换（新数据） |
| `enumEventUart1Rxd` | 串口 1 收到合法数据包（包头匹配、大小一致） |
| `enumEventUart2Rxd` | 串口 2 收到合法数据包 / ModBus 数据包 |
| `enumEventIrRxd` | 红外收到一个数据包 |

事件回调函数由用户编写，用 `SetEventCallBack()` 注册。

---

## 1. sys 模块（sys.H）——必须

```c
typedef struct {                 // 系统性能评估参数，每秒更新一次
  unsigned long MainLoops;       // 每秒主循环次数（应 >1000）
  unsigned char PollingMisses;   // 每秒轮询丢失次数（理想值 0）
} SysPerF;

extern void MySTC_Init();        // sys 初始化函数，必须执行一次
extern void MySTC_OS();          // sys 调度函数，置于 while(1) 中
extern void SetEventCallBack(char event, void *(user_callback));  // 加载事件用户回调
extern SysPerF GetSysPerformance(void);  // 获取系统运行性能评估参数

enum event { enumEventSys1mS, enumEventSys10mS, enumEventSys100mS, enumEventSys1S,
             enumEventKey, enumEventHall, enumEventVib, enumEventNav, enumEventXADC,
             enumEventUart1Rxd, enumEventUart2Rxd, enumEventIrRxd };
```

---

## 2. 显示模块（display.H）——可选

```c
extern void DisplayerInit();                                        // 显示模块加载
extern void SetDisplayerArea(char Begin_of_scan, char Ending_of_Scan); // 设置有效显示区域（数码管 0~7 从左至右）
extern void Seg7Print(char d0,char d1,char d2,char d3,char d4,char d5,char d6,char d7); // 8 个数码管输出（经 decode_table 译码）
extern void LedPrint(char led_val);                                 // 8 个 LED 输出，bit=1 亮
extern void Seg7SetMode(char m0,char m1,char m2,char m3,char m4,char m5,char m6,char m7); // 数码管闪烁控制
extern void LedSetMode(char m0,char m1,char m2,char m3,char m4,char m5,char m6,char m7);  // LED 闪烁控制
```

- **`SetDisplayerArea`**：参数取值 0~7，且 `Ending_of_Scan > Begin_of_scan`；利用动态扫描/人眼视觉可设超范围参数实现亮度调节等特效。
- **`Seg7Print`**：显示译码表 `code char decode_table[]` 定义在 `main.c` 中，用户可修改增减。
- **`Seg7SetMode` / `LedSetMode`**：每个参数控制一位：
  - `=0`：常亮；`=1~9`：不同方式闪烁；`=10~254`：常暗；`=255`：方式不变。
  - m0 控制左起第 1 个，m1 控制左起第 2 个，以此类推。

---

## 3. 按键模块（key.H）——可选

```c
extern void KeyInit();                          // 按键模块加载（V3.6 起由 Key_Init 改名而来）
extern unsigned char GetKeyAct(char Key);       // 获取按键状态（软件消抖后有效事件）
enum KeyName   { enumKey1, enumKey2, enumKey3 };
enum KeyActName{ enumKeyNull, enumKeyPress, enumKeyRelease, enumKeyFail };
```

- `GetKeyAct`：参数 Key 取值 `enumKey1/2/3`；返回 `enumKeyNull`（无动作）、`enumKeyPress`（按下）、`enumKeyRelease`（抬起）、`enumKeyFail`（参数非法）。**查询一次后事件值变为 enumKeyNull（仅一次有效）**。
- 按键事件 `enumEventKey`：任一按键按下/抬起触发，回调由 `SetEventCallBack` 设置。
- **注意**：若启用了 ADC 模块，Key3 的操作由 ADC 模块检测（P1.7 复用），本模块无反应。

---

## 4. 蜂鸣器模块（beep.H）——可选（占用 STC 内部 CCP1）

```c
extern void BeepInit();                          // 蜂鸣器模块驱动
extern char SetBeep(unsigned int Beep_freq, unsigned int Beep_time);  // 控制发声，非阻塞
extern unsigned char GetBeepStatus(void);        // 获取 Beep 状态
enum BeepActName { enumBeepFree=0, enumBeepBusy, enumSetBeepOK, enumSetBeepFail };
```

- `SetBeep(freq, time)`：freq 单位 Hz（<10Hz 不发音）；发声时长 = `10*Beep_time` mS，最长 655350mS。
- 返回值：`enumSetBeepOK` 成功；`enumSetBeepFail` 失败（参数错或蜂鸣器正在发音）。
- `GetBeepStatus`：`enumBeepFree` 空闲 / `enumBeepBusy` 正在发音。

---

## 5. 音乐模块（music.H）——可选（依赖 Beep + Displayer）

```c
extern void MusicPlayerInit();                                  // 驱动 music 模块
extern char PlayTone(unsigned char tone, unsigned char beatsPM,
                     unsigned char scale, unsigned char beats); // 播放单个音阶
extern void SetPlayerMode(unsigned char play_ctrl);             // 播放控制
extern char GetPlayerMode(void);                                // 获取播放状态

enum PlayerMode  { enumModeInvalid=0, enumModePlay, enumModePause, enumModeStop };
enum MusicKeyword{ enumMscNull=0xF0, enumMscDrvSeg7, enumMscDrvLed, enumMscDrvSeg7andLed,
                   enumMscSetBeatsPM, enumMscSetTone, enumMscRepeatBegin, enumMscRepeatEnd };
```

（说明章节还提到 `SetMusic(unsigned char beatsPM, unsigned char tone, unsigned char *pt, unsigned int datasize, unsigned char display)`，用于设定音乐与播放参数；*pt=待播放编码首地址，datasize=编码长度，二者之一为 enumModeInvalid 则不改变；display 取 enumMscNull / enumMscDrvSeg7 / enumMscDrvLed / enumMscDrvSeg7andLed。）

### PlayTone 参数
- `tone`：音调，有效值 `0xFA/0xFB/0xFC/0xFD/0xFE/0xFF/0xF9` 分别对应 **A/B/C/D/E/F/G** 调。
- `beatsPM`：节拍率，10~255 拍/分钟。
- `scale`：音高编码。`0x00` 休止符；高 4 位：1=低 8 度音、2=中 8 度音、3=高 8 度音；低 3 位：1~7 对应简谱音。如 `0x13` 表示低音 3（mi）。
- `beats`：音长，单位 1/16 拍。16(0x10)=1 拍，32(0x20)=2 拍，8(0x08)=半拍。
- 返回值：`enumBeepOK` 成功 / `enumBeepBusy` 忙 / `enumBeepFail` 参数错（见 Beep.h 的 BeepActName）。

### 音乐编码规则
1. 常规发音编码**成对出现**：`(音高1字节, 节拍数1字节), (音高, 节拍), ...`，中间不可插入其它编码/控制字。
   - 音高：`0x11~0x17` 低音 do~si；`0x21~0x27` 中音；`0x31~0x37` 高音。
   - 节拍：`0x01~0xFF` 单位 1/16 拍；高 4 位整拍数，低 4 位分拍数。如 0x20=2 拍、0x08=半拍、0x18=1 拍半。
2. 控制字（可插入编码中，前 6 个也可用函数设定）：
   - `enumMscNull` / `enumMscDrvSeg7` / `enumMscDrvLed` / `enumMscDrvSeg7andLed`：显示方式
   - `enumMscSetBeatsPM` + 节拍率(1 字节)：设置节拍率
   - `enumMscSetTone` + 音调(1 字节：0xFA~0xFF、0xF9)：设置音调
   - `enumMscRepeatBegin` / `enumMscRepeatEnd`：重复播放（重复一次，不支持嵌套）

### SetPlayerMode / GetPlayerMode
- `enumModePlay` 播放 / `enumModePause` 暂停（可续放）/ `enumModeStop` 停止。
- 所有操作在当前"音"播放完成后生效。

---

## 6. 霍尔传感器模块（hall.H）——可选

```c
extern void HallInit(void);              // 模块初始化
extern unsigned char GetHallAct(void);   // 获取 hall 事件
enum HallActName { enumHallNull, enumHallGetClose, enumHallGetAway };
```

- `GetHallAct` 返回值：`enumHallNull` 无变化 / `enumHallGetClose` 磁场接近 / `enumHallGetAway` 磁场离开。**查询一次后事件值变回 enumHallNull（仅一次有效）**。
- 事件 `enumEventHall`：磁场接近/离开时产生。

---

## 7. 振动传感器模块（Vib.h）——可选

```c
extern void VibInit();
extern unsigned char GetVibAct(void) reentrant;
enum VibActName { enumVibNull, enumVibQuake };
```

- `GetVibAct`：`enumVibNull` 无 / `enumVibQuake` 发生过振动。查询一次后变回 enumVibNull。
- 事件 `enumEventVib`：检测到振动时产生。

---

## 8. 模数转换 ADC 模块（adc.h）——可选（温度 Rt、光照 Rop、导航按键 Nav、EXT 上 ADC）

```c
typedef struct {           // ADC 转换结果（10bit，值为 VCC/1024 伏）
  unsigned int EXT_P10;    // 扩展接口 EXT 上 P1.0 脚 ADC
  unsigned int EXT_P11;    // 扩展接口 EXT 上 P1.1 脚 ADC
  unsigned int Rt;         // 热敏电阻 ADC
  unsigned int Rop;        // 光敏电阻 ADC
  unsigned int Nav;        // 导航按键 ADC
} struct_ADC;

extern void AdcInit(char ADCmodel);
enum ADCmodel_name { enumAdcincEXT=0x9B,   // ADC 模式：包含扩展接口（EXT 上 P1.0/P1.1 不可作数字 IO）
                     enumAdcexpEXT=0x98 }; // 不包含扩展接口（P1.0/P1.1 可作数字 IO）
extern struct_ADC GetADC();
extern unsigned char GetAdcNavAct(char Nav_button);  // 获取导航按键（含 K3）消抖后状态
enum KN_name { enumAdcNavKey3=0, enumAdcNavKeyRight, enumAdcNavKeyDown,
               enumAdcNavKeyCenter, enumAdcNavKeyLeft, enumAdcNavKeyUp };
```

- `GetAdcNavAct` 返回值同 Key 模块：`enumKeyNull` / `enumKeyPress` / `enumKeyRelease` / `enumKeyFail`。**查询一次后变回 enumKeyNull**。
- 事件：
  - `enumEventNav`：导航按键 5 方向或 K3 有按下/抬起动作时产生；软件消抖，最快支持每秒 12 次操作。
  - `enumEventXADC`：P1.0/P1.1 有新 ADC 结果（每 3mS 一次，即每秒 333 次转换）。
- 补充：
  - Rt/Rop 转换速度 9mS（每秒 111 次），无事件，用 `GetADC()` 随时查询。
  - 导航按键与 K3 共用 P1.7，启用 ADC 后 P1.7 IO 功能失效，K3 只能用 `GetAdcNavAct(enumAdcNavKey3)` 获取。
  - Rt：10K/3950 NTC 热敏电阻；Rop：GL5516 光敏电阻。

---

## 9. 串口 1 模块（uart1.h）——可选（固定在 USB 口，与计算机通信）

```c
extern void Uart1Init(unsigned long band);    // 初始化，参数：波特率 bps（固定 8 数据位/1 停止位/无校验）
extern void SetUart1Rxd(void *RxdPt, unsigned int Nmax,
                        void *matchhead, unsigned int matchheadsize);
extern char Uart1Print(void *pt, unsigned int num);   // 发送数据包，非阻塞（约 1uS 返回）
extern char GetUart1TxStatus(void);                  // 获取发送状态
enum Uart1ActName { enumUart1TxFree=0, enumUart1TxBusy, enumUart1TxOK, enumUart1TxFailure };
```

- `SetUart1Rxd(RxdPt, Nmax, matchhead, matchheadsize)`：设置接收数据包存放区、大小、包头匹配字符及个数。
  - `Nmax`：数据包大小（字节），最大 65535；**收到数据超过 Nmax 后多余字节被丢弃**。
  - `Nmax=1`：单字节接收，收到 1 字节即产生事件（若定义匹配需满足匹配条件）。
  - `0 < matchheadsize < Nmax`：接收数据中连续 matchheadsize 个字节与 matchhead 完全匹配，且收到 Nmax 字节时才产生事件。
  - `matchheadsize == Nmax`：数据包完全匹配。
  - `matchheadsize=0 或 > Nmax`：不做匹配，收到任意 Nmax 字节即产生事件。
  - **事件发出后，用户回调函数返回才接收下一个数据包**。
- `Uart1Print(pt, num)`：返回值 `enumTxOK`（请求被 sys 接受）/ `enumTxFailure`（串口忙，上一包未发完）。发送 1 字节约需 0.1~10mS（视波特率）。
- 事件 `enumEventUart1Rxd`：收到包头匹配、大小一致的数据包。
- 补充：串口上**相邻两个数据包时间间隔要求 ≥ 1mS**（系统内部调度限制）；串口 1、串口 2 波特率独立可设，互不影响；串口 1、串口 2、红外可同时工作。

---

## 10. 串口 2 模块（uart2.h）——可选（485 接口 / EXT 扩展接口）

```c
extern void Uart2Init(unsigned long band, unsigned char Uart2mode);  // 初始化：波特率 + 位置
enum Uart2PortName { Uart2UsedforEXT,        // 串口 2 在 EXT 扩展插座上（TTL 标准串口）
                     Uart2Usedfor485,        // 串口 2 用于 485 通信（半双工，发送时不能接收）
                     Uart2Usedfor485ModBus };// 串口 2 用于 485 上 ModBus 协议收发
extern void SetUart2Rxd(void *RxdPt, unsigned int Nmax,
                        void *matchhead, unsigned int matchheadsize); // 参数含义同串口 1
extern char Uart2Print(void *pt, unsigned int num);   // 发送数据包，非阻塞
extern char GetUart2TxStatus(void);
enum Uart2ActName { enumUart2TxFree=0, enumUart2TxBusy, enumUart2TxOK, enumUart2TxFailure };
```

- 固定 8 数据位 / 1 停止位 / 无校验。
- 接收事件 `enumEventUart2Rxd`：
  - `Uart2UsedforEXT` / `Uart2Usedfor485`：同串口 1（包头匹配、大小一致）。
  - `Uart2Usedfor485ModBus`：收到一个 ModBus 数据帧（帧内字节间隔 < 4 字节收发时间，且包头与设定匹配）。注意：
    1. 帧内**未做 CRC 校验**，建议用户在回调函数中自行 CRC 校验；
    2. **不返回有效字节数**，用户需从指令类型（第 2 字节）及帧内数据（一般第 5、6 字节）判断帧长。

---

## 11. 红外模块（IR.h）——可选（38KHz，支持 PWM/PPM 协议）

```c
extern void IrInit(unsigned char Protocol);   // IR 模块初始化
enum IrProtocalName { NEC_R05d=43 };          // 红外协议：基本时间片 = 43*13 = 560uS
extern char IrTxdSet(unsigned char *pt, unsigned char num);   // 自由编码方式发送（任意协议）
extern char IrPrint(void *pt, unsigned char num);             // NEC PWM 方式发送数据包
extern void SetIrRxd(void *RxdPt, unsigned char RxdNmax);     // 设置红外接收缓冲区与最大字节数
extern unsigned char GetIrRxNum(void);                        // 获取红外接收数据包大小（字节）
enum IrActName { enumIrTxFree=0, enumIrTxBusy, enumIrTxOK, enumIrTxFailure };
```

- `IrTxdSet(pt, num)`：自由编码。数据格式为成对的（码 n 发送时长, 码 n 停止时长）……；每个时长单位 = 协议基本时间片个数（最大 255）。参照该格式可实现任何 38KHz 电器遥控器。
- `IrPrint(pt, num)`：NEC PWM 编码发送（数据包不含引导码/结束码，仅有效数据）。发送格式 a+b+c：
  - a 引导码：发 16×基本时间片、停 8×基本时间片（0.56mS 时即 9mS 发、4.5mS 停）；
  - b 数据："0" = 发 1、停 1；"1" = 发 1、停 3（×基本时间片），**先发高位后发低位**；
  - c 结束码：发 1、停 1。
  - 每字节约需 10mS 量级时间；非阻塞，约 1uS 返回。
- `SetIrRxd(RxdPt, RxdNmax)`：设置接收缓冲区与每个数据包最大字节数，**超出部分忽略**；收到至少 1 字节的数据包产生 `enumEventIrRxd`。
- `GetIrRxNum()`：事件产生后返回本次红外数据包大小（字节数）；其它时间访问值不确定。
- 说明章节还提到 `char GetIrStatus(void)`：返回 `enumIrFree`（空闲）/ `enumIrBusy`（正忙）。
- 红外速率固定（约 500~800bps），无包头匹配；单工：不发送时自动进入接收，正在接收时不会进入发送。
- 与串口 1、串口 2 可同时工作互不影响。

---

## 12. 步进电机模块（stepmotor.h）——可选

```c
extern void StepMotorInit();                              // 步进电机模块初始化
extern char SetStepMotor(char StepMotor, unsigned char speed, int steps);
extern int EmStop(char StepMotor);                        // 紧急停止，返回剩余未转完步数
extern unsigned char GetStepMotorStatus(char StepMotor);  // 获取状态
enum StepMotorName    { enumStepMotor1=0, enumStepMotor2, enumStepMotor3 };
enum StepMotorActName { enumStepMotorFree, enumStepMotorBusy, enumSetStepMotorOK, enumSetStepMotorFail };
```

- `SetStepMotor(电机, speed, steps)`：
  - 电机：`enumStepMotor1` = SM 接口上的真实步进电机；`enumStepMotor2` = 用 L0~L3 四个 LED 模拟 4 相电机；`enumStepMotor3` = 用 L4~L7 模拟。
  - `speed`：0~255，单位 步/S（实际每步时间 = int(1000/speed) mS，与设定值有误差）。
  - `steps`：-32768~32767，负值反转。
  - 返回 `enumSetStepMotorOK` / `enumSetStepMotorFail`（电机名非法、speed=0、或正在转动）。
- `EmStop`：参数不对返回 0。
- `GetStepMotorStatus`：`enumStepMotorFree` / `enumStepMotorBusy` / `enumSetStepMotorFail`。
- **V3.6b 新增**：`StepLedPrint` 函数，用于控制步进电机 4 相（4 个指示灯）开关。

---

## 13. 实时时钟模块（DS1302.h）——可选

```c
typedef struct {            // 均为 BCD 码
  unsigned char second;     // 秒
  unsigned char minute;     // 分
  unsigned char hour;       // 时
  unsigned char day;        // 日
  unsigned char month;      // 月
  unsigned char week;       // 星期
  unsigned char year;       // 年
} struct_DS1302_RTC;

extern void DS1302Init(struct_DS1302_RTC time);   // 驱动/初始化；若检测到掉电则按 time 初始化 RTC
extern struct_DS1302_RTC RTC_Read(void);          // 读 RTC
extern void RTC_Write(struct_DS1302_RTC time);    // 写 RTC（校时）
extern unsigned char NVM_Read(unsigned char NVM_addr);   // 读 NVM（地址 0~30）
extern unsigned char NVM_Write(unsigned char NVM_addr, unsigned char NVM_data);
enum DS1302name { enumDS1302_OK, enumDS1302_error };
```

- NVM：31 字节（地址 0~30），**地址 30 被 DS1302Init 用于掉电检测，用户不可用**。
- `NVM_Read` 参数错误返回 `enumDS1302_error`；`NVM_Write` 正常返回 `enumDS1302_OK`，错误返回 `enumDS1302_error`。
- DS1302 NVM 为低功耗 RAM（纽扣电池保持），容量小（31 字节）但无写寿命问题、写周期极短（两次写无需等待）；每字节读写需数十 uS，避免无效/大量/重复操作。
- 例：`struct_DS1302_RTC t={0x30,0,9,0x06,9,1,0x21};` 即 2021-09-06 周一 09:00:30。

---

## 14. 非易失存储器 M24C02（M24C02.h）——可选（IIC，无需初始化）

```c
extern unsigned char M24C02_Read(unsigned char NVM_addr);          // 读，地址 00~0xFF
extern void M24C02_Write(unsigned char NVM_addr, unsigned char NVM_data); // 写
```

- 容量 256 字节（2K bits），断电保持。
- 写周期 5~10mS（**两次写操作之间需间隔 5~10mS 以上**）；每单元写寿命约 10 万次量级。
- 每次读/写约数十 uS；避免无效、大量、重复操作。

---

## 15. FM 收音机模块（FM_Radio.h）——可选

```c
typedef struct {            // FM 收音机控制模型
  unsigned int frequency;   // 收音频率 887~1080（单位 0.1MHz，即 88.7~108.0MHz）
  unsigned char volume;     // 音量 0~15，0 最小
  unsigned char GP1;        // FM 指示灯 1：=0 输出低，GP1 亮；!=0 输出高，GP1 灭
  unsigned char GP2;        // 指示灯 2
  unsigned char GP3;        // 指示灯 3
} struct_FMRadio;

extern void FMRadioInit(struct_FMRadio FMRadio);  // 收音机模块初始化
extern void SetFMRadio(struct_FMRadio FMRadio);   // 设置收音机控制参数
extern struct_FMRadio GetFMRadio(void);           // 获取当前收音机参数
```

- 注意：本版本暂未输出调谐、自动搜索、电台信号等状态信息，暂不能自动搜台。

---

## 16. EXT 扩展接口模块（EXT.h）——可选（电子秤 / PWM / 旋转编码器 / 超声波，4 选 1）

```c
extern void EXTInit(char EXTfunction);   // 扩展接口初始化，决定哪种 API 有效
enum EXTname { enumEXTWeight,    // 电子秤（HX710/HX711）
               enumEXTPWM,       // PWM：控制直流电机方向、快慢
               enumEXTDecode,    // 增量式计数（旋转编码器）
               enumEXTUltraSonic // 超声波测距
             };
extern int GetWeight(void);      // 电子秤 ADC 值：16bit 带符号，未清零未标定（仅返回高 16bit）
extern int GetDecode(void);      // 增量编码器增量值（相对上次读取后的新增量）
extern int GetUltraSonic(void);  // 超声波测距值，每秒 5 次测量，单位 cm
extern void SetPWM(unsigned char PWM1, unsigned char freq1,
                   unsigned char PWM2, unsigned char freq2);
```

- `SetPWM`：`PWMx` 占空比 0~100（%），`freqx` 频率 1~255Hz；实际频率 = `1000/int(1000/freqx)`（即 1000/i = 4,5,6...1000，或 250,200,167,143,125,...,1）。可配合 H 型桥式电路控制直流电机正反转、转速，或灯亮度等。
- 串口 2 在 EXT 上 / 外接蓝牙见 uart2 模块；气敏、数据采集、电子尺等见 ADC 模块。

---

## 17. 推荐工程框架（STC_DemoV3 示例程序要点）

### main.h 要点
```c
#include "STC15F2K60S2.H"   // 必须
#include "sys.H"            // 必须
// ... 其它用到的模块头文件 ...
code unsigned long SysClock=11059200;   // 必须，与实际下载频率一致
#ifdef _displayer_H_  // 选用显示模块时必须：数码管显示译码表（可修改增减）
code char decode_table[]={0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f,
                          0x00,0x08,0x40,0x01,0x41,0x48,
                          0x3f|0x80,0x06|0x80,0x5b|0x80,0x4f|0x80,0x66|0x80,
                          0x6d|0x80,0x7d|0x80,0x07|0x80,0x7f|0x80,0x6f|0x80};
#endif
```
（译码表索引：0~9 数字；10 空；11 "下-"(0x08)；12 "中-"(0x40)；13 "上-"(0x01)；14 "上中-"(0x41)；15 "中下-"(0x48)；16~25 为带小数点的 0~9。）

### main() 流程（顺序固定）
```c
void main() {
  // 1. 加载需要的模块（驱动/初始化函数）
  KeyInit();  DisplayerInit();  BeepInit();  MusicPlayerInit();
  HallInit();  VibInit();  AdcInit(enumAdcexpEXT);
  StepMotorInit();  DS1302Init(t);  IrInit(NEC_R05d);
  // EXT 4 选 1：EXTInit(enumEXTWeight / enumEXTPWM / enumEXTDecode / enumEXTUltraSonic)
  Uart1Init(1200);
  // 串口 2 二选一：Uart2Init(2400,Uart2Usedfor485) 或 Uart2Init(2400,Uart2UsedforEXT)
  // 2. 设置事件回调
  SetEventCallBack(enumEventKey, mykey_callback);
  SetEventCallBack(enumEventSys1mS, my1mS_callback);
  SetEventCallBack(enumEventSys10mS, my10mS_callback);
  SetEventCallBack(enumEventSys100mS, my100mS_callback);
  SetEventCallBack(enumEventSys1S, my1S_callback);
  SetEventCallBack(enumEventHall, myhall_callback);
  SetEventCallBack(enumEventVib, mySV_callback);
  SetEventCallBack(enumEventNav, myKN_callback);
  SetEventCallBack(enumEventUart1Rxd, myUart1Rxd_callback);
  SetEventCallBack(enumEventUart2Rxd, myUart2Rxd_callback);
  SetEventCallBack(enumEventXADC, myADC_callback);
  SetEventCallBack(enumEventIrRxd, myIrRxd_callback);
  // 3. 用户程序状态初始化
  SetDisplayerArea(0,7);
  SetUart1Rxd(&rxd, sizeof(rxd), rxdhead, sizeof(rxdhead));  // rxdhead={0xaa,0x55}
  SetUart2Rxd(&rxd, sizeof(rxd), rxdhead, sizeof(rxdhead));
  SetIrRxd(&rxd, Nmax);   // 注意：现版本有两个参数 (RxdPt, RxdNmax)
  // 4. 用户程序变量初始化（FM、音乐参数、模式等）
  // 5. 系统启动
  MySTC_Init();          // 必须
  while(1) { MySTC_OS(); }  // 必须！【铁律】循环内只允许 MySTC_OS()，不得出现任何其它代码
  // 所有用户业务逻辑均放在各事件回调函数中实现
}
```

### Demo 通信协议示例（AA 55 包头、8 字节数据包）
- 串口 1 收到 `AA 55` 开头 8 字节包 → 第 7 字节 +1 → 串口 2（485/EXT，2400bps）转发。
- 串口 2 收到合法包 → 第 7 字节 +2 → 红外 IrPrint 转发（NEC_R05d）。
- 红外收到包（包头 `AA 55`，第 3 字节）：
  - `F1`：调收音频率（第 4、5 字节 BCD，0.1MHz，887~1080）与音量（第 6 字节，0~15）；
  - `F2`：调 RTC 时分秒（第 4、5、6 字节 BCD）；
  - `F3`：调 RTC 年月日（第 4、5、6 字节 BCD）；
  - 处理完第 7 字节 +4、调整值存入 NVM、蜂鸣器 1000Hz 600mS、向串口 1 转发。
- 按键 1 按下：红外发送"大家好！"；按键 3 抬起：串口 1 发送性能参数（波特率 1200bps）。
- 振动传感器：控制音乐播放/暂停；霍尔传感器：磁场接近且蜂鸣器空闲时 1350Hz 发声 1 秒。
- Demo 7 种功能模式（Key2 切换，LED 显示模式号）：RTC_YMD / RTC_HMS / Rt_Rop（温度光照）/ Music / FMradio / UltroSonic / Weight。

---

## 18. 版本更新要点（V3.6b / V3.6a / V3.6）
- **V3.6b（2025-03-25）**：StepMotor 模块新增 `StepLedPrint`（控制步进电机 4 相/4 个指示灯开关）。
- **V3.6a（2024-10-15）**：修正 uart1/uart2 接收数据帧头匹配一个的 BUG；displayer 新增 `Seg7SetMode`、`LedSetMode`。
- **V3.6（2022-05-02）**：串口 2 增加 485 ModBus 支持；数据包超出最大接收字节时后续字节丢弃；`Key_Init()` 改名 `KeyInit()`。
- **2021-11-08**：`SetIrRxd` 增加 `RxdNmax` 参数；修正 ADC 模块 BUG；更正 uart1/uart2 波特率 115200 的 BUG。

## 19. 常见注意事项（务必遵守）
1. `SysClock` 必须与实际下载频率一致。
2. `MySTC_Init()` 只执行一次；`MySTC_OS()` 必须在 while(1) 中。
3. **【铁律，用户特别强调】`while(1)` 主循环中不允许出现除 `MySTC_OS()` 之外的任何代码！**
   - 用户业务代码一律放入各事件回调函数（1mS/10mS/100mS/1S/Key/Nav/Hall/Vib/XADC/Uart1Rxd/Uart2Rxd/IrRxd）中执行。
   - 主循环的标准形态只能是：
     ```c
     while(1) { MySTC_OS(); }
     ```
   - 严禁在 while(1) 内写轮询、延时、判断、函数调用等任何其它代码。
4. 用户回调函数内程序执行时间（含所有事件回调累计）必须 < 1mS。
4. 串口相邻两个数据包间隔 ≥ 1mS；事件回调返回后才接收下一包。
5. 启用 ADC 后 K3（P1.7）由 ADC 模块接管；EXT P1.0/P1.1 在 AdcInit(enumAdcincEXT) 时不可作数字 IO。
6. M24C02 两次写操作间隔 ≥ 5~10mS；DS1302 地址 30 用户不可用。
7. 查询型 API（GetKeyAct/GetAdcNavAct/GetHallAct/GetVibAct 等）事件仅一次有效，查后复位。
8. 头文件中声明的原型最准确，函数名以下表为准（注意 Beep 是 `SetBeep` 而非 `Set_Beep`；按键是 `KeyInit` 而非 `Key_Init`）。

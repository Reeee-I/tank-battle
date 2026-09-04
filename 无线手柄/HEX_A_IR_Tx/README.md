# HEX-A 工程：红外发送端（玩家2无线手柄）

> 生成文件：`..\..\HEX\Wireless_TX_P2.hex`（统一 HEX 目录，见 `HEX\README.md` 对照表）
> 作用：替代 **原玩家2有线手柄**。采集导航按键与 K1/K2，每 100ms 打包成
> `AA 02 按键状态` 3 字节数据包，经 **红外（IR，NEC_R05d）** 发出。
> 数据包格式与原有线协议完全一致，PC 端无需任何修改。

---

## 1. 目录内容（本工程自包含）

| 文件 | 说明 |
|---|---|
| `main.c` | 唯一源文件（完整中文注释，C89，无寄存器直接操作，仅用 BSP API） |
| `HEX_A.uvproj` | Keil 工程（Target: HEX_A_IR_Tx，Output → `..\..\HEX\Wireless_TX_P2.hex`） |
| `STC_BSP.lib` | BSP 库副本（V3.6b，与 `MCU/STC_BSP.lib` 一致） |
| `inc/` | BSP 头文件副本：`STC15F2K60S2.H` `sys.H` `displayer.h` `Key.H` `adc.h` `IR.h` |

> 编译后 HEX 在 `A大项目\HEX\Wireless_TX_P2.hex`（不在本目录内）。

## 2. 程序流程

```
main(): DisplayerInit → 身份显示(L7亮+数码管"A") → KeyInit → AdcInit(ADCexpEXT)
        → IrInit(NEC_R05d) → 注册 enumEventSys100mS 回调 → MySTC_Init → while(MySTC_OS)
my100mS_callback(每100ms):
        ① 轮询导航四方向：Press 置位 / Release 清位 → navHold
        ② K1 按下瞬间 → firePending=1；K2 按下瞬间 → restartPending=1
        ③ 组包：AA, 02, navHold|K1位|K2位
        ④ IrPrint(txBuf,3) 红外发送；发送请求被接受才清除单发标志
```

- 方向键"按住持续上报"、K1 开火与 K2 重开请求"按下瞬间单发"，
  与原有线玩家2手柄逻辑**完全一致**；
- 不按键时每 100ms 也发一包（状态=0），作为 PC 的在线心跳；
- 红外发送为 **非阻塞**（约 1µs 返回），模块实际发送约需 30ms/包，
  远小于 100ms 周期，故不会堆积。

## 3. 数码管身份显示（区分四块板）

| 显示 | 含义 |
|---|---|
| **A** | 本板 = 无线发送端（HEX-A，红外发射，玩家2无线手柄） |
| 1 / 2 | 有线玩家1 / 玩家2 手柄板（注意：无线发送端**故意不用"2"**，避免与有线玩家2混淆） |
| b | 无线接收端（HEX-B） |

- 'A' 段码追加在 `decode_table[]` 索引 26（段码 0x77），属自定义译码表用法；
- 上电自检：**L7 常亮**（表示玩家2 通道）+ 数码管最左位显示 **A**。

## 4. 硬件连接（HEX-A）

- 本板 **板载红外发射管 IR_TXD** 对准 HEX-B 接收板的 **IR_RXD**；
- 本板供电：任意 USB 口 5V 即可（**无需**连接电脑进行数据通信）。

## 5. 编译（Keil）

方式 A（推荐，直接打开本工程）：
1. 双击打开 `HEX_A.uvproj`（Keil 中需已安装 STC 设备库，STC-ISP →
   "Keil仿真设置" 安装过即可）；
2. 按 **F7** 编译；
3. 产物：`A大项目\HEX\Wireless_TX_P2.hex`。

方式 B（手动核对配置清单）：
- 芯片：**STC15F2K60S2 Series**（STC 设备库）；
- 内存模式 Memory Model = **Small**；优化 Optimize = **Level 8**；
- C51 → Include Paths = `.\inc`；Output 勾选 **Create HEX File**；
- Output Directory = `..\..\HEX\`，Output Name = `Wireless_TX_P2`；
- 工程文件：`main.c` + `STC_BSP.lib`（Add Existing Files 时类型选 *）；
- C51 Define：`WIRELESS_TX`（仅用于区分工程、防止共享输出目录时误用旧 obj）。

## 6. 烧录（STC-ISP）

1. 单片机型号选 **STC15F2K60S2**；
2. 频率选 **11.0592MHz**（外部晶振，与代码 `SysClock` 一致）；
3. 载入 `HEX\Wireless_TX_P2.hex` → 下载/编程（必要时按提示重新上电）；
4. 烧完 **关闭 STC-ISP**（释放 COM 口给游戏）。

## 7. 功能核对清单

| 项 | 期望 |
|---|---|
| 上电 | L7 亮，数码管最左位显示 A |
| 导航键 | 按住对应键，HEX-B/L0 闪、PC 玩家2 坦克移动/转向 |
| K1 | 按下瞬间开火一次（按住不连发） |
| K2 | 对局结束后按下 → PC 重开一局 |
| 心跳 | 不按键也每 100ms 发一包，PC 判定在线 |
| 断链 | HEX-A 关机/遮挡 → PC 约 0.6s 后显示玩家2 断开 |

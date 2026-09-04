# HEX-B 工程：红外接收端 + 串口1转发

> 生成文件：`..\..\HEX\Wireless_RX.hex`（统一 HEX 目录，见 `HEX\README.md` 对照表）
> 作用：接收 HEX-A 红外发送端发来的 `AA 02 xx` 3 字节数据包，
> **原样**通过 **串口1（板载 USB 口）9600bps 8N1** 转发给 PC。
> 收不到合法红外包时不发送任何数据。

---

## 1. 目录内容（本工程自包含）

| 文件 | 说明 |
|---|---|
| `main.c` | 唯一源文件（完整中文注释，C89，无寄存器直接操作，仅用 BSP API） |
| `HEX_B.uvproj` | Keil 工程（Target: HEX_B_IR_Rx，Output → `..\..\HEX\Wireless_RX.hex`） |
| `STC_BSP.lib` | BSP 库副本（V3.6b，与 `MCU/STC_BSP.lib` 一致） |
| `inc/` | BSP 头文件副本：`STC15F2K60S2.H` `sys.H` `displayer.h` `IR.h` `uart1.h` |

> 编译后 HEX 在 `A大项目\HEX\Wireless_RX.hex`（不在本目录内）。

## 2. 程序流程

```
main(): DisplayerInit → SetDisplayerArea(0,7) → 身份显示(数码管"b")
        → IrInit(NEC_R05d) → Uart1Init(9600) → SetIrRxd(irRxBuf, 10)
        → 注册 enumEventIrRxd 回调 → MySTC_Init → while(MySTC_OS)

myIrRxd_callback(收到一个红外数据包时):
        rxNum = GetIrRxNum()                     // 取实际字节数
        若 rxNum==3 且 buf[0]==0xAA 且 buf[1]==0x02:
            若 GetUart1TxStatus()==enumUart1TxFree:
                Uart1Print(irRxBuf,3)            // 原样转发给 PC
                （成功则 L0 闪一下，作调试指示）
        其它情况（长度不符/包头或玩家号不符）：直接丢弃
```

- 红外接收缓冲区：`irRxBuf[10]`（每包最大 10 字节，由 SetIrRxd 设定）；
- 只有 **长度=3、包头 0xAA、玩家号 0x02** 的包才转发，普通家电遥控器
  （4 字节 NEC 帧等）会被自动过滤；
- **长时间收不到红外信号 → 不发送任何数据**，PC 端 0.6s 心跳超时后
  判定玩家2 断开并冻结输入（与现有有线断线逻辑一致）。

## 3. 数码管身份显示（区分四块板）

| 显示 | 含义 |
|---|---|
| **b** | 本板 = 无线接收端（HEX-B，红外接收 + USB 转发） |
| 1 / 2 | 有线玩家1 / 玩家2 手柄板 |
| A | 无线发送端（HEX-A） |

- 'b' 段码追加在 `decode_table[]` 索引 27（段码 0x7C），属自定义译码表用法；
- 上电自检：数码管最左位显示 **b**；每成功转发一包 **L0 闪一下**。

## 4. 硬件连接（HEX-B）

- 本板 **板载红外接收管 IR_RXD** 对准 HEX-A 发射板的 **IR_TXD**；
- 本板用 **板载 USB 线（串口1 / CH340）连接电脑** —— 这就是 PC 识别
  为"玩家2"的那个 COM 口。

## 5. 编译（Keil）

方式 A（推荐，直接打开本工程）：
1. 双击打开 `HEX_B.uvproj`；
2. 按 **F7** 编译；
3. 产物：`A大项目\HEX\Wireless_RX.hex`。

方式 B（手动核对配置清单）：
- 芯片：**STC15F2K60S2 Series**（STC 设备库）；
- 内存模式 Memory Model = **Small**；优化 Optimize = **Level 8**；
- C51 → Include Paths = `.\inc`；Output 勾选 **Create HEX File**；
- Output Directory = `..\..\HEX\`，Output Name = `Wireless_RX`；
- 工程文件：`main.c` + `STC_BSP.lib`（Add Existing Files 时类型选 *）；
- C51 Define：`WIRELESS_RX`（仅用于区分工程、防止共享输出目录时误用旧 obj）。

## 6. 烧录（STC-ISP）

1. 单片机型号选 **STC15F2K60S2**；
2. 频率选 **11.0592MHz**（外部晶振，与代码 `SysClock` 一致）；
3. 载入 `HEX\Wireless_RX.hex` → 下载/编程（必要时按提示重新上电）；
4. 烧完 **关闭 STC-ISP**（否则 COM 口被占用，游戏打不开）。

## 7. 功能核对清单

| 项 | 期望 |
|---|---|
| 上电 | 数码管最左位显示 b（无包时 LED 全灭、不发送） |
| 收包转发 | HEX-A 发射 → L0 闪一下，PC 收到玩家2 数据 |
| 校验过滤 | 长度≠3 / 包头≠AA / 玩家号≠02 的包一律不转发 |
| 断链 | HEX-A 关机/遮挡 → L0 停闪、不发送，PC 约 0.6s 后显示玩家2 断开 |

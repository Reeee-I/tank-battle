# 双人坦克对战（STC-B 学习板手柄 + PC Pygame）

> 手柄板（**STC-B 学习板，STC15F2K60S2**）每 100ms 采集按键并打包上报，
> **PC 端 Python + Pygame** 接收后驱动双人同屏坦克对战（移动 / 转向 / 开火 /
> 碰撞 / 道具 / 胜负结算），并下行 `AA D1/D2 HP` 帧驱动手柄 **LED 血量条**。

板端支持三套连接方案，PC 端协议完全通用（自动按数据包内容绑定玩家）：

| 方案 | 板端固件目录 | HEX（在 `HEX\`） | 说明 |
|---|---|---|---|
| **① RS485 三板手柄（主推）** | `01_下位机程序/02_RS485模式/` | `485_Player1.hex` / `485_Player2.hex` / `485_Relay.hex` | 两块手柄走 485 总线，第三块中转板 USB 上报 PC（单 COM 双玩家） |
| ② 有线 USB 直连（可选） | `01_下位机程序/01_有线模式/` | `USB_Player1.hex` / `USB_Player2.hex` | 两块手柄各自 USB 直连 PC（两个 COM） |
| ③ 红外无线（可选） | `01_下位机程序/03_红外模式/` | `IR_Player2.hex`（发射端）/ `IR_Relay.hex`（接收转发） | 玩家2 无线手柄（红外发射）+ 接收转发板 |

---

## 一、目录结构（重组后）

```
A大项目/
├── 01_下位机程序/                 # ★ 所有单片机（STC15）端程序
│   ├── 01_有线模式/                # ① 有线 USB 直连手柄（旧方案，仍可选）
│   │   ├── main.c                 #    唯一源文件（宏 PLAYER_ID 区分玩家1/2）
│   │   ├── TankBattle.uvproj      #    双 Target 工程（Player1/Player2 一次 Batch Build）
│   │   ├── TankBattle_P1.uvproj   #    便捷工程：只编 USB_Player1.hex
│   │   └── TankBattle_P2.uvproj   #    便捷工程：只编 USB_Player2.hex
│   ├── 02_RS485模式/               # ② RS485 三板手柄方案（主推）
│   │   ├── main_handle.c          #    两块手柄共用源（工程 Define 区分 PLAYER_ID=1/2）
│   │   ├── RS485_Handle1.uvproj   #    手柄1 → 485_Player1.hex
│   │   ├── RS485_Handle2.uvproj   #    手柄2 → 485_Player2.hex
│   │   ├── main_hub.c             #    中转板源（485 轮询主机 + USB 转发）
│   │   ├── RS485_Hub.uvproj       #    中转板 → 485_Relay.hex
│   │   └── README.md              #    485 接线 / 轮询协议 / 烧录说明
│   ├── 03_红外模式/                # ③ 红外无线手柄
│   │   ├── 01_发射端/              #    无线发送端 HEX-A（玩家2手柄，数码管 'A'）
│   │   │   ├── main.c
│   │   │   └── HEX_A.uvproj       #    → IR_Player2.hex
│   │   ├── 02_接收端/              #    红外接收 + 串口转发 HEX-B（数码管 'b'）
│   │   │   ├── main.c
│   │   │   └── HEX_B.uvproj       #    → IR_Relay.hex
│   │   └── README.md              #    红外模块总览 / 联调说明
│   ├── 04_音效模块/                # 蜂鸣器音效模块（唯一权威副本，各工程共享引用）
│   │   ├── sound_effect.h/.c      #    音效模块（宏 SOUND_ENABLED=0 即空操作）
│   │   ├── README.md              #    交付物对照 / 快速集成
│   │   └── 音效测试与集成说明.md
│   └── common/                    # ★ 下位机共用资源（唯一权威副本，勿在工程内再复制）
│       ├── inc/                   #    BSP 与板级头文件（17 个，各工程 Include 路径指向这里）
│       ├── STC_BSP.lib            #    BSP 库（各工程共享引用）
│       └── (说明见本 README 第三节)
│
├── 02_上位机程序/                 # ★ PC 端游戏程序
│   ├── main.py                    #     入口（串口自动绑定 / 键盘调试 / 断线重连）
│   ├── game.py                    #     Game 类：主循环 / 碰撞 / 道具 / 渲染
│   ├── tank.py / bullet.py / obstacle.py / powerup.py
│   ├── serial_handler.py          #     串口接收线程 / 自动绑定 / 下行血量帧
│   ├── requirements.txt           #     pygame + pyserial
│   ├── README.md                  #     PC 端运行与自测说明
│   ├── tests/                     #     逻辑 / 地图 / 串口 e2e / 验收预演 / 画面 QA
│   ├── tools/serial_probe.py      #     串口裸监听调试工具
│   └── 素材/                      #     UI 重设计素材（原 picture/，尚未被代码引用）
│
├── 03_文档/                       # ★ 全部说明文档（见下节"文档索引"）
│   ├── 01_项目简介/               ├── 02_硬件连接/        ├── 03_通信协议/
│   ├── 04_项目计划/               ├── 05_开发日志/        ├── 06_用户手册/
│   ├── 07_参考资料/               └── 08_整理记录/（整理说明.md 等）
│
├── HEX/                           # ★ 统一 HEX 输出目录 —— 重组时保持原样（未改动）
│   ├── USB_Player1.hex / USB_Player2.hex / 485_Player1.hex / 485_Player2.hex
│   ├── 485_Relay.hex / IR_Player2.hex / IR_Relay.hex
│   └── README.md                  # HEX 命名 / 用途对照表（原样保留）
│
├── .gitignore
└── README.md                      ← 本文件
```

> ⚠️ 各 Keil 工程的 **Output 目录**已统一指向根目录 `HEX\`（保持原约定），编译后直接到
> `HEX\` 取对应 `.hex` 烧录。

---

## 二、各文件夹 / 主要文件用途说明

### 01_下位机程序 —— 单片机端
- 按**通信方案**分子目录（01_有线 / 02_RS485 / 03_红外），每方案内含各自 `main*.c`
  与其 Keil 工程（`.uvproj` 跟随源文件）；`list\` 为 Keil 中间产物（已 gitignore）。
- **04_音效模块**：蜂鸣器音效（K1"哒"、方向"嗒嗒"、被命中"呜"、结束下扫音）。
  仅"玩家手边"的板挂载 `sound_effect.c`；接收端 / 中转板不发声。
- **common/**：三套方案**共享**的 BSP 头文件（`inc\`）与库（`STC_BSP.lib`）。
  所有工程都以相对路径引用这里（`..\common\...`），**不要再复制到各工程内**。
- 各方案关系：玩家身份与数据包内容一致（数码管最左位显示 1/2/C/A/b），
  换接法只换板端固件，PC 端零改动。

### 02_上位机程序 —— PC 端
- 模块划分：`main.py`（入口）→ `serial_handler.py`（串口链路，独立线程）→
  `game.py`（游戏世界与渲染）→ `tank/bullet/obstacle/powerup`（实体类）。
- `tests/`：无需硬件的自动化回归（用法见 `03_文档/06_用户手册/使用说明.md`）。
- `素材/`：UI 重设计参考素材（原 `picture/`，尚未被代码引用，仅供后续开发）。

### 03_文档 —— 文档中心（详细索引见下节）

### HEX —— 不整理目录
- 本项目所有 HEX 的唯一输出与发布目录，重组时**未移动 / 未修改 / 未删除**任何内容；
  文件与板子的对照表见 `HEX/README.md`（原样保留）。

---

## 三、如何快速找到某个功能对应的代码

| 想找的功能 | 去哪里找 |
|---|---|
| 按键采集 / 移动转向 / K1 开火 / K2 重开 / K3 开始 | 各方案 `main*.c` 顶部宏区与 100ms 回调（`01_有线模式\main.c`、`02_RS485模式\main_handle.c`、`03_红外模式\01_发射端\main.c`） |
| 板↔PC 3 字节协议（0xAA + 玩家号 + 按键掩码） | `03_文档/03_通信协议/通信协议说明.md`（实现见 `serial_handler.py` 与各 `main*.c`） |
| PC → 板 下行血量帧 `AA D1/D2 HP`（LED 血量条） | 下发侧 `serial_handler.py` / `game.py`；接收侧 `01_有线模式\main.c`、`02_RS485模式\main_handle.c`、中转转发 `main_hub.c` |
| 485 点名轮询时序 / 空闲窗口转发 | `02_RS485模式\main_hub.c`（常量集中在文件顶部） |
| 红外 NEC 收发（IR_TXD / IR_RXD） | `03_红外模式\01_发射端\main.c`、`03_红外模式\02_接收端\main.c`；接口头文件 `common\inc\IR.h` |
| 蜂鸣器音效（启用 / 关闭 / 音量 / 播放点） | `04_音效模块\sound_effect.h/.c`（宏 `SOUND_ENABLED`、`SOUND_VOLUME`） |
| BSP 初始化 / 显示 / 串口 / ADC / LED | `common\inc\`（sys.H、displayer.h、uart1.h、uart2.h、adc.h、Key.H、Beep.h …）与 `common\STC_BSP.lib` |
| 游戏规则数值 / 道具平衡 / 地图设计 | `02_上位机程序\game.py`（常量集中在对应类顶部） |
| 串口自动绑定 / 断线重连 / 心跳 | `02_上位机程序\serial_handler.py` |
| PC 端自测与验收预演 | `02_上位机程序\tests\`（用法见 `06_用户手册\使用说明.md`） |
| HEX 命名 ↔ 板子角色 | `HEX\README.md`（原样） |

**Keil 工程（`.uvproj`）已统一**：Include 路径 = `..\common\inc;..\04_音效模块`
（红外子目录为 `..\..\` 两层），库文件 = `common\STC_BSP.lib`，音效模块 =
`04_音效模块\sound_effect.c`，Output = `..\..\HEX\`（红外为 `..\..\..\HEX\`）。
若新建工程请照此相对路径配置，保持"共享资源只在 common/ 音效模块放一份"的约定。

---

## 四、文档索引（03_文档）

| 想查什么 | 文档 |
|---|---|
| 项目总览（历史完整版存档） | `03_文档/01_项目简介/项目介绍_历史完整版.md`；精简版见 `01_项目简介/项目简介.md` |
| 三套接法怎么接线 | `03_文档/02_硬件连接/硬件连接说明.md` |
| 协议定义（上行按键包 / 下行血量帧 / 485 点名帧） | `03_文档/03_通信协议/通信协议说明.md` |
| 开发计划 / UI 重设计计划 / 验收复测清单 | `03_文档/04_项目计划/` |
| 版本变更与真机验证记录 | `03_文档/05_开发日志/开发日志.md` |
| PC 运行 / 编译烧录 / 操作与 FAQ | `03_文档/06_用户手册/使用说明.md` |
| STC-B BSP（V3.6b）参考资料 | `03_文档/07_参考资料/` |
| 本次目录重组：新旧对照 / 移动与合并清单 | `03_文档/08_整理记录/整理说明.md` |

---

## 五、快速开始

```bat
:: 1) PC 端（Windows 10/11，Python 3.8+）
cd 02_上位机程序
pip install -r requirements.txt
python main.py                  :: 自动扫描串口；--p1/--p2 可手动指定

:: 2) 编译板端固件（Keil uVision4 + C51）
::    打开对应方案目录下的 .uvproj → F7（Output 已指向 ..\..\HEX\ 或 ..\..\..\HEX\）
::    烧录：STC-ISP，型号 STC15F2K60S2，频率 11.0592MHz，烧完关闭 STC-ISP

:: 3) 联调链路自测（不开游戏也能验）
cd 02_上位机程序
python tools/serial_probe.py
```

> 更完整的运行 / 烧录 / 接线 / 验收步骤与 FAQ 见 `03_文档/06_用户手册/使用说明.md`。

---

## 六、说明

- **目录重组于本次提交完成**：原 `MCU/`、`485手柄/`、`无线手柄/`、`sound/`、
  `inc/`、`PC/`、`picture/` 及根目录散落文档已按上述结构归位；HEX 目录保持原样。
  重复代码（BSP 头文件、STC_BSP.lib、sound_effect.* 等）已合并为单一权威副本，
  合并清单与"旧→新"路径映射表见 `03_文档/08_整理记录/整理说明.md`。
- 详细历史版本（各版本验收记录）保留在 `03_文档/05_开发日志/开发日志.md` 与
  `03_文档/04_项目计划/开发计划.md`。

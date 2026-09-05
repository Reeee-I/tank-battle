> **目录重组提示**：本文件正文为迁移前的原始说明，其中涉及旧目录名（`MCU\`、`485手柄\`、`无线手柄\`、`sound\`、`PC\`、`inc\` 等）的路径均已随重组迁移，新旧路径对照见仓库根目录 `README.md` 及 `03_文档/08_整理记录/整理说明.md`。

# sound —— 蜂鸣器音效（测试开发，不影响任何已有功能）

本目录存放"双人坦克对战"蜂鸣器音效的全部测试代码与文档。
**所有新增代码都在本目录内**，仓库其余文件未做任何修改；宏关闭时行为与原版完全一致。

## 交付物对照表

| 交付物 | 文件 | 角色 / 用途 |
| :--- | :--- | :--- |
| ① 音效模块（.h/.c） | `sound_effect.h` + `sound_effect.c` | 统一音效模块：初始化 / 播放 / 忙闲查询 / 10ms 状态机驱动 |
| ② 有线手柄 main（SOUND_ENABLED=1） | `main_wired_handle_sound.c` | 有线模式两块手柄板（USB/串口直连电脑，玩家手边），源自 `MCU/main.c`，编译时用宏 PLAYER_ID=1/2 区分两块板 |
| ③ 无线发射端 main（SOUND_ENABLED=1） | `main_wireless_tx_sound.c` | 红外无线发送端 HEX-A（玩家手边），源自 `无线手柄/HEX_A_IR_Tx/main.c` |
| ④ 无线接收端 main（SOUND_ENABLED=0） | `main_wireless_rx_disabled.c` | 红外无线接收端 HEX-B（电脑旁，不发声），源自 `无线手柄/HEX_B_IR_Rx/main.c` |
| ⑤ 音频测试说明文档 | `音效测试与集成说明.md` | 集成步骤 / 音量控制 / 测试步骤与预期 / 验收记录表 / FAQ |
| （可选补充）485 手柄 main（SOUND_ENABLED=1） | `main_485_handle_sound.c` | 仓库主推的 485 三板方案中两块手柄板（玩家手边），源自 `485手柄/main_handle.c` |

> 各 main 文件的改动点都有 `【音效】` 注释标注，其余代码与原版逐行一致；
> 详情、集成步骤与测试方法见《音效测试与集成说明.md》。

## 一句话集成（以某块"玩家手边"的板为例）

1. 把对应版本 `main_xxx.c` 改名 `main.c`，覆盖到其 Keil 工程源目录（先备份原文件）；
2. 把 `sound_effect.h`、`sound_effect.c` 与 `main.c` 放同一目录，并把 `sound_effect.c` 加入工程；
3. 无线工程（HEX-A/HEX-B）的 `inc` 目录没有 `Beep.h`，把 `MCU\inc\Beep.h` 复制进去（或添加包含路径）；
4. 编译 → 烧录 → 听声（接收端板不要加 `sound_effect.c`）。

编码说明：本目录 `.c/.h` 为 **ANSI/GBK**（与仓库多数源码、Keil uVision4 中文环境一致），
`.md` 文档为 UTF-8。

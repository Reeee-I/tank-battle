# PC 端上位机（双人坦克对战）

Python + Pygame 游戏主程序。通过串口接收两块手柄板（或 485 中转板 / 红外接收板）
上行的 3 字节按键包驱动双人坦克对战，并下行 `AA D1/D2 HP` 血量帧驱动手柄 LED 血条。

## 环境要求

- Windows 10/11，Python 3.8+
- 依赖：`pip install -r requirements.txt`（pygame、pyserial）

## 运行

```bat
python main.py                    :: 自动扫描串口并按包内容绑定玩家
python main.py --p1 COM3 --p2 COM5 :: 手动指定两个手柄串口（485 单口可两参同写中转 COM）
python main.py --no-keyboard      :: 纯手柄模式（默认开启键盘调试控制）
python main.py --debug            :: 打印按键 / 重开 / 下行帧诊断
```

- 键盘调试：玩家1 = WASD + 空格（开火）；玩家2 = 方向键 + 回车；Esc 退出。
- 开始界面：任一手柄任意键 / 鼠标点击进入；对局结束：鼠标点击或任一手柄 K2 重开。

## 文件说明

| 文件 | 用途 |
|---|---|
| `main.py` | 程序入口：参数解析 / 创建 SerialHub 与 Game / 主循环 |
| `game.py` | Game 类：主循环 / 碰撞 / 道具 / 渲染 / 开始与结算界面 / 地图系统 |
| `tank.py` / `bullet.py` / `obstacle.py` / `powerup.py` | Tank / Bullet / Obstacle / PowerUp 实体类 |
| `serial_handler.py` | 串口接收线程 / 自动绑定玩家 / 0.6s 心跳断线 / 下行血量帧发送 |
| `requirements.txt` | Python 依赖清单 |
| `tests/` | 自动化自测（无硬件可跑，见下） |
| `tools/serial_probe.py` | 串口裸监听工具：实时打印解析出的玩家包，烧录后先跑它验证链路 |
| `素材/` | UI 重设计参考素材（原 `picture/`，代码暂未引用） |

## 自测（在 02_上位机程序 目录下执行）

```bat
python tests/test_logic.py          :: 游戏逻辑自测（无需 pygame/串口）
python tests/test_maps.py           :: 地图约束自测（对称/出生留空/开局遮挡/连通）
python tests/test_serial_e2e.py     :: 串口端到端自测（虚拟串口，含 485 单 COM 双玩家与下行血量帧）
python tests/acceptance_sim.py      :: 验收标准 1~8 自动化预演（虚拟板驱动游戏）
python tests/visual_qa.py           :: 画面 QA（截图输出到 tests/shots/）
python tests/text_layout_qa.py      :: HUD 文本 / 中文字体 QA
```

> 协议细节见 `../03_文档/03_通信协议/通信协议说明.md`；操作与 FAQ 见
> `../03_文档/06_用户手册/使用说明.md`。

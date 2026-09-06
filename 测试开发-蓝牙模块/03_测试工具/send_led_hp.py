# -*- coding: utf-8 -*-
"""send_led_hp.py —— 蓝牙测试工具：向指定 COM 下发一帧 LED 血量帧（测试开发专用）

用途（蓝牙测试的"下行链路"独立验证，不必开游戏）：
  - 打开蓝牙虚拟 COM（9600 8N1），下发 3 字节帧 AA D1/D2 HP；
  - 蓝牙手柄板收到后应把 LED(L0~L5) 刷新为对应血量：
        HP=3 满血六灯全亮；HP=2 亮 L0~L3；HP=1 亮 L0~L1；HP=0 全灭（死亡）。
  - 连续多发同值可验证"重发同血量不重复播音效"。

用法：
    python send_led_hp.py --list
    python send_led_hp.py --port COM6 --player 1 --hp 3
    python send_led_hp.py --port COM6 --player 2 --hp 0 --repeat 3

说明：
  - 本工具是蓝牙【测试开发】专用脚本，独立于 02_上位机程序（不改动任何
    既有代码；仅依赖 pyserial，即项目 requirements.txt 里已装好的库）。
  - 板端在收到首帧前 LED 默认全灭；本帧只做"单次状态刷新"，非周期心跳。
"""
import argparse
import sys
import time

PACKET_HEAD = 0xAA   # 包头（与协议一致）
DL_HP_P1    = 0xD1   # 下行命令码：玩家1 血量
DL_HP_P2    = 0xD2   # 下行命令码：玩家2 血量
HP_MAX      = 3      # 血量上限（满血=3）


def cmd_list():
    """列出所有串口（含蓝牙虚拟 COM，帮助找 COM 号）"""
    try:
        import serial.tools.list_ports as list_ports
    except Exception as e:
        print('[错误] 无法导入 pyserial：%s（请先 pip install pyserial）' % e)
        return 1
    print('当前串口列表（蓝牙虚拟 COM 的 description 一般含 bluetooth）：')
    found = False
    for info in list_ports.comports():
        found = True
        print('  %-8s %s' % (info.device, info.description or '(无描述)'))
    if not found:
        print('  （未发现任何串口。请先打开笔记本蓝牙并让蓝牙模块完成配对/连接。）')
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog='send_led_hp.py',
        description='蓝牙测试：手动下发一帧 LED 血量帧 AA <D1/D2> <HP>（9600 8N1）')
    parser.add_argument('--list', action='store_true',
                        help='列出全部串口（含蓝牙）后退出')
    parser.add_argument('--port', metavar='COMx', default=None,
                        help='目标蓝牙虚拟 COM 口（如 COM6）')
    parser.add_argument('--player', type=int, default=1, choices=[1, 2],
                        help='玩家号 1/2（决定命令码 D1/D2），默认 1')
    parser.add_argument('--hp', type=int, default=3, choices=range(0, 4),
                        help='血量 0~3（3=满血 六灯全亮），默认 3')
    parser.add_argument('--repeat', type=int, default=1,
                        help='连续下发次数（间隔 0.5s），默认 1')
    args = parser.parse_args()

    if args.list:
        return cmd_list()
    if not args.port:
        parser.print_help()
        print('\n[提示] 请用 --port 指定 COM（先用 --list 查看有哪些口）。')
        return 2

    try:
        import serial
    except Exception as e:
        print('[错误] 无法导入 pyserial：%s（请先 pip install pyserial）' % e)
        return 1

    code = DL_HP_P1 if args.player == 1 else DL_HP_P2
    frame = bytes((PACKET_HEAD, code, int(args.hp)))
    print('目标: %s  帧: AA %02X %02X（玩家%d 血量=%d）  波特率 9600 8N1'
          % (args.port, code, args.hp, args.player, args.hp))

    for i in range(args.repeat):
        try:
            with serial.Serial(port=args.port, baudrate=9600, bytesize=8,
                               parity='N', stopbits=1, timeout=1.0) as ser:
                ser.write(frame)
                print('  [%d/%d] 已写入 %s -> %s' % (i + 1, args.repeat,
                                                    frame.hex(' '), args.port))
        except Exception as e:
            print('  [%d/%d] 写入失败：%s' % (i + 1, args.repeat, e))
            print('  提示：确认模块已上电并与电脑完成蓝牙连接（COM 已存在）；'
                  '若报"打不开端口"，先在蓝牙设置里确认已连接，再重试。')
            return 1
        if i + 1 < args.repeat:
            time.sleep(0.5)
    print('完成。观察蓝牙手柄板 LED：HP=3 六灯全亮 / 2 四灯 / 1 两灯 / 0 全灭。')
    return 0


if __name__ == '__main__':
    sys.exit(main())

# -*- coding: utf-8 -*-
"""bt_port_test.py —— 蓝牙链路检测工具（测试开发专用）

用途：
  Windows 里蓝牙模块"已配对但未连接"时，虚拟 COM 打不开（游戏等待连接）。
  本工具逐个尝试打开蓝牙虚拟 COM（打开 = 触发一次拨号/等待模块拨入），
  并在打开成功后监听数秒统计收到的帧，帮你找出"真正能通"的那个 COM。

用法：
    python bt_port_test.py                # 自动枚举蓝牙 COM 并逐个测试
    python bt_port_test.py COM7 COM8      # 只测指定端口

判断：
  显示"收到 AA 01 x N" → 玩家1 蓝牙板链路通，游戏用 --p1 填这个 COM；
  显示"收到 AA 02 x N" → 玩家2 蓝牙板链路通，游戏用 --p2 填这个 COM；
  全部"打开失败/超时/无数据" → 链路没建立，先看 README 排查（模块上电、
  不在 AT 模式、Windows 里"已连接"而非仅"已配对"、添加传出 COM 等）。

先决条件：模块已配对；模块所在板已上电且模块不在 AT 模式
（LED 慢闪 ≈ 等待连接；快闪 ≈ AT 模式，需断电重上电且不按按键）。
"""
import sys
import threading
import time

import serial
import serial.tools.list_ports as list_ports

OPEN_TIMEOUT_S = 6.0   # 打开(拨号)最大等待
LISTEN_S = 4.0         # 打开成功后监听时长


def is_bt_port(info):
    text = (((info.description or '') + ' ' + (info.hwid or '')).lower())
    return 'bluetooth' in text or 'bthenum' in text or 'bth' in text


def try_open(port):
    """尝试打开串口（放入线程：传出口会阻塞拨号若干秒，传入口等待拨入）"""
    box = {'ser': None, 'err': None}

    def _open():
        try:
            box['ser'] = serial.Serial(port=port, baudrate=9600, bytesize=8,
                                       parity='N', stopbits=1, timeout=0.3)
        except Exception as e:
            box['err'] = e

    th = threading.Thread(target=_open, daemon=True)
    th.start()
    th.join(OPEN_TIMEOUT_S)
    if th.is_alive():
        print('[%s] 打开超时(%ss)：通常是“传入”口在等模块拨入，或拨号无应答'
              % (port, OPEN_TIMEOUT_S))
        return None
    if box['err'] is not None:
        print('[%s] 打开失败: %s' % (port, box['err']))
        return None
    return box['ser']


def listen_and_report(ser, port):
    raw = b''
    end = time.time() + LISTEN_S
    while time.time() < end:
        try:
            n = ser.in_waiting
            if n:
                raw += ser.read(n)
            else:
                b = ser.read(1)
                if b:
                    raw += b
        except Exception as e:
            print('[%s] 读取中断: %s' % (port, e))
            break
    try:
        ser.close()
    except Exception:
        pass

    n1 = raw.count(bytes((0xAA, 0x01)))
    n2 = raw.count(bytes((0xAA, 0x02)))
    if n1 or n2:
        print('[%s] ✔ 收到帧: AA01(玩家1)=%d 帧, AA02(玩家2)=%d 帧'
              % (port, n1, n2))
        if n1 > 0:
            print('     → 这就是玩家1 蓝牙板的口：游戏启动参数填  --p1 %s' % port)
        if n2 > 0:
            print('     → 这就是玩家2 蓝牙板的口：游戏启动参数填  --p2 %s' % port)
    else:
        print('[%s] 打开成功但 %ss 内无数据：链路未通或模块没在发（检查供电/固件）'
              % (port, LISTEN_S))
        if raw:
            print('     原始字节: %s' % raw[:24].hex(' '))


def main():
    args = sys.argv[1:]
    if args:
        ports = args
    else:
        ports = [i.device for i in list_ports.comports() if is_bt_port(i)]
    if not ports:
        print('未找到蓝牙虚拟 COM。先确认：模块已配对；然后在设备管理器'
              '“端口(COM和LPT)”里能看到 “标准串行 over 蓝牙链接(COMx)”。')
        return 1
    print('待测蓝牙 COM: %s   （每个口最多约 %ds，请耐心等待）'
          % ('、'.join(ports), OPEN_TIMEOUT_S + LISTEN_S))
    ok = 0
    for port in ports:
        ser = try_open(port)
        if ser is None:
            continue
        print('[%s] 打开成功，监听 %ss…' % (port, LISTEN_S))
        listen_and_report(ser, port)
        ok += 1
    print('测试结束。全部失败请按 README“PC 配对与 COM 识别/FAQ”排查。')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

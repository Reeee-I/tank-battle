# -*- coding: utf-8 -*-
"""tools/serial_probe.py —— 串口裸监听调试工具（可选）

用途：
  - 不启动游戏，直接观察两块板子发来的原始数据包；
  - 烧录后先跑本工具即可验证"板子 → PC"链路是否通畅；
  - 也是串口自动绑定、断线重连等功能的排障利器。

用法：
    python tools/serial_probe.py                # 自动扫描并监听所有串口
    python tools/serial_probe.py COM3 COM5      # 只监听指定串口
    Ctrl+C 退出
"""

import sys
import threading
import time


def print_packet(port, pid, mask, t0):
    """格式化打印一个数据包"""
    from serial_handler import mask_to_text
    el = time.monotonic() - t0
    print('[%s] 玩家%d  mask=0x%02X  →  %s   (%.1fs)'
          % (port, pid, mask, mask_to_text(mask), el), flush=True)


def monitor_port(port, stop_event, t0):
    """单个端口的监听循环（独立线程）"""
    import serial
    from serial_handler import PacketParser
    parser = PacketParser()
    while not stop_event.is_set():
        try:
            with serial.Serial(port=port, baudrate=9600, bytesize=8,
                               parity='N', stopbits=1, timeout=0.2) as ser:
                print('  [%s] 已打开，等待数据包…' % port, flush=True)
                while not stop_event.is_set():
                    try:
                        n = ser.in_waiting
                        data = ser.read(n) if n else ser.read(1)
                    except Exception:
                        break
                    for byte in data:
                        pkt = parser.feed(byte)
                        if pkt is not None:
                            print_packet(port, pkt[0], pkt[1], t0)
        except Exception as e:
            print('  [%s] 打开失败：%s（每2秒自动重试）' % (port, e), flush=True)
        # 等待重连（可被 Ctrl+C 中断）
        for _ in range(20):
            if stop_event.is_set():
                return
            time.sleep(0.1)


def main():
    import serial.tools.list_ports as list_ports

    ports = sys.argv[1:]
    if not ports:
        ports = [i.device for i in list_ports.comports()
                 if 'bluetooth' not in (i.description or '').lower()]
    if not ports:
        print('未发现可用串口。请先插入开发板 USB 线后重试。')
        return 1

    print('=' * 60)
    print(' 双人坦克对战 - 串口监听调试工具（Ctrl+C 退出）')
    print(' 协议: AA | 01/02 | 按键掩码  (9600,8N1)')
    print(' 监听端口: %s' % '、'.join(ports))
    print('=' * 60)

    stop_event = threading.Event()
    t0 = time.monotonic()
    threads = [threading.Thread(target=monitor_port,
                                args=(p, stop_event, t0), daemon=True)
               for p in ports]
    for t in threads:
        t.start()
    try:
        while not stop_event.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=1.0)
    print('\n监听结束。')
    return 0


if __name__ == '__main__':
    sys.exit(main())

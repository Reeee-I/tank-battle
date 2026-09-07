# -*- coding: utf-8 -*-
"""wait_link.py —— 等待游戏侧 COM 出现玩家帧（供“一键启动”脚本使用）

用法: python wait_link.py COM20 [秒数=45]
成功(收到任一 AA 01/AA 02 帧)返回 0，超时返回 1。
"""
import sys
import time

import serial


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM20"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 45
    t0 = time.time()
    last_report = 0
    ok = 0
    try:
        ser = serial.Serial(port, 9600, timeout=0.3)
    except Exception as e:
        print("[wait_link] 打开 %s 失败: %r" % (port, e))
        return 1
    print("[wait_link] 监听 %s，等待蓝牙手柄心跳（上限 %d 秒）..." % (port, limit))
    try:
        while time.time() - t0 < limit:
            n = ser.in_waiting
            data = ser.read(n) if n else ser.read(1)
            if data and (b"\xaa\x01" in data or b"\xaa\x02" in data):
                ok = 1
                break
            el = int(time.time() - t0)
            if el > last_report and el % 5 == 0:
                last_report = el
                print("[wait_link] %d 秒...还没收到帧，请确认蓝牙板已上电"
                      "（必要时断电重上电）" % el)
    finally:
        ser.close()
    if ok:
        print("[wait_link] 链路 OK：已收到玩家帧 → 可以启动游戏了")
        return 0
    print("[wait_link] 超时：未收到任何帧")
    return 1


if __name__ == "__main__":
    sys.exit(main())

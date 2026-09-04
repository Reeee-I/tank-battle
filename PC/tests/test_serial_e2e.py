# -*- coding: utf-8 -*-
"""tests/test_serial_e2e.py —— 串口接收链路端到端验证（无需真实硬件）

用 socket.socketpair() 构造虚拟串口对：
  - 一个端由 SerialHub 接收线程（SerialLink）持有；
  - 另一端由本脚本模拟"开发板"发包。
验证：打开→读字节→协议解析→自动绑定→心跳超时→恢复 全链路。

运行：python tests/test_serial_e2e.py
"""
import socket
import sys
import time

sys.path.insert(0, '.')
sys.path.insert(0, 'PC')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from serial_handler import (SerialHub, PLAYER1, PLAYER2,  # noqa: E402
                            BIT_LEFT, BIT_RIGHT, BIT_UP, BIT_DOWN, BIT_FIRE)
from game import Game  # noqa: E402


class FakeSerial(object):
    """最小的"类 pyserial"对象：包装 socket 的一端"""

    def __init__(self, sock):
        self._sock = sock
        self._sock.settimeout(0.05)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def in_waiting(self):
        import select
        r, _, _ = select.select([self._sock], [], [], 0)
        return 1 if r else 0

    def read(self, n):
        try:
            return self._sock.recv(n)
        except socket.timeout:
            return b''

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


def main():
    print('串口链路端到端自测（socketpair 虚拟串口）')
    print('-' * 50)

    # 为每个"端口名"建立 socketpair；factory 把一端交给接收线程
    peers = {}

    def factory(port):
        link_end, board_end = socket.socketpair()
        peers[port] = board_end
        return FakeSerial(link_end)

    hub = SerialHub(preferred=['mock_p1', 'mock_p2'])
    hub.start(factory=factory)
    # 等待两个接收线程就绪
    for _ in range(100):
        if len(peers) >= 2:
            break
        time.sleep(0.02)
    assert len(peers) == 2, peers
    b1, b2 = peers['mock_p1'], peers['mock_p2']

    # 模拟板1 发"上+开火"(AA 01 14)，板2 发"右"(AA 02 02)
    b1.send(bytes([0xAA, 0x01, 0x14]))
    b2.send(bytes([0xAA, 0x02, 0x02]))
    deadline = time.monotonic() + 3.0
    got = {}
    while time.monotonic() < deadline and len(got) < 2:
        for pid in (PLAYER1, PLAYER2):
            m, on = hub.get_control(pid)
            if on:
                got[pid] = m
        time.sleep(0.02)
    assert got.get(PLAYER1) == (BIT_UP | BIT_FIRE), got
    assert got.get(PLAYER2) == 0x02, got
    print('  [PASS] 虚拟板发包 → 自动绑定并解析正确掩码')

    # 身份自动绑定：哪端发哪个玩家号，就绑到哪个玩家
    assert hub.binding_port(PLAYER1) == 'mock_p1'
    assert hub.binding_port(PLAYER2) == 'mock_p2'
    print('  [PASS] COM口 ↔ 玩家自动绑定')

    # 垃圾字节流 + 连续两包：滑动窗口重同步（最后一包应生效）
    b1.send(bytes([0x11, 0xAA, 0x99, 0xAA, 0x01, 0x04, 0xAA, 0x01, 0x00]))
    deadline = time.monotonic() + 3.0
    last = None
    while time.monotonic() < deadline:
        m, on = hub.get_control(PLAYER1)
        if on:
            last = m
            if m == 0x00:
                break
        time.sleep(0.02)
    assert last == 0x00, last
    print('  [PASS] 噪声/坏包重同步')

    # 心跳超时：>0.6s 不再收包 → 判离线、掩码清零
    time.sleep(0.9)                       # 超过 HEARTBEAT_TIMEOUT(0.6s)
    m, on = hub.get_control(PLAYER1)
    assert not on and m == 0, (m, on)
    print('  [PASS] 超时判离线且输入冻结')

    # 恢复：继续发包 → 重新在线
    b1.send(bytes([0xAA, 0x01, 0x08]))
    deadline = time.monotonic() + 3.0
    ok = False
    while time.monotonic() < deadline:
        m, on = hub.get_control(PLAYER1)
        if on and m == 0x08:
            ok = True
            break
        time.sleep(0.02)
    assert ok
    print('  [PASS] 恢复在线')

    # —— 联合集成：虚拟板 → SerialHub → Game 真实驱动 ——
    class FClock(object):
        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t

        def advance(self, dt):
            self.t += dt

    g = Game(hub=hub, keyboard=False)
    fc = FClock()
    g.set_clock(fc)

    # 1) 板1 发"前进"持续包 → 坦克应持续右移
    x0 = g.tanks[PLAYER1].x
    b1.send(bytes([0xAA, 0x01, BIT_UP]))
    time.sleep(0.15)                       # 让接收线程解析并刷新
    for _ in range(30):                    # 0.5s ≈ 30 帧
        fc.advance(1 / 60.0)
        g.update()
    assert g.tanks[PLAYER1].x > x0 + 60, (x0, g.tanks[PLAYER1].x)
    print('  [PASS] 集成：板1按住上 → 坦克前进')

    # 2) 板1 发"开火"单发 → 应发射子弹（先清开火沿）
    b1.send(bytes([0xAA, 0x01, 0x00]))
    time.sleep(0.15)
    b1.send(bytes([0xAA, 0x01, BIT_FIRE]))
    deadline = time.monotonic() + 2.0
    fired = False
    while time.monotonic() < deadline:
        fc.advance(1 / 60.0)
        g.update()
        if len(g.bullets[PLAYER1]) > 0:
            fired = True
            break
        time.sleep(0.01)
    assert fired, '虚拟板开火应产生子弹'
    print('  [PASS] 集成：板1按K1 → 坦克开火(单发)')

    b1.close()
    b2.close()
    hub.stop()
    print('-' * 50)
    print('串口链路端到端自测通过 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())

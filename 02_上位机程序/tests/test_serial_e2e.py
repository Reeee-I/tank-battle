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

    def write(self, data):
        """PC → 板 下行（血量帧等）：发到板端 socket"""
        return self._sock.sendall(data)

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


_streams = {}     # socket → 未消费的下行字节缓存（跨 recv_frame 调用不丢帧）


def recv_frame(sock, code, timeout=2.0):
    """从"板端"socket 读取下行帧，返回首个匹配 AA <code> <hp> 的 hp。
    每 socket 维护字节缓存，帧连续到达（同一 recv 块）也不丢失；
    超时未收到返回 None。"""
    sock.settimeout(0.2)
    buf = _streams.get(sock, b'')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while len(buf) < 3:
            try:
                chunk = sock.recv(64)
            except socket.timeout:
                chunk = b''
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
        while len(buf) >= 3:
            if buf[0] == 0xAA and buf[1] in (0xD1, 0xD2):
                if buf[1] == code:
                    _streams[sock] = buf[3:]
                    return buf[2]
                buf = buf[3:]          # 其它命令码：跳过整帧
            else:
                buf = buf[1:]          # 未对齐：滑动一个字节
        time.sleep(0.005)
    _streams[sock] = buf
    return None


def drain_socket(sock, idle=0.15):
    """丢弃已到达的下行字节（含缓存），读到短超时空闲为止"""
    _streams.pop(sock, None)
    sock.settimeout(idle)
    while True:
        try:
            if not sock.recv(1024):
                break
        except socket.timeout:
            break
        except OSError:
            break


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

    # —— 下行：PC → 板 LED 血量帧（AA D1/D2 HP，满血3/掉血/归零）——
    hub.set_hp(PLAYER1, 3)              # 满血 → AA D1 03
    hub.set_hp(PLAYER2, 2)              # 掉 1 血 → AA D2 02
    hub.set_hp(PLAYER2, 0)              # 死亡 → AA D2 00
    assert recv_frame(b1, 0xD1) == 3, '玩家1 板应收到 AA D1 03'
    assert recv_frame(b2, 0xD2) == 2, '玩家2 板应收到 AA D2 02'
    assert recv_frame(b2, 0xD2) == 0, '玩家2 板应收到 AA D2 00'
    print('  [PASS] 下行：血量帧 AA D1/D2 HP 按玩家送达（满血3/掉血2/归零0）')

    # —— 下行补发：端口重连（打开代数+1）后首个上行包 → 重发最新血量 ——
    with hub._lock:
        hub._port_gen['mock_p1'] = hub._port_gen.get('mock_p1', 0) + 1
    b1.send(bytes([0xAA, 0x01, 0x08]))
    assert recv_frame(b1, 0xD1) == 3, '重连后应自动补发最新血量 AA D1 03'
    print('  [PASS] 下行：断线重连/换口后按最新血量自动补发')

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

    # 3) 命中 → 血量下行：P2 被击中扣 1 血 → 玩家2 板应收到 AA D2 02
    #    （Game 在扣血时经 hub 下行最新血量；LED 亮灭由真板执行）
    g.bullets[PLAYER1] = []                # 清掉此前测试残留子弹，保证只射一枪
    g.bullets[PLAYER2] = []
    g.obstacles = []                       # 开阔场直射，避免地图掩体挡弹
    t1 = g.tanks[PLAYER1]
    t1.x, t1.y, t1.angle = 100.0, 300.0, 0.0
    t2 = g.tanks[PLAYER2]
    t2.x, t2.y, t2.angle = 170.0, 300.0, 180.0
    g._prev[PLAYER1] = 0
    g._prev[PLAYER2] = 0
    drain_socket(b2)                       # 丢弃此前历史下行帧（如开局满血）
    fc.advance(0.3)                        # 越过上一枪的 200ms 开火冷却
    g._inject[PLAYER1] = 0
    for _ in range(2):
        fc.advance(1 / 60.0)
        g.update()
    g._inject[PLAYER1] = BIT_FIRE
    deadline = time.monotonic() + 2.0
    hit = False
    while time.monotonic() < deadline:
        fc.advance(1 / 60.0)
        g.update()
        if g.tanks[PLAYER2].lives < 3:
            hit = True
            break
        time.sleep(0.005)
    g._inject[PLAYER1] = 0
    assert hit, 'P1 子弹应命中 P2'
    assert g.tanks[PLAYER2].lives == 2, g.tanks[PLAYER2].lives
    assert recv_frame(b2, 0xD2) == 2, '命中后板2 应收到 AA D2 02（LED 灭 2 灯）'
    print('  [PASS] 集成：命中扣血 → 血量下行 AA D2 02 送达玩家2 板')

    # —— 485 中转板场景：单一 COM 口同时承载玩家1 与 玩家2 ——
    # 两块手柄不再直连 PC，而是经"中转板"轮询后从一个 COM 口交替上送两玩家
    # 的数据包。断言：两玩家都绑定到同一端口、掩码/在线判定互不干扰。
    peers_hub = {}

    def factory_hub(port):
        link_end, board_end = socket.socketpair()
        peers_hub[port] = board_end
        return FakeSerial(link_end)

    hub2 = SerialHub(preferred=['mock_485hub'])
    hub2.start(factory=factory_hub)
    for _ in range(100):
        if len(peers_hub) >= 1:
            break
        time.sleep(0.02)
    assert len(peers_hub) == 1, peers_hub
    bh = peers_hub['mock_485hub']

    # 模拟中转板交替转发玩家1（AA 01 14=上+开火）与玩家2（AA 02 02=右）的包
    bh.send(bytes([0xAA, 0x01, 0x14]))
    bh.send(bytes([0xAA, 0x02, 0x02]))
    deadline = time.monotonic() + 3.0
    got = {}
    while time.monotonic() < deadline and len(got) < 2:
        for pid in (PLAYER1, PLAYER2):
            m, on = hub2.get_control(pid)
            if on:
                got[pid] = m
        time.sleep(0.02)
    assert got.get(PLAYER1) == (BIT_UP | BIT_FIRE), got
    assert got.get(PLAYER2) == 0x02, got
    # 关键断言：两玩家绑到同一 COM（单端口多玩家，485 中转板拓扑）
    assert hub2.binding_port(PLAYER1) == 'mock_485hub'
    assert hub2.binding_port(PLAYER2) == 'mock_485hub'
    # —— 485 单 COM 下行：两条血量帧（AA D1/D2 HP）按玩家号从同一口发出，
    #    由中转板在 485 总线空闲窗口分别转发给对应手柄 ——
    hub2.set_hp(PLAYER1, 3)              # 玩家1 满血 → AA D1 03
    hub2.set_hp(PLAYER2, 1)              # 玩家2 剩 1 血 → AA D2 01
    assert recv_frame(bh, 0xD1) == 3, '485 单 COM 应收到 AA D1 03'
    assert recv_frame(bh, 0xD2) == 1, '485 单 COM 应收到 AA D2 01'
    print('  [PASS] 485中转：单 COM 下行血量帧 D1/D2 均按玩家正确发出')
    # 中转板整体掉线（如拔其 USB）→ 两玩家心跳同时超时判离线
    bh.send(bytes([0xAA, 0x02, 0x04]))
    bh.send(bytes([0xAA, 0x01, 0x08]))
    time.sleep(0.1)
    bh.close()
    time.sleep(0.9)
    m1, on1 = hub2.get_control(PLAYER1)
    m2, on2 = hub2.get_control(PLAYER2)
    assert not on1 and not on2 and m1 == 0 and m2 == 0, (on1, on2)
    hub2.stop()
    print('  [PASS] 485中转：单COM口两玩家同端口绑定/中转板掉线两玩家判离线')

    b1.close()
    b2.close()
    hub.stop()
    print('-' * 50)
    print('串口链路端到端自测通过 ✓（含 485 中转单 COM 场景）')
    return 0


if __name__ == '__main__':
    sys.exit(main())

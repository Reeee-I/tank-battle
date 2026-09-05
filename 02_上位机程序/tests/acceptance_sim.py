# -*- coding: utf-8 -*-
"""tests/acceptance_sim.py —— 验收标准(1~7) 自动化预演（无需硬件）

把 README 验收清单中"可自动化"的条目，用虚拟串口板(socketpair)真实驱动
游戏逐条跑一遍，输出 PASS/FAIL 对照表。真板到位后同样可直接复用本流程。

运行：python tests/acceptance_sim.py
"""
import socket
import sys
import time

sys.path.insert(0, '.')
sys.path.insert(0, 'PC')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from serial_handler import (SerialHub, PLAYER1, PLAYER2, BIT_UP, BIT_FIRE,  # noqa: E402
                            BIT_RESTART)  # noqa: E402
from game import Game, START_LIVES, SCORE_PER_HIT  # noqa: E402


class FakeSerial(object):
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


_streams = {}     # socket → 未消费的下行字节缓存（跨 recv_hp 调用不丢帧）


def recv_hp(sock, code, expect, timeout=2.0):
    """从板端 socket 读取下行帧，直到找到 AA <code> <expect>（跳过历史帧）。
    每 socket 维护字节缓存，帧连续到达也不丢失；找到返回 True，超时返回 False。"""
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
                if buf[1] == code and buf[2] == expect:
                    _streams[sock] = buf[3:]
                    return True
                buf = buf[3:]
            else:
                buf = buf[1:]
        time.sleep(0.005)
    _streams[sock] = buf
    return False


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


class FClock(object):
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


RESULTS = []


def record(no, ok, note):
    RESULTS.append((no, ok, note))
    print('  验收%d  [%s]  %s' % (no, 'PASS' if ok else 'FAIL', note))


def wait_until(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def main():
    print('双人坦克对战 · 验收标准(1~8) 自动化预演（虚拟串口板驱动）')
    print('=' * 62)
    print(' 注：身份=数码管（验收1）；LED=血量条（验收8，亮灭需真板确认）。')
    print('=' * 62)

    # ---------- 环境：两块虚拟板 + Game ----------
    peers = {}

    def factory(port):
        link_end, board_end = socket.socketpair()
        peers[port] = board_end
        return FakeSerial(link_end)

    hub = SerialHub(preferred=['COM_SIM_P1', 'COM_SIM_P2'])
    hub.start(factory=factory)
    wait_until(lambda: len(peers) >= 2)
    b1, b2 = peers['COM_SIM_P1'], peers['COM_SIM_P2']

    g = Game(hub=hub, keyboard=False)
    fc = FClock()
    g.set_clock(fc)

    def frames(n):
        for _ in range(n):
            fc.advance(1 / 60.0)
            g.update()

    def send(port, pid, mask):
        port.send(bytes([0xAA, pid, mask]))
        time.sleep(0.08)              # 等接收线程解析

    # ---------- 验收1：身份绑定（LED 为硬件项，此处验证包内玩家号绑定） ----------
    send(b1, 0x01, 0x00)
    send(b2, 0x02, 0x00)
    ok = (hub.binding_port(PLAYER1) == 'COM_SIM_P1' and
          hub.binding_port(PLAYER2) == 'COM_SIM_P2')
    record(1, ok, '身份绑定：板1→玩家1、板2→玩家2（真板数码管显示 1/2 为硬件项，需实物确认）')

    # ---------- 验收2：导航键移动/转向 ----------
    t1 = g.tanks[PLAYER1]
    x0 = t1.x
    send(b1, 0x01, BIT_UP)
    frames(20)
    moved = t1.x > x0 + 40
    send(b1, 0x01, 0x00)
    frames(2)
    a0 = t1.angle
    send(b1, 0x01, 0x02)              # 右转
    frames(10)
    turned = (t1.angle - a0) % 360 > 15
    send(b1, 0x01, 0x00)
    frames(2)
    record(2, moved and turned, '导航键驱动：前进移动 + 转向（角度变化 %.0f°）' %
           ((t1.angle - a0) % 360))

    # ---------- 验收6：障碍物阻挡（先于开火场景验证，避免路线被挡） ----------
    t1.x, t1.y, t1.angle = 300.0, 245.0, 0.0     # 正对中央横墙
    send(b1, 0x01, BIT_UP)
    frames(40)
    blocked = t1.x + 15.0 <= 345.0 + 1e-6 and t1.x > 320.0
    send(b1, 0x01, 0x00)
    frames(2)
    record(6, blocked, '坦克被障碍物阻挡（车体右缘未越过障碍左缘，x=%.1f）' % t1.x)

    # ---------- 验收3/4/5：开火 → 命中 → 三命耗尽 → 胜负 ----------
    send(b1, 0x01, 0x00)
    frames(2)
    # 坦克归位并直指玩家2：出生点间的直线（y=300）被中央掩体遮挡（平衡设计），
    # 因此把玩家1 前移到掩体右缘之后的空道（x500），使弹道畅通只验证"命中结算"链路
    t1.x, t1.y, t1.angle = 500.0, 300.0, 0.0
    t2 = g.tanks[PLAYER2]
    t2.x, t2.y, t2.angle = 650.0, 300.0, 180.0
    g._prev[PLAYER2] = 0
    lives = [START_LIVES]
    score = [0]
    fired_once = [False]

    def watch_state():
        lives[0] = t2.lives
        score[0] = g.tanks[PLAYER1].score

    hits = 0
    dl_hit2 = False            # 验收8：首次命中后收到 AA D2 02（掉血灭 2 灯）
    for shot in range(START_LIVES):
        send(b1, 0x01, 0x00)          # 先清沿：确保 K1 每次产生上升沿(单发)
        frames(3)
        send(b1, 0x01, BIT_FIRE)      # K1 按下瞬间 → 单发
        fired_once[0] = True
        # 边沿已形成；等子弹飞到并命中
        deadline = time.monotonic() + 3.0
        hit_this = False
        while time.monotonic() < deadline and not hit_this:
            frames(1)
            if t2.lives < START_LIVES - hits or g.game_over:
                hit_this = True
                break
            time.sleep(0.005)
        if not hit_this:
            break
        hits += 1
        watch_state()
        if hits == 1:
            # 首次命中（3→2 命）：玩家2 板应收到 AA D2 02
            dl_hit2 = recv_hp(b2, 0xD2, 2)
        # 等重生无敌(1s)结束再补下一枪
        for _ in range(70):
            frames(1)
    watch_state()

    record(3, fired_once[0] and hits >= 1,
           'K1 开火：共命中 %d 次（首枪已发射）' % hits)
    record(4, hits >= 1 and t2.lives <= START_LIVES - 1 and
           g.tanks[PLAYER1].score == SCORE_PER_HIT * min(hits, 3),
           '命中结算：生命 %d→%d、射手得分 %d' % (START_LIVES, t2.lives,
                                           g.tanks[PLAYER1].score))
    record(5, g.game_over and g.winner == PLAYER1 and t2.lives == 0,
           '生命归零 → 玩家1 获胜（game_over=%s winner=%s）' %
           (g.game_over, g.winner))

    # 验收8（前半）：死亡后板2 应收到 AA D2 00（LED 全灭）
    dl_dead0 = recv_hp(b2, 0xD2, 0)

    # ---------- 验收7：手柄按 K2(bit5) 重开（虚拟板真实驱动） ----------
    assert g.game_over
    send(b1, 0x01, 0x00)                  # 先清沿
    frames(3)
    drain_socket(b1)                      # 清历史帧：重开满血(03)要与绑定补发区分
    drain_socket(b2)                      # 同上（02/00 证据已在上方取到）
    send(b1, 0x01, BIT_RESTART)           # 玩家1 手柄按 K2
    deadline = time.monotonic() + 3.0
    restarted = False
    while time.monotonic() < deadline:
        frames(1)
        if not g.game_over:
            restarted = True
            break
        time.sleep(0.005)
    record(7, restarted and g.winner is None and
           g.tanks[PLAYER1].lives == START_LIVES and
           g.tanks[PLAYER2].lives == START_LIVES and
           g.tanks[PLAYER1].score == 0,
           '手柄按 K2 重开：生命/得分/胜负状态全部复位')

    # ---------- 验收8：手柄 LED 血量联动（PC→板下行帧；LED 亮灭为硬件项） ----------
    #   板2 依序收到：首次命中 AA D2 02 → 死亡 AA D2 00 → K2 重开 AA D2 03；
    #   板1 收到 K2 重开后的 AA D1 03（开局/重开都从满血 3 命下发）。
    refill1 = recv_hp(b1, 0xD1, 3)        # K2 重开 → 板1 满血 AA D1 03
    refill2 = recv_hp(b2, 0xD2, 3)        # K2 重开 → 板2 满血 AA D2 03
    record(8, dl_hit2 and dl_dead0 and refill1 and refill2,
           '血量下行：命中→AA D2 02、死亡→AA D2 00、K2重开→两板 AA D1/D2 03'
           '（LED 灭 2 灯/全灭/六灯全亮为硬件项，需真板确认）')

    b1.close()
    b2.close()
    hub.stop()

    print('=' * 62)
    fails = [r for r in RESULTS if not r[1]]
    if fails:
        print('未通过 %d 项：%s' % (len(fails), [f[0] for f in fails]))
        return 1
    print('验收标准 1~8 自动化预演全部通过 ✓（验收1 亮灯/验收8 亮灯为硬件项需真板确认）')
    return 0


if __name__ == '__main__':
    sys.exit(main())

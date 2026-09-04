# -*- coding: utf-8 -*-
"""serial_handler.py —— 串口通信模块（双人坦克对战 PC 端）

职责：
  1. 协议定义：与板端完全一致的 3 字节数据包解析/组包说明；
  2. PacketParser：字节流状态机解析器（纯逻辑，可独立测试）；
  3. SerialLink   ：单个串口口的接收线程（含断线自动重连）；
  4. SerialHub    ：统一管理两个板子对应的串口，向游戏提供按键状态，
                    并自动完成「COM口 ↔ 玩家ID」绑定。

通信协议（9600bps, 8 数据位, 1 停止位, 无校验）：
    字节0 : 0xAA              包头
    字节1 : 0x01 / 0x02       玩家1 / 玩家2
    字节2 : 按键位掩码
           bit0 左(左转)  bit1 右(右转)  bit2 上(前进)
           bit3 下(后退)  bit4 开火(K1,单发)  bit5 重开请求(K2,单发)
           bit6 K3(单发；PC 仅在开始界面当作"任意键开始"输入，对战中无含义)

设计要点：
  - 接收放在独立线程中，绝不阻塞游戏主循环；
  - 玩家身份由数据包内容（字节1）决定：哪块板先发来合法包，
    就把它绑到对应玩家上，用户无需记住线序；
  - 超过 HEARTBEAT_TIMEOUT 未收到某玩家数据 → 判定该玩家断线，
    串口线程会持续尝试重连，重连成功后自动恢复。
"""

import threading
import time

# ------------------------------ 协议常量 ------------------------------
PACKET_HEAD = 0xAA          # 包头（固定）
PLAYER1     = 0x01          # 玩家1 号
PLAYER2     = 0x02          # 玩家2 号

BIT_LEFT    = 0x01          # bit0：左（左转）
BIT_RIGHT   = 0x02          # bit1：右（右转）
BIT_UP      = 0x04          # bit2：上（前进）
BIT_DOWN    = 0x08          # bit3：下（后退）
BIT_FIRE    = 0x10          # bit4：开火（K1，单发）
BIT_RESTART = 0x20          # bit5：重开请求（K2，单发；仅对局结束时生效）
BIT_K3      = 0x40          # bit6：K3（单发；PC 开始界面"任意键开始"用，对战中忽略）

BAUDRATE    = 9600          # 波特率（与板端一致）

HEARTBEAT_TIMEOUT   = 0.6   # 秒：超过该时长未收到数据判定为断线
RECONNECT_INTERVAL  = 2.0   # 秒：断线后的自动重连间隔


def mask_to_text(mask):
    """把按键掩码转成可读文本（用于调试工具 / 界面状态）"""
    parts = []
    if mask & BIT_LEFT:
        parts.append('左')
    if mask & BIT_RIGHT:
        parts.append('右')
    if mask & BIT_UP:
        parts.append('上')
    if mask & BIT_DOWN:
        parts.append('下')
    if mask & BIT_FIRE:
        parts.append('开火')
    if mask & BIT_RESTART:
        parts.append('K2')
    if mask & BIT_K3:
        parts.append('K3')
    return ('+'.join(parts)) if parts else '无'


class PacketParser:
    """字节流 → 数据包解析器（滑动窗口自动重同步）

    用法：
        p = PacketParser()
        for byte in data:                 # data 为任意字节流
            pkt = p.feed(byte)
            if pkt is not None:
                pid, mask = pkt           # 解析出一个合法数据包
    """

    def __init__(self):
        self._stage = 0      # 0=找包头 1=等玩家号 2=读按键字节
        self._pid = 0

    def feed(self, byte):
        """喂入一个字节；若凑成一个合法包返回 (玩家号, 掩码)，否则 None"""
        if self._stage == 0:
            # 找包头：0xAA 进入下一阶段
            if byte == PACKET_HEAD:
                self._stage = 1
        elif self._stage == 1:
            # 等玩家号：合法则进入读按键；非法则丢弃（若又是包头则继续等）
            if byte == PLAYER1 or byte == PLAYER2:
                self._pid = byte
                self._stage = 2
            elif byte != PACKET_HEAD:
                self._stage = 0
        else:
            # 读到按键字节：完整一包，复位状态机并返回结果
            self._stage = 0
            return (self._pid, byte)
        return None

    def feed_bytes(self, data):
        """批量喂入 bytes，返回解析出的 [(玩家号, 掩码), ...]"""
        out = []
        for b in data:
            pkt = self.feed(b)
            if pkt is not None:
                out.append(pkt)
        return out


class SerialLink:
    """单个串口的接收线程。

    负责：打开串口 → 持续读字节 → 喂给解析器 → 回调 SerialHub；
    读失败（拔线/占用）后按 RECONNECT_INTERVAL 周期自动重连，直到 stop。
    """

    def __init__(self, port_name, on_packet, on_state, stop_event, factory=None):
        self.port_name = port_name
        self.on_packet = on_packet    # on_packet(pid, mask, port)
        self.on_state = on_state      # on_state(port, opened: bool)
        self.stop_event = stop_event
        # factory: 返回一个"类 serial"对象（默认 pyserial.Serial），
        # 供单元测试注入虚拟串口对（socketpair），无需真实硬件
        if factory is None:
            factory = self._default_factory
        self._open = factory
        self._thread = None

    def _default_factory(self):
        """默认打开真实串口：9600 8N1，与板端一致"""
        import serial
        return serial.Serial(port=self.port_name, baudrate=BAUDRATE,
                             bytesize=8, parity='N', stopbits=1,
                             timeout=0.05)

    # -- 生命周期 --
    def start(self):
        self._thread = threading.Thread(
            target=self._run, name='SerialLink-%s' % self.port_name, daemon=True)
        self._thread.start()

    def stop(self):
        # 线程为 daemon 且通过 stop_event 退出，最长等待 1 秒
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    # -- 接收主循环 --
    def _run(self):
        while not self.stop_event.is_set():
            try:
                # 打开串口（默认 9600 8N1 与板端一致；测试可注入虚拟端口）
                with self._open() as ser:
                    self.on_state(self.port_name, True)
                    parser = PacketParser()   # 每次连接重建解析器：
                    # 防止拔线/重连后残留"半包"状态把新流首字节误解析成按键
                    while not self.stop_event.is_set():
                        try:
                            waiting = ser.in_waiting
                            if waiting > 0:
                                chunk = ser.read(waiting)
                            else:
                                chunk = ser.read(1)  # 带超时，顺便当心跳
                        except Exception:
                            break  # 读取异常 → 走重连
                        for byte in chunk:
                            pkt = parser.feed(byte)
                            if pkt is not None:
                                try:
                                    self.on_packet(pkt[0], pkt[1], self.port_name)
                                except Exception:
                                    pass  # 回调异常不影响接收线程存活
            except Exception:
                pass  # 打开失败（如端口被占用/不存在）→ 稍后重试
            finally:
                try:
                    self.on_state(self.port_name, False)
                except Exception:
                    pass
            # 断线后等待重连（期间可被 stop 中断）
            for _ in range(int(RECONNECT_INTERVAL * 10)):
                if self.stop_event.is_set():
                    return
                time.sleep(0.1)


class SerialHub:
    """手柄控制器统一入口：向游戏暴露 get_control()。

    自动绑定：哪个 COM 口先发来玩家 X 的合法包，该口即被绑定为玩家 X。
    手动指定：start(preferred=[...]) 可限定只打开这些端口。
    """

    def __init__(self, preferred=None):
        self._preferred = list(preferred) if preferred else None
        self._links = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        # 每玩家最近状态
        self._state = {
            PLAYER1: {'port': None, 'mask': 0, 'last': 0.0},
            PLAYER2: {'port': None, 'mask': 0, 'last': 0.0},
        }
        self._errors = []          # 打开失败的提示信息
        self._open_ports = set()   # 当前实际打开中的端口

    # ------------------------------ 生命周期 ------------------------------
    def start(self, factory=None):
        """扫描并打开串口（自动模式或按 preferred 限定）

        factory：可选，接收(端口名)返回类 serial 对象的函数，
                 供测试注入虚拟串口；为 None 时使用真实 pyserial。
        返回打开的 SerialLink 列表；扫描/导入失败记入 self.errors()。
        """
        candidates = []
        if self._preferred:
            candidates = list(self._preferred)
        else:
            # 自动扫描：普通 USB 转串口都尝试打开，蓝牙等排除
            try:
                import serial.tools.list_ports as list_ports
                for info in list_ports.comports():
                    desc = (info.description or '').lower()
                    if 'bluetooth' in desc or 'bth' in desc:
                        continue
                    candidates.append(info.device)
            except Exception as e:
                # 未安装 pyserial 等情形：不崩溃，退化为纯键盘模式
                with self._lock:
                    self._errors.append('串口组件不可用，已退化为纯键盘模式：%s' % e)
        self._candidates = list(candidates)
        # 去重（防 --p1/--p2 重复指定同一端口导致双线程抢口）
        seen = set()
        ports = []
        for port in candidates:
            if port not in seen:
                seen.add(port)
                ports.append(port)
        for port in ports:
            link_factory = None
            if factory is not None:
                link_factory = (lambda p=port: factory(p))
            link = SerialLink(port, self._on_packet, self._on_state,
                              self._stop_event, factory=link_factory)
            self._links.append(link)
            link.start()
        return self._links

    def candidates(self):
        """返回本次尝试打开的端口列表"""
        return list(getattr(self, '_candidates', []))

    def stop(self):
        self._stop_event.set()
        for link in self._links:
            link.stop()

    # ------------------------------ 回调 ------------------------------
    def _on_state(self, port, opened):
        with self._lock:
            if opened:
                self._open_ports.add(port)
            else:
                self._open_ports.discard(port)

    def _on_packet(self, pid, mask, port):
        now = time.monotonic()
        with self._lock:
            st = self._state[pid]
            st['port'] = port
            st['mask'] = mask
            st['last'] = now

    # ------------------------------ 查询 ------------------------------
    def get_control(self, pid, now=None):
        """返回 (最新掩码, 是否在线)。

        - 在线判定：该玩家已绑定且 HEARTBEAT_TIMEOUT 内有新数据；
        - 不在线时掩码返回 0（游戏据此冻结该玩家输入）。
        """
        if now is None:
            now = time.monotonic()
        with self._lock:
            st = self._state.get(pid)
            if st is None:
                return (0, False)
            connected = (st['port'] is not None and
                         (now - st['last']) <= HEARTBEAT_TIMEOUT)
            mask = st['mask'] if connected else 0
            return (mask, connected)

    def is_bound(self, pid):
        with self._lock:
            return self._state[pid]['port'] is not None

    def binding_port(self, pid):
        with self._lock:
            return self._state[pid]['port']

    def open_ports(self):
        with self._lock:
            return sorted(self._open_ports)

    def errors(self):
        with self._lock:
            return list(self._errors)

    def bound_count(self):
        with self._lock:
            return sum(1 for p in (PLAYER1, PLAYER2)
                       if self._state[p]['port'] is not None)

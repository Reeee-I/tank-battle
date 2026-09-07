# -*- coding: utf-8 -*-
"""ble_bridge.py —— BLE↔虚拟串口 桥接程序（蓝牙测试开发专用）

背景：手头模块是 BT05（CC2541 BLE 透传，0xFFE0/0xFFE1），Windows 不会把它
变成 COM 口。本程序把 BLE 链路上的字节流搬到一对虚拟串口的一侧（另一侧给
游戏用），从而让既有游戏（pyserial 打开普通 COM）无需改动即可联机：

    游戏 main.py --p1 COM_A      ┌── com0com 虚拟串口对 ──┐
                              ──►│ COM_A (游戏)  COM_B (桥) │──► ble_bridge.py
                                 └──────────────────────┘       │ bleak(BLE)
                                                          BT05 模块 ←UART← 手柄板

用法：
    python ble_bridge.py --com COM_B --addr 00:15:83:F0:15:97 [--debug]

    --com   : 桥接程序占用的虚拟串口（com0com 对的一侧，另一侧给游戏 --p1）
    --addr  : 模块蓝牙地址（BT05 一般为 00:15:83:F0:15:97）
    --debug : 打印双向字节流（十六进制）
    --scan  : 只扫描附近 BT05/BT 模块（列出地址与名称）后退出

依赖：本目录下 _bleak_deps（已内置 bleak+winrt）与已安装的 pyserial。
特性：双向透传、BLE/串口各自断线自动重连、Ctrl+C 退出。
注意：模块"已配对且不广播"时扫不到也连不上 → 请把蓝牙手柄板断电重上电
（模块重新广播）再启动本程序；连接期间不要在 Windows 设置里动该设备。
"""
import argparse
import asyncio
import os
import sys
import threading
import time

# ---- 本地依赖：优先本目录下的 _bleak_deps / _bleak_deps312 ----
_HERE = os.path.dirname(os.path.abspath(__file__))
for _dep in ("_bleak_deps", "_bleak_deps312"):
    _p = os.path.join(_HERE, _dep)
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
        break

import serial                      # pyserial（项目已有）
import bleak                       # BLE（本地 _bleak_deps）

BLE_SVC = "0000ffe0-0000-1000-8000-00805f9b34fb"
BLE_CHR = "0000ffe1-0000-1000-8000-00805f9b34fb"
SERIAL_BAUD = 9600


# ============================ 扫描模式 ============================
async def cmd_scan(filter_text=None):
    print("正在扫描 BLE 设备 12 秒（Ctrl+C 可提前结束）…")
    devs = await bleak.BleakScanner.discover(timeout=12.0)
    hit = []
    for d in devs:
        name = d.name or ""
        if filter_text and filter_text.lower() not in name.lower():
            continue
        if filter_text or name or d.address.upper().startswith("00:15:83"):
            hit.append(d)
            print("   %s  %r" % (d.address, d.name))
    if not hit:
        print("没有找到匹配设备。请确认模块已上电且正在广播"
              "（必要时把蓝牙手柄板断电重上电一次）。")
    return 0


# ============================ 查找并连接 ============================
async def find_and_connect(addr):
    """先扫描找模块（模块广播时才能连），再建立 BLE 连接"""
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        devs = await bleak.BleakScanner.discover(timeout=5.0)
        for d in devs:
            if d.address.lower() == addr.lower():
                client = bleak.BleakClient(d, timeout=10.0)
                await client.connect()
                return client
        print("    …还没扫到 %s，继续找（模块上电后应广播）" % addr)
    return None


async def ble_session(client, tx_queue, on_rx, log):
    """连接建立后：订阅 notify（BLE→串口），并消费队列（串口→BLE）。
    返回条件：BLE 断开 或 串口→BLE 写失败（由外层负责重连）。"""
    log("BLE 已连接，正在查找透传通道 0xFFE0/0xFFE1 …")
    services = await client.get_services()
    char = None
    for svc in services:
        if svc.uuid.lower() == BLE_SVC.lower():
            for ch in svc.characteristics:
                if ch.uuid.lower() == BLE_CHR.lower():
                    char = ch
    if char is None:
        # 兜底：任意含 write+notify 的特征
        for svc in services:
            for ch in svc.characteristics:
                props = set(ch.properties)
                if props & {"write", "write-without-response"} and "notify" in props:
                    char = ch
    if char is None:
        raise RuntimeError("未找到透传通道特征（0xFFE1）")
    props = set(char.properties)
    log("透传通道: %s（%s）" % (char.uuid, ",".join(sorted(props))))

    # BLE → 串口
    def _on_notify(_sender, data):
        try:
            on_rx(bytes(data))
        except Exception as e:
            log("串口写失败: %r" % e)
    await client.start_notify(char, _on_notify)
    log("notify 已开启 → 串口方向就绪")

    # 串口 → BLE（同一协程内单消费者，避免重复消费）
    prefer_no_rsp = "write-without-response" in props
    while True:
        try:
            data = await asyncio.wait_for(tx_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            if not client.is_connected:
                log("BLE 连接断开")
                break
            continue
        if data is None:
            break
        try:
            if prefer_no_rsp:
                await client.write_gatt_char(char, data, response=False)
            else:
                await client.write_gatt_char(char, data)
        except Exception as e:
            log("BLE 写失败: %r" % e)
            break


# ============================ 串口端 ============================
class SerialBridge:
    """串口读写线程：读→投递到 tx_queue（BLE 发送）；on_serial_rx 由 BLE 回调写回"""

    def __init__(self, port, tx_queue, loop, log):
        self.port = port
        self.tx_queue = tx_queue
        self.loop = loop
        self.log = log
        self.stop = threading.Event()
        self._thread = None
        self._write_lock = threading.Lock()
        self.ser = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="serial-bridge")
        self._thread.start()

    def write(self, data):
        with self._write_lock:
            if self.ser is not None and self.ser.is_open:
                try:
                    self.ser.write(data)
                    return True
                except Exception:
                    return False
        return False

    def _run(self):
        while not self.stop.is_set():
            try:
                ser = serial.Serial(port=self.port, baudrate=SERIAL_BAUD,
                                    bytesize=8, parity="N", stopbits=1,
                                    timeout=0.2)
                with self._write_lock:
                    self.ser = ser
                self.log("串口 %s 已打开" % self.port)
                while not self.stop.is_set():
                    n = ser.in_waiting
                    chunk = ser.read(n) if n else ser.read(1)
                    if not chunk:
                        continue
                    # 投递给 BLE 发送端（跨线程安全）
                    asyncio.run_coroutine_threadsafe(
                        self.tx_queue.put(bytes(chunk)), self.loop)
            except Exception as e:
                self.log("串口 %s 异常: %r（2 秒后重连）" % (self.port, e))
                with self._write_lock:
                    self.ser = None
            for _ in range(20):
                if self.stop.is_set():
                    break
                time.sleep(0.1)

    def close(self):
        self.stop.set()
        with self._write_lock:
            if self.ser is not None:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)


# ============================ 主流程 ============================
def _log_line(text):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), text), flush=True)


async def run_bridge(args):
    log = _log_line
    addr = args.addr
    port = args.com

    tx_queue = asyncio.Queue()     # 串口→BLE
    serial_b = SerialBridge(port, tx_queue, asyncio.get_running_loop(), log)
    serial_b.start()
    log("桥接启动：BLE %s  <->  串口 %s（给游戏用另一侧 COM）" % (addr, port))
    log("Ctrl+C 退出。模块连不上时：把蓝牙手柄板断电重上电一次。")

    rx_count = 0

    def on_ble_rx(data):
        nonlocal rx_count
        rx_count += 1
        if serial_b.write(data):
            if args.debug:
                log("BLE→COM: %s" % data.hex(" "))
        else:
            log("串口不可写（等重连）")

    while True:
        client = None
        try:
            log("扫描/连接 BLE %s …" % addr)
            client = await find_and_connect(addr)
            if client is None:
                log("15 秒内未扫到模块：请确认蓝牙手柄板上电且模块在广播"
                    "（必要时断电重上电一次），2 秒后重试")
                await asyncio.sleep(2)
                continue
            log("BLE 连接成功（is_connected=%s）" % client.is_connected)
            await ble_session(client, tx_queue, on_ble_rx, log)

            # 会话结束（断开）：交给外层重连
            rx_count = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log("BLE 会话异常: %r" % e)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
        await asyncio.sleep(2)


def main():
    ap = argparse.ArgumentParser(prog="ble_bridge.py",
                                 description="BLE(BT05) ↔ 虚拟串口 双向桥接")
    ap.add_argument("--com", metavar="COM_B", help="桥接占用的虚拟串口")
    ap.add_argument("--addr", default="00:15:83:F0:15:97", help="模块蓝牙地址")
    ap.add_argument("--debug", action="store_true", help="打印双向字节流")
    ap.add_argument("--scan", action="store_true", help="扫描 BLE 设备后退出")
    args = ap.parse_args()

    if args.scan:
        try:
            asyncio.run(cmd_scan())
        except KeyboardInterrupt:
            pass
        return 0
    if not args.com:
        ap.print_help()
        print("\n[提示] 需要 --com（com0com 虚拟串口对的一侧）与 --addr（模块地址）。")
        return 2
    try:
        asyncio.run(run_bridge(args))
    except KeyboardInterrupt:
        print("\n已退出。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

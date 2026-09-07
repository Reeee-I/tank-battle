# -*- coding: utf-8 -*-
"""fetch_bleak_deps.py —— 拉取 bleak + winrt 依赖 wheel 到本地 _bleak_deps（换机时用）

用法（在 03_测试工具 目录下执行）：
    python fetch_bleak_deps.py _bleak_deps
说明：沙箱/内网环境 pip 不可用时，直接经 PyPI JSON API 下载并解压 wheel；
     本机 Python 3.12 64 位会优先选择 cp312-win_amd64 版本。
"""
import json
import os
import re
import sys
import urllib.request
import zipfile

TARGET = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_bleak_deps")

PACKAGES = [
    "bleak",
    "winrt-runtime",
    "winrt-windows-devices-bluetooth",
    "winrt-windows-devices-bluetooth-advertisement",
    "winrt-windows-devices-bluetooth-genericattributeprofile",
    "winrt-windows-devices-enumeration",
    "winrt-windows-devices-radios",
    "winrt-windows-foundation",
    "winrt-windows-foundation-collections",
    "winrt-windows-storage-streams",
]


def pick_wheel(meta):
    ver = meta["info"]["version"]
    rel = [w for w in meta["releases"].get(ver, [])
           if w.get("packagetype") == "bdist_wheel"]

    def key(w):
        fn = w["filename"]
        m = re.search(r"cp(\d+)", fn)
        if m:
            cp = int(m.group(1))
            if cp == 312 and "win_amd64" in fn:
                return (0, 0, 0)
            if cp == 312:
                return (0, 1, 0)
            return (2, 0, cp)
        if "abi3" in fn:
            return (1, 0, 0)
        if "py3-none-any" in fn:
            return (3, 0, 0)
        return (4, 0, 0)
    rel.sort(key=key)
    if not rel:
        raise RuntimeError("no wheel for %s" % meta["info"]["name"])
    return rel[0]


def main():
    os.makedirs(TARGET, exist_ok=True)
    for name in PACKAGES:
        with urllib.request.urlopen("https://pypi.org/pypi/%s/json" % name,
                                    timeout=30) as r:
            meta = json.loads(r.read().decode())
        w = pick_wheel(meta)
        fn = w["filename"]
        dest = os.path.join(TARGET, fn)
        if not os.path.exists(dest):
            print("downloading %s ..." % fn)
            with urllib.request.urlopen(w["url"], timeout=180) as r:
                data = r.read()
            with open(dest, "wb") as f:
                f.write(data)
        with zipfile.ZipFile(dest) as z:
            z.extractall(TARGET)
        print("OK %s" % fn)
    print("done -> %s" % TARGET)


if __name__ == "__main__":
    sys.exit(main())

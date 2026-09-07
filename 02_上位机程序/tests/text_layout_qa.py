# -*- coding: utf-8 -*-
"""tests/text_layout_qa.py —— HUD 文本布局与中文字形 QA(16:9 换肤版, 可无显示器)

1) 用实际加载的中文字体度量每条 HUD/菜单/结算文本, 检查越界与两两重叠;
2) 逐字渲染常用汉字, 检查"内部着墨密度"(豆腐块) 判定乱码方块。

窗口为 1280x720(SCREEN), 逻辑战场仍为 800x600(WINDOW)。
运行: python tests/text_layout_qa.py
"""
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pygame  # noqa: E402
import assets  # noqa: E402
from game import Game  # noqa: E402

SW, SH = assets.SCREEN_W, assets.SCREEN_H
pygame.init()
pygame.display.set_mode((80, 60))
g = Game(hub=None, keyboard=False)   # 无需 screen; 复用字体加载
FAILS = []
MARGIN = 3


def rect_of(font, text, x, y, align):
    w = font.size(text)[0]
    h = font.get_height()
    if align == 'right':
        x0 = x - w
    elif align == 'center':
        x0 = x - w / 2.0
    else:
        x0 = x
    return (x0, y, x0 + w, y + h)


def overlaps(a, b):
    return not (a[2] <= b[0] + MARGIN or b[2] <= a[0] + MARGIN or
                a[3] <= b[1] + MARGIN or b[3] <= a[1] + MARGIN)


def audit(name, items):
    rects = []
    for font, text, x, y, align in items:
        r = rect_of(font, text, x, y, align)
        if r[0] < -1 or r[2] > SW + 1 or r[1] < -1 or r[3] > SH + 1:
            print('  [FAIL] %s 文本越界: %r rect=%r' % (name, text, r))
            FAILS.append(name + '-bounds')
        rects.append((text, r))
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if overlaps(rects[i][1], rects[j][1]):
                print('  [FAIL] %s 文本重叠: %r × %r' % (name, rects[i][0], rects[j][0]))
                FAILS.append(name + '-overlap')
    print('  [%s] %-12s %d 条文本无越界/无重叠'
          % ('PASS' if not any(f.startswith(name) for f in FAILS) else 'FAIL',
             name, len(items)))


def texts_running(conn1='COM3 在线', conn2='等待连接'):
    items = []
    for pid, al, x in ((1, 'left', 92), (2, 'right', SW - 92)):
        items.append((g._font(20, True), 'PLAYER %d' % pid, x, 14, al))
        items.append((g._font(14), '玩家%d' % pid, x, 40, al))
        items.append((g._font(12), conn1 if pid == 1 else conn2, x, 98, al))
    hint = ('手柄：导航键=转向/移动  K1=开火      '
            '键盘：P1 WASD+空格   P2 方向键+回车      Esc=退出')
    items.append((g._font(10), hint, SW / 2, SH - 14, 'center'))
    items.append((g._font(13), '地图·经典战场', 40, SH - 36, 'left'))
    items.append((g._font(21, True), '比分 120', 240, SH - 52, 'center'))
    items.append((g._font(21, True), '比分 80', 560, SH - 52, 'center'))
    items.append((g._font(16), '59.8 FPS', SW - 22, SH - 36, 'right'))
    return items


def texts_over():
    items = []
    cy = SH / 2
    items.append((g._font(46, True), '玩家1 获胜！', SW / 2, cy - 90, 'center'))
    items.append((g._font(24), '得分 120 : 30', SW / 2, cy - 16, 'center'))
    items.append((g._font(18), '点击鼠标 或 任一手柄按 K2 重新开始', SW / 2, cy + 26, 'center'))
    items.append((g._font(15), '按 Esc 键退出', SW / 2, cy + 62, 'center'))
    return items


def texts_menu():
    items = []
    items.append((g._font(26, True), '双人坦克对战', SW / 2, 168, 'center'))
    items.append((g._font(18), 'STC-B 学习板手柄 · 双人同屏对战', SW / 2, 206, 'center'))
    items.append((g._font(18), '玩家1（蓝）  手柄：导航键转向/移动 · K1 开火   键盘：WASD + 空格',
                  SW / 2, 254, 'center'))
    items.append((g._font(18), '玩家2（红）  手柄：导航键转向/移动 · K1 开火   键盘：方向键 + 回车',
                  SW / 2, 284, 'center'))
    items.append((g._font(14), '道具：碾过发光图标即拾取 — 加速 / 炮弹增强(命中-2血) / 血包(+1命) / 护盾(挡1发)',
                  SW / 2, 356, 'center'))
    items.append((g._font(24, True), '按任意键 或 点击鼠标 开始', SW / 2, 420, 'center'))
    items.append((g._font(15), '对局结束后：点击鼠标 或 任一手柄按 K2 再来一局', SW / 2, 464, 'center'))
    return items


print('HUD/文本布局 QA (1280x720)')
print('-' * 50)
audit('running', texts_running())
audit('running-long', texts_running(conn1='COM10 断开!', conn2='COM11 在线'))
audit('over', texts_over())
audit('menu', texts_menu())

# ---------- 字形质量(豆腐块启发式) ----------
sample = '玩家得分等待连接断开在线获胜手柄导航键移动转向开火键盘重开退出胜对战'
font = g._font(24)
suspicious = []
interior = []
for ch in sample:
    surf = font.render(ch, True, (255, 255, 255))
    w, h = surf.get_size()
    if w == 0 or h == 0:
        suspicious.append(ch)
        continue
    y0, y1 = int(h * 0.3), int(h * 0.7)
    ink = sum(1 for yy in range(y0, y1) for xx in range(w)
              if surf.get_at((xx, yy))[0] > 40)
    total = max(1, (y1 - y0) * w)
    interior.append(ink / total)
    if ink / total < 0.03:
        suspicious.append(ch)
dens = sorted(interior)
median = dens[len(dens) // 2] if dens else 0.0
print('  字形内部着墨密度中位数=%.3f（<0.03 疑为豆腐块）' % median)
if suspicious:
    print('  [FAIL] 疑为豆腐块/缺字:', ''.join(suspicious))
    FAILS.append('glyph-tofu')
else:
    print('  [PASS] %d 个汉字字形正常（无豆腐块迹象）' % len(sample))

print('-' * 50)
if FAILS:
    print('布局 QA 未通过:', FAILS)
    sys.exit(1)
print('布局/字形 QA 全部通过 ✓')

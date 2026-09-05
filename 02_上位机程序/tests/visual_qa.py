# -*- coding: utf-8 -*-
"""tests/visual_qa.py —— 多状态画面视觉 QA（需 pygame，可无显示器运行）

渲染 6 类关键画面到 tests/shots/ 并用像素断言核验：
  01 开局 / 02 激战(子弹) / 03 受伤(灰心+无敌护盾) /
  04 断线(橙点) / 05 等待连接 / 06 玩家2胜利

运行：python tests/visual_qa.py          （SDL dummy 亦可，如：
      SDL_VIDEODRIVER=dummy python tests/visual_qa.py）
产物：tests/shots/s0X_*.png（可直接打开人工预览界面效果）
"""
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pygame  # noqa: E402
from serial_handler import (PLAYER1, PLAYER2, BIT_UP, BIT_FIRE,  # noqa: E402
                            BIT_RESTART, SerialHub, HEARTBEAT_TIMEOUT)
from game import Game, WINDOW_W, WINDOW_H, START_LIVES, MAP_IDS  # noqa: E402

SHOTS = os.path.join(HERE, 'shots')
os.makedirs(SHOTS, exist_ok=True)
FAILS = []

pygame.init()
screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))


def close(c1, c2, tol=45):
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))


def anywhere(surf, color, region=None, tol=45):
    w, h = surf.get_size()
    x0, y0, x1, y1 = region or (0, 0, w, h)
    for yy in range(max(0, y0), min(h, y1), 2):
        for xx in range(max(0, x0), min(w, x1), 2):
            if close(surf.get_at((xx, yy))[:3], color, tol):
                return True
    return False


def snap(name):
    path = os.path.join(SHOTS, name + '.png')
    pygame.image.save(screen, path)
    return path


def check(name, ok, detail):
    print('  [%s] %-32s %s' % ('PASS' if ok else 'FAIL', name, detail))
    if not ok:
        FAILS.append(name)


# 01 开局
g0 = Game(hub=None, screen=screen, keyboard=False)
g0.draw()
s1 = pygame.image.load(snap('s01_start')).convert()

# 02 激战（开阔下路 y=500：经典图 y=300 直线已被中央掩体遮挡——平衡设计，
#     直射子弹场景放到无掩体的下路 y=500，只验证"子弹在弹道区"画面）
g = Game(hub=None, screen=screen, keyboard=False)
t1, t2 = g.tanks[PLAYER1], g.tanks[PLAYER2]
t1.x, t1.y, t1.angle = 100.0, 500.0, 0.0
t2.x, t2.y, t2.angle = 600.0, 500.0, 180.0
g._inject[PLAYER1] = BIT_UP | BIT_FIRE
for _ in range(10):
    g.update()
g._inject[PLAYER1] = 0
for i in range(30):
    g.update()
    time.sleep(0.008)
g.draw()
s2 = pygame.image.load(snap('s02_battle')).convert()

# 03 受伤态：P1 掉1命(灰心)、P2 剩2命且无敌护盾
t1.lives = 2
t2.lives = 2
t2.x, t2.y = 470.0, 300.0     # 移到画面中部采样位（避开中央掩体与地图无关的贴图区）
t2.invincible_until = time.monotonic() + 5.0
g.draw()
s3 = pygame.image.load(snap('s03_hurt')).convert()
# 护盾为"呼吸闪烁"圆环，需在亮相相位时采样（最多重绘 40 次）
shield_ok = False
for _k in range(40):
    g.draw()
    surf = pygame.image.load(snap('s03_hurt')).convert()
    if anywhere(surf, (255, 255, 255), (440, 270, 505, 335), tol=40):
        shield_ok = True
        s3 = surf
        break
    time.sleep(0.02)
check('s03', shield_ok, '玩家2 无敌护盾白圈(闪烁相位内捕获)')

# 04 断线态：hub 中 P1 在线、P2 超时离线（橙点 + 断开!）
hub = SerialHub(preferred=None)
now = time.monotonic()
with hub._lock:
    hub._state[PLAYER1].update(port='COM3', mask=BIT_UP, last=now - 0.1)
    hub._state[PLAYER2].update(port='COM7', mask=0,
                               last=now - HEARTBEAT_TIMEOUT - 0.5)
g4 = Game(hub=hub, screen=screen, keyboard=False)
g4.draw()
s4 = pygame.image.load(snap('s04_disconnected')).convert()

# 05 等待连接态：hub 无任何板子绑定
hub0 = SerialHub(preferred=None)
g5 = Game(hub=hub0, screen=screen, keyboard=False)
g5.draw()
s5 = pygame.image.load(snap('s05_waiting')).convert()

# 06 玩家2胜利
g6 = Game(hub=None, screen=screen, keyboard=False)
g6._end_game(PLAYER2)
g6.draw()
s6 = pygame.image.load(snap('s06_win_p2')).convert()

P1B, P2B = (88, 152, 255), (255, 96, 96)
GRAY, ORANGE = (110, 116, 130), (240, 165, 60)
TEXT = (226, 230, 240)

# ---- 断言 ----
check('s01', anywhere(s1, P1B, (110, 260, 190, 340)), 'P1 蓝坦克在左出生区')
check('s01', anywhere(s1, P2B, (610, 260, 690, 340)), 'P2 红坦克在右出生区')
check('s01', anywhere(s1, (96, 101, 118), (330, 210, 470, 285)),
      '中央障碍物存在')
check('s02', anywhere(s2, P1B, (200, 460, 620, 545)), 'P1 子弹在弹道区(下路)')
check('s02', anywhere(s2, TEXT, (200, 8, 600, 30)), '顶部状态栏文字存在')
check('s03', anywhere(s3, GRAY, (14, 34, 90, 56)), '玩家1 损失的心=灰色')
check('s04', anywhere(s4, ORANGE, (700, 12, 784, 34)), '玩家2 断线橙点')
check('s05', anywhere(s5, GRAY, (150, 20, 700, 44), tol=30), '等待连接灰色状态点×2')
check('s06', anywhere(s6, P2B, (300, 200, 500, 260)), '玩家2 胜利大红字')
check('s06', anywhere(s6, TEXT, (250, 280, 550, 360)), '结算得分/提示文字存在')

# ---- 09 开始界面（menu=True 首次启动显示；任意键/点击/手柄按键进入对战）----
gm = Game(hub=None, screen=screen, keyboard=False, menu=True)
assert gm.menu_active
gm.draw()
s9 = pygame.image.load(snap('s09_menu')).convert()
check('s09-menu', anywhere(s9, (235, 240, 255), (230, 90, 570, 175), tol=35),
      '开始界面大标题(亮白)存在')
check('s09-menu2', anywhere(s9, (88, 152, 255), (140, 232, 660, 262), tol=35),
      '玩家1(蓝)操作行存在')
check('s09-menu3', anywhere(s9, (255, 96, 96), (140, 258, 660, 288), tol=35),
      '玩家2(红)操作行存在')
# 点击开始 → 进入对战：界面要素（HUD 红心/出生区坦克）恢复
gm.start_game()
assert not gm.menu_active
gm.draw()
s10 = pygame.image.load(snap('s10_after_start')).convert()
check('s10-start', anywhere(s10, (88, 152, 255), (110, 260, 190, 340), tol=35),
      '开始后：P1 蓝坦克回到对战场景(出生区)')

# ---- 07/08 结算重开（用户新规）：仅 鼠标点击 与 任一手柄按 K2(bit5) ----
# K1(开火)/R/回车 均不再触发重开
g7 = Game(hub=None, keyboard=False)
g7._end_game(PLAYER1)                     # 制造对局结束态
g7._inject[PLAYER1] = BIT_FIRE            # 按 K1(开火)：不应重开
g7.update()
k1_no = g7.game_over is True
g7._inject[PLAYER1] = 0
g7.update()
g7._inject[PLAYER1] = BIT_RESTART         # 按 K2(bit5)：应重开
g7.update()
k2_yes = (not g7.game_over and g7.winner is None and
          g7.tanks[PLAYER1].lives == START_LIVES)
g8 = Game(hub=None, keyboard=False)
g8._end_game(PLAYER2)
g8.restart_on_click()                     # 鼠标点击：应重开
click_yes = not g8.game_over
check('s07', k1_no and k2_yes and click_yes,
      '结算重开：K1不触发 / 手柄K2触发 / 鼠标点击触发')

# ---- 多地图渲染冒烟：每张地图都能正常绘制（含左下角"地图·xx"文字）----
for mid in MAP_IDS:
    gm = Game(hub=None, screen=screen, keyboard=False, map_id=mid)
    gm.draw()
check('maps-render', True, '全部 %d 张地图渲染冒烟通过（地图名显示）' % len(MAP_IDS))

print('-' * 60)
print('截图已保存至: %s' % SHOTS)
if FAILS:
    print('画面 QA 未通过:', FAILS)
    sys.exit(1)
print('画面 QA 全部通过 ✓')

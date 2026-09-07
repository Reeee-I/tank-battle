# -*- coding: utf-8 -*-
"""tests/visual_qa.py —— 多状态画面视觉 QA(需 pygame, 可无显示器, 4:3 换肤版)

渲染关键画面到 tests/shots/ 并用色相/像素断言核验换肤后的关键元素:
  起始 / 激战(子弹) / 受伤(灰心+无敌护盾) / 断线(橙点) / 等待连接 / 玩家2胜利
  及 开始菜单 / 多地图渲染冒烟 / 结算重开规则。
窗口=逻辑战场 800x600(1:1), 边框拉伸, 背景封面裁剪。
运行: python tests/visual_qa.py
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
import assets  # noqa: E402
from bullet import Bullet  # noqa: E402
from serial_handler import (PLAYER1, PLAYER2, BIT_UP, BIT_FIRE,  # noqa: E402
                            BIT_RESTART, SerialHub, HEARTBEAT_TIMEOUT)
from game import Game, WINDOW_W, WINDOW_H, START_LIVES, MAP_IDS  # noqa: E402

SHOTS = os.path.join(HERE, 'shots')
os.makedirs(SHOTS, exist_ok=True)
FAILS = []

pygame.init()
screen = pygame.display.set_mode((assets.SCREEN_W, assets.SCREEN_H))
# 窗口=逻辑战场 1:1, 无需坐标换算


def _classify(p):
    r, g, b = p[0] / 255.0, p[1] / 255.0, p[2] / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    sat8 = (mx - mn) * 255
    mx8 = mx * 255
    if sat8 < 30:
        if mx8 > 210:
            return 'white'
        if mx8 >= 45:
            return 'gray'
        return 'dark'
    if mx8 < 60:
        return 'dark'
    if mx == mn:
        h = 0.0
    elif mx == r:
        h = 60.0 * ((g - b) / (mx - mn)) % 360
    elif mx == g:
        h = 60.0 * ((b - r) / (mx - mn) + 2)
    else:
        h = 60.0 * ((r - g) / (mx - mn) + 4)
    h = (h + 360.0) % 360.0
    if h < 15 or h >= 345:
        return 'red'
    if h < 40:
        return 'orange'
    if h < 70:
        return 'yellow'
    if h < 170:
        return 'green'
    if h < 260:
        return 'blue'
    return 'purple'


def any_class(surf, klass, x0, y0, x1, y1, step=3):
    for yy in range(max(0, int(y0)), int(y1), step):
        for xx in range(max(0, int(x0)), int(x1), step):
            if xx < 0 or yy < 0 or xx >= surf.get_width() or yy >= surf.get_height():
                continue
            if _classify(surf.get_at((xx, yy))) == klass:
                return True
    return False


def snap(name):
    path = os.path.join(SHOTS, name + '.png')
    pygame.image.save(screen, path)
    return path


def check(name, ok, detail):
    print('  [%s] %-30s %s' % ('PASS' if ok else 'FAIL', name, detail))
    if not ok:
        FAILS.append(name)


# ---- 01 起点 ----
g0 = Game(hub=None, screen=screen, keyboard=False, map_id='classic')
g0.draw()
s1 = pygame.image.load(snap('s01_start')).convert()

# ---- 02 激战: 指定坦克位置 + 已知子弹 ----
g = Game(hub=None, screen=screen, keyboard=False, map_id='classic')
t1, t2 = g.tanks[PLAYER1], g.tanks[PLAYER2]
t1.x, t1.y, t1.angle = 100.0, 500.0, 0.0
t2.x, t2.y, t2.angle = 600.0, 500.0, 180.0
g.bullets[PLAYER1] = [Bullet(400.0, 500.0, 0.0, PLAYER1)]
g.bullets[PLAYER2] = [Bullet(300.0, 300.0, 180.0, PLAYER2)]
g._inject[PLAYER1] = BIT_UP | BIT_FIRE
for _ in range(6):
    g.update()
g._inject[PLAYER1] = 0
g.draw()
s2 = pygame.image.load(snap('s02_battle')).convert()

# ---- 03 受伤态 ----
t1.lives = 2
t2.x, t2.y = 470.0, 300.0
t2.invincible_until = time.monotonic() + 5.0
g.draw()
s3 = pygame.image.load(snap('s03_hurt')).convert()
shield_ok = False
for _k in range(40):
    g.draw()
    surf = pygame.image.load(snap('s03_hurt')).convert()
    if any_class(surf, 'white', 440, 260, 510, 340, step=2):
        shield_ok = True
        s3 = surf
        break
    time.sleep(0.02)
check('s03', shield_ok, '玩家2 无敌护盾白圈(闪烁相位内捕获)')

# ---- 04 断线态 ----
hub = SerialHub(preferred=None)
now = time.monotonic()
with hub._lock:
    hub._state[PLAYER1].update(port='COM3', mask=BIT_UP, last=now - 0.1)
    hub._state[PLAYER2].update(port='COM7', mask=0,
                               last=now - HEARTBEAT_TIMEOUT - 0.5)
g4 = Game(hub=hub, screen=screen, keyboard=False, map_id='classic')
g4.draw()
s4 = pygame.image.load(snap('s04_disconnected')).convert()

# ---- 05 等待连接态 ----
g5 = Game(hub=SerialHub(preferred=None), screen=screen, keyboard=False, map_id='classic')
g5.draw()
s5 = pygame.image.load(snap('s05_waiting')).convert()

# ---- 06 玩家2胜利 ----
g6 = Game(hub=None, screen=screen, keyboard=False, map_id='classic')
g6._end_game(PLAYER2)
g6.draw()
s6 = pygame.image.load(snap('s06_win_p2')).convert()

# ---- 09 开始菜单 ----
gm = Game(hub=None, screen=screen, keyboard=False, menu=True, map_id='classic')
assert gm.menu_active
gm.draw()
s9 = pygame.image.load(snap('s09_menu')).convert()

# ---- 断言(800x600 1:1) ----
check('s01', any_class(s1, 'blue', 110, 260, 190, 340), 'P1 蓝色坦克在左出生区')
check('s01b', any_class(s1, 'red', 610, 260, 690, 340), 'P2 红色坦克在右出生区')
check('s01c', any_class(s1, 'gray', 330, 210, 470, 285), '中央障碍物(灰块)存在')
check('s02', any_class(s2, 'blue', 340, 450, 470, 545), 'P1 蓝色彗尾弹在弹道区')
check('s03h', any_class(s2, 'gray', 140, 66, 190, 100), '玩家1 受损(灰)心形存在')
check('s04', any_class(s4, 'orange', 592, 14, 640, 42), '玩家2 断线橙点')
check('s05', any_class(s5, 'gray', 88, 94, 190, 116), '等待连接: 玩家血条下方 COM 说明(灰)')
check('s06', any_class(s6, 'red', 300, 190, 500, 240), '玩家2 胜利大红字')
check('s09-menu', any_class(s9, 'orange', 300, 60, 500, 140), '开始界面 TANK BATTLE 金色标题')

# 点击开始 → 进入对战
gm.start_game()
assert not gm.menu_active
gm.draw()
s10 = pygame.image.load(snap('s10_after_start')).convert()
check('s10-start', any_class(s10, 'blue', 110, 260, 190, 340),
      '开始后: P1 蓝坦克回到出生区')

# ---- K1不重开 / K2重开 / 鼠标重开 ----
g7 = Game(hub=None, keyboard=False)
g7._end_game(PLAYER1)
g7._inject[PLAYER1] = BIT_FIRE
g7.update()
k1_no = g7.game_over is True
g7._inject[PLAYER1] = 0
g7.update()
g7._inject[PLAYER1] = BIT_RESTART
g7.update()
k2_yes = (not g7.game_over and g7.winner is None and
          g7.tanks[PLAYER1].lives == START_LIVES)
g8 = Game(hub=None, keyboard=False)
g8._end_game(PLAYER2)
g8.restart_on_click()
click_yes = not g8.game_over
check('s07', k1_no and k2_yes and click_yes,
      '结算重开: K1不触发 / 手柄K2触发 / 鼠标点击触发')

# ---- 多地图渲染冒烟 ----
for mid in MAP_IDS:
    gm = Game(hub=None, screen=screen, keyboard=False, map_id=mid)
    gm.draw()
check('maps-render', True, '全部 %d 张地图渲染冒烟通过' % len(MAP_IDS))

print('-' * 60)
print('截图已保存至: %s' % SHOTS)
if FAILS:
    print('画面 QA 未通过:', FAILS)
    sys.exit(1)
print('画面 QA 全部通过 ✓')

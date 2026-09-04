# -*- coding: utf-8 -*-
"""tests/test_maps.py —— 多地图设计约束自测（无头，无需 pygame / 硬件）

运行：python tests/test_maps.py

覆盖（对应 game.py MAPS 注释中的平衡设计约束，改地图/新增地图必须保持）：
  1) 地图注册表结构合法：id 唯一、每张图有显示名与障碍列表、默认图在池内；
  2) 左右镜像对称（关于 x=400）→ 两玩家地形完全公平；
  3) 出生点 (150,300)/(650,300) 周边 ±55 留空 → 开局/重生不被卡死；
  4) 出生→出生 水平直线（y=300，子弹半径 5）被中央掩体拦截 → 刚开局不能隔空直射；
  5) 全图连通（AABB 精确 BFS）：任一空地都可由玩家1 出生点到达，无死角死区；
  6) 规模：每图 4~12 个障碍、总占地面积 3%~14%（不过空/不过挤）；
  7) 行为回归：地图随机模式与固定模式的选择语义；
  8) 平衡行为回归：开局从出生点正前方开火，子弹必须被掩体吸收、不得打到对方
     （旧版"开局直接对射"的回归保护）。
全部通过打印 PASS 汇总并以 0 退出；失败抛出 AssertionError。
"""

import sys
from collections import deque

sys.path.insert(0, '.')          # 使 `import serial_handler` 等可用
sys.path.insert(0, 'PC')         # 兼容在 PC/ 目录与项目根目录两种运行方式

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from serial_handler import PLAYER1, PLAYER2, BIT_FIRE          # noqa: E402
from obstacle import Obstacle                                  # noqa: E402
from game import (Game, MAPS, MAP_IDS, DEFAULT_MAP_ID,          # noqa: E402
                  SPAWNS, WINDOW_W, WINDOW_H, START_LIVES,
                  BULLET_RADIUS)

TANK_HALF = 15.0
SPAWN_MARGIN = 55.0
BFS_STEP = 8


def bounds(block):
    cx, cy, w, h = block
    return (cx - w / 2.0, cy - h / 2.0, w, h)


def rects_overlap(ax, ay, aw, ah, bx, by, bw, bh):
    return (ax < bx + bw) and (bx < ax + aw) and (ay < by + bh) and (by < ay + ah)


def check_symmetry(layout):
    """关于 x=400 镜像对称：每个障碍都能在右侧找到一一对应的镜像"""
    mine = sorted((float(cx), float(cy), float(w), float(h)) for (cx, cy, w, h) in layout)
    mir = sorted((WINDOW_W - cx, cy, w, h) for (cx, cy, w, h) in mine)
    return all(abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6 and
               abs(a[2] - b[2]) < 1e-6 and abs(a[3] - b[3]) < 1e-6
               for a, b in zip(mine, mir))


def check_spawn_clear(layout):
    for (sx, sy) in [SPAWNS[PLAYER1][:2], SPAWNS[PLAYER2][:2]]:
        for bl in layout:
            l, t, w, h = bounds(bl)
            if rects_overlap(sx - SPAWN_MARGIN, sy - SPAWN_MARGIN,
                             2 * SPAWN_MARGIN, 2 * SPAWN_MARGIN, l, t, w, h):
                return False
    return True


def ray_hits_obstacle(layout, x0, x1, y=300.0):
    """y=300 水平直线从 x0 到 x1 是否被某障碍拦截（子弹半径 BULLET_RADIUS）"""
    n = int(abs(x1 - x0))
    step = 1.0 if x1 > x0 else -1.0
    for i in range(1, n + 1):
        px = x0 + i * step
        for bl in layout:
            l, t, w, h = bounds(bl)
            nx = max(l, min(px, l + w))
            ny = max(t, min(y, t + h))
            if (px - nx) ** 2 + (y - ny) ** 2 <= BULLET_RADIUS ** 2:
                return True
    return False


def check_spawn_los_blocked(layout):
    """出生点炮口到对方出生点（车头前）的直线必须被掩体挡住"""
    p1x = SPAWNS[PLAYER1][0] + 23.0          # 玩家1 炮口（朝右）
    p2x = SPAWNS[PLAYER2][0] - 23.0          # 玩家2 炮口（朝左，即 P1 弹道终点前）
    return (ray_hits_obstacle(layout, p1x, p2x) and
            ray_hits_obstacle(layout, p2x, p1x))


def check_full_connectivity(layout):
    """AABB 精确可达性：坦克中心落在 BFS 格点上，与障碍/边界均不交即为空地；
    从玩家1 出生点出发须能到达所有空地（即全图无死区、出生点不被封死）。"""
    gw, gh = WINDOW_W // BFS_STEP, WINDOW_H // BFS_STEP

    def blocked(cx, cy):
        px, py = cx * BFS_STEP, cy * BFS_STEP
        if (px - TANK_HALF < 0 or px + TANK_HALF > WINDOW_W or
                py - TANK_HALF < 0 or py + TANK_HALF > WINDOW_H):
            return True
        for bl in layout:
            l, t, w, h = bounds(bl)
            if rects_overlap(px - TANK_HALF, py - TANK_HALF,
                             2 * TANK_HALF, 2 * TANK_HALF, l, t, w, h):
                return True
        return False

    start = (int(SPAWNS[PLAYER1][0]) // BFS_STEP,
             int(SPAWNS[PLAYER1][1]) // BFS_STEP)
    if blocked(*start):
        return False, '玩家1 出生点不可站'

    total_free = sum(1 for cy in range(gh) for cx in range(gw)
                     if not blocked(cx, cy))
    seen = {start}
    dq = deque([start])
    while dq:
        cx, cy = dq.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < gw and 0 <= ny < gh):
                continue
            if (nx, ny) in seen or blocked(nx, ny):
                continue
            seen.add((nx, ny))
            dq.append((nx, ny))
    if len(seen) != total_free:
        return False, '存在 %d 块不可达空地' % (total_free - len(seen))
    return True, '全图连通'


def test_registry():
    """地图注册表结构合法"""
    assert MAP_IDS == list(MAPS), 'MAP_IDS 必须等于 MAPS 的全部键'
    assert len(MAPS) >= 5, '应提供至少 5 张地图（当前 %d 张）' % len(MAPS)
    assert DEFAULT_MAP_ID in MAPS, '默认地图必须在池内'
    assert MAP_IDS[0] == 'classic', '经典图保留为默认'
    names = set()
    for mid, (mname, layout) in MAPS.items():
        assert isinstance(mname, str) and mname, mid
        assert mname not in names, '地图显示名重复'
        names.add(mname)
        assert isinstance(layout, list) and layout, mid
        for bl in layout:
            assert len(bl) == 4, mid
            cx, cy, w, h = bl
            assert w > 0 and h > 0 and 0 <= cx <= WINDOW_W, bl
    print('  [PASS] 地图注册表：%d 张图（默认=%s）' % (len(MAPS), DEFAULT_MAP_ID))


def test_every_map_constraints():
    """每张图：对称 / 出生留空 / 开局直线遮挡 / 全图连通 / 规模合理"""
    for mid in MAP_IDS:
        mname, layout = MAPS[mid]
        assert check_symmetry(layout), '[%s] 非 x=400 镜像对称' % mid
        assert check_spawn_clear(layout), '[%s] 出生点周边±%.0f 有障碍' % (mid, SPAWN_MARGIN)
        assert check_spawn_los_blocked(layout), '[%s] 开局直线弹道未被遮挡' % mid
        ok, note = check_full_connectivity(layout)
        assert ok, '[%s] %s' % (mid, note)
        area = sum(w * h for (_, _, w, h) in layout)
        frac = area / (WINDOW_W * WINDOW_H)
        assert 4 <= len(layout) <= 12, '[%s] 障碍数量 %d 超限' % (mid, len(layout))
        assert 0.03 <= frac <= 0.14, '[%s] 面积占比 %.1f%% 超限' % (mid, frac * 100)
    print('  [PASS] %d 张图：镜像对称/出生留空/开局直线遮挡/全图连通/规模合理' % len(MAPS))


def test_map_selection_semantics():
    """地图选择语义：默认图确定；固定图重开不变；随机图每次开局都可能换图"""
    g = Game(hub=None, keyboard=False)
    assert g.map_id == DEFAULT_MAP_ID and g.map_name == MAPS[DEFAULT_MAP_ID][0]
    assert g.map_id in MAPS and len(g.obstacles) == len(MAPS[g.map_id][1])

    # 固定地图：reset 后仍同一张
    g = Game(hub=None, keyboard=False, map_id='maze')
    for _ in range(3):
        g.reset()
        assert g.map_id == 'maze'
        assert g.map_name == MAPS['maze'][0]

    # 随机地图：每次 reset 抽到的都是合法图，且多次抽取应出现多种地图
    g = Game(hub=None, keyboard=False, map_id='random')
    seen = set()
    for _ in range(150):
        g.reset()
        assert g.map_id in MAPS
        assert [Obstacle(*t).rect() for t in MAPS[g.map_id][1]] == \
               [ob.rect() for ob in g.obstacles], '障碍未按所选地图重建'
        seen.add(g.map_id)
    assert len(seen) >= 2, '150 次随机只抽到 %r（随机异常）' % sorted(seen)

    # 未知地图 id 报错
    try:
        Game(hub=None, keyboard=False, map_id='no_such_map')
        raise AssertionError('未知地图 id 未抛错')
    except ValueError:
        pass
    print('  [PASS] 选择语义：默认经典 / 固定不变 / 随机每局 / 非法 id 报错')


def test_no_direct_fire_at_round_start():
    """平衡回归：开局双方在出生点，正前方开火必须被掩体吸收，
    绝不能直接命中对方（旧版"开局即对射"的反例保护）"""
    for mid in MAP_IDS:
        for shooter, foe in ((PLAYER1, PLAYER2), (PLAYER2, PLAYER1)):
            g = Game(hub=None, keyboard=False, map_id=mid)
            g._inject[shooter] = BIT_FIRE
            g.update()                       # 发射（出生炮口处不允许卡弹）
            assert len(g.bullets[shooter]) == 1, \
                '[%s] P%d 出生点开火应能发射' % (mid, shooter)
            g._inject[shooter] = 0
            for _ in range(240):             # 足够飞到对方出生点
                g.update()
            assert g.tanks[foe].lives == START_LIVES, \
                '[%s] P%d 出生直射打中了对方（地图未遮挡开局直线）' % (mid, shooter)
            assert g.tanks[shooter].score == 0
            assert not g.bullets[shooter], '[%s] 子弹应被掩体吸收' % mid
    print('  [PASS] 平衡回归：%d 张图 × 双向，出生直射均被掩体吸收' % len(MAPS))


def main():
    print('多地图设计约束自测')
    print('-' * 50)
    tests = [test_registry, test_every_map_constraints,
             test_map_selection_semantics, test_no_direct_fire_at_round_start]
    for t in tests:
        t()
    print('-' * 50)
    print('全部 %d 项测试通过 ✓' % len(tests))
    return 0


if __name__ == '__main__':
    sys.exit(main())

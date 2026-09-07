# -*- coding: utf-8 -*-
"""assets.py —— 素材加载与缓存模块(UI 换肤版)

职责:
  1. 从同目录 素材/ 加载坦克/心形/边框/地面/标题/障碍贴图;
  2. 提供懒加载 + 缓存 + convert_alpha();
  3. 坦克: 绕"车体质心"旋转(非图中心), 按 (玩家, 角度) 缓存旋转图;
  4. 地面: 从地板素材裁出 800x600 逻辑战场区域;
  5. 边框: 缩放到 1280x720 窗口(16:9);
  6. **缺素材/加载失败一律返回 None**, 调用方回退到原有矢量画法(不影响运行)。

素材均只读; 尺寸/轴心依据实图像素测量(见 预览示意/实施说明)。
"""
import io
import math
import os

import pygame

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(HERE, '素材')

# 逻辑战场(保持不变)与窗口(4:3)尺寸 —— 窗口=逻辑战场 1:1
LOGIC_W, LOGIC_H = 800, 600
SCREEN_W, SCREEN_H = 800, 600

# 坦克: 整车视觉长度(逻辑 px, 加大更显眼; 车体碰撞仍为 TANK_SIZE=30)
TANK_LEN = 56.0

_cards = {}   # 预留
_cache = {}


def _load(fn):
    """加载 PNG(兼容无/有扩展名); 失败返回 None"""
    if fn in _cache:
        return _cache[fn]
    path = os.path.join(ASSET_DIR, fn)
    if not os.path.exists(path):
        # 尝试补 .png 扩展
        if not path.lower().endswith('.png'):
            p2 = path + '.png'
            if os.path.exists(p2):
                path = p2
            else:
                _cache[fn] = None
                return None
        else:
            _cache[fn] = None
            return None
    try:
        with open(path, 'rb') as f:
            sf = pygame.image.load(io.BytesIO(f.read()))
        if sf.get_flags() & pygame.SRCALPHA:
            sf = sf.convert_alpha()
        else:
            sf = sf.convert()
        _cache[fn] = sf
    except Exception:
        _cache[fn] = None
    return _cache[fn]


def _bbox(sf, thr=30):
    w, h = sf.get_size()
    bb = [w, h, -1, -1]
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if sf.get_at((x, y)).a >= thr:
                bb[0] = min(bb[0], x)
                bb[1] = min(bb[1], y)
                bb[2] = max(bb[2], x)
                bb[3] = max(bb[3], y)
    return bb


# ------------------------------------------------------------------ 坦克
# 实测(像素): 蓝坦克朝右, 炮管右伸; 红坦克朝左, 炮管左伸。轴心=车体质心。
_TANK_SPEC = {
    1: dict(fn='玩家1坦克素材', bbox=None, pivot=(484.9, 409.2),
            orig=(116, 110), base_heading=0.0),
    2: dict(fn='玩家二坦克素材', bbox=None, pivot=(865.0, 437.9),
            orig=(64, 74), base_heading=180.0),
}
_tank_base = {}      # player -> (pivot_centered, scale)
_tank_rot = {}       # (player, int_angle) -> rotated surface


def _build_tank_base(pid):
    spec = _TANK_SPEC[pid]
    sf = _load(spec['fn'])
    if sf is None:
        return None
    bb = spec['bbox'] or _bbox(sf)
    crop = sf.subsurface((bb[0], bb[1], bb[2] - bb[0] + 1, bb[3] - bb[1] + 1))
    cw, ch = crop.get_size()
    scale = TANK_LEN / cw
    # 以 2x 逻辑分辨率做基图(旋转时更平滑)
    k = 2
    sc = pygame.transform.smoothscale(crop, (max(1, int(cw * scale * k)),
                                             max(1, int(ch * scale * k))))
    sw, sh = sc.get_size()
    px = spec['pivot'][0] * scale * k
    py = spec['pivot'][1] * scale * k
    side = int(2 * max(px, sw - px, py, sh - py)) + 2
    pad = pygame.Surface((side, side), pygame.SRCALPHA)
    pad.blit(sc, (int(side / 2 - px), int(side / 2 - py)))
    return pad, side, spec['base_heading']


def get_tank(pid, angle):
    """返回绕车体质心旋转好、最终尺寸的贴图(玩家 pid, 角度 angle)"""
    key = (pid, int(angle) % 360)
    if key in _tank_rot:
        return _tank_rot[key]
    base = _tank_base.get(pid)
    if base is None:
        base = _build_tank_base(pid)
        _tank_base[pid] = base
    if base is None:
        return None
    pad, side, bh = base
    # 游戏角度: 0=右, 顺时针为正; pygame rotozoom 正=逆时针 → 取负
    rot = -(angle - bh)
    surf = pygame.transform.rotozoom(pad, rot, 1.0 / 2.0)   # 2x -> 1x
    _tank_rot[key] = surf
    return surf


# ------------------------------------------------------------------ 心形
def _heart(fn):
    sf = _load(fn)
    if sf is None:
        return None
    bb = _bbox(sf, 40)
    crop = sf.subsurface((bb[0], bb[1], bb[2] - bb[0] + 1, bb[3] - bb[1] + 1))
    # 心形高约 27px(适中, 不抢眼)
    return pygame.transform.smoothscale(crop, (int(crop.get_width() * 0.06),
                                               int(crop.get_height() * 0.06)))


_heart_c = {}


def get_heart(state):
    """state: 'p1' / 'p2' / 'empty'"""
    if state in _heart_c:
        return _heart_c[state]
    fn = {'p1': '蓝方血量素材.png', 'p2': '红方血量素材.png',
          'empty': '空血素材.png'}[state]
    h = _heart(fn)
    if h is not None and h.get_width() > 0:
        _heart_c[state] = h
        return h
    _heart_c[state] = None
    return None


# ------------------------------------------------------------------ 地面 / 边框 / 标题 / 障碍
_floor_c = None


def get_floor():
    """返回逻辑战场地面(800x600)"""
    global _floor_c
    if _floor_c is not None:
        return _floor_c
    sf = _load('地板背景素材图.png')
    if sf is None:
        _floor_c = None
        return None
    fw, fh = sf.get_size()
    fx = max(0, (fw - LOGIC_W) // 2)
    fy = max(0, (fh - LOGIC_H) // 2)
    region = sf.subsurface((fx, fy, min(LOGIC_W, fw), min(LOGIC_H, fh)))
    _floor_c = pygame.transform.smoothscale(region, (LOGIC_W, LOGIC_H)).convert()
    return _floor_c


_floor_bg_c = None


def get_floor_bg():
    """返回整窗地面(封面裁剪, 不拉伸) —— 窗口=逻辑战场 1:1"""
    global _floor_bg_c
    if _floor_bg_c is not None:
        return _floor_bg_c
    f = get_floor()
    _floor_bg_c = f
    return f


_frame_c = None


def get_frame():
    """返回整幅边框贴图(SCREEN 16:9)"""
    global _frame_c
    if _frame_c is not None:
        return _frame_c
    sf = _load('边框素材图')
    if sf is None:
        _frame_c = None
        return None
    _frame_c = pygame.transform.smoothscale(sf, (SCREEN_W, SCREEN_H)).convert_alpha()
    return _frame_c


_title_c = {}


def get_title(h):
    """返回标题贴图(TANK BATTLE)指定高度"""
    if h in _title_c:
        return _title_c[h]
    sf = _load('Tank Battle 素材.png')
    if sf is None:
        _title_c[h] = None
        return None
    w, _ = sf.get_size()
    t = pygame.transform.smoothscale(sf, (int(w * h / sf.get_height()), h)).convert_alpha()
    _title_c[h] = t
    return t


_ob_c = None


def get_obstacle():
    """返回整块障碍物贴图(含金属面+底部警示条), 供等比缩放、不裁切放置"""
    global _ob_c
    if _ob_c is not None:
        return _ob_c
    sf = _load('障碍物素材')
    if sf is None:
        _ob_c = None
        return None
    bb = _bbox(sf, 30)
    x0, y0, x1, y1 = bb
    block = sf.subsurface((x0, y0, (x1 - x0) + 1, (y1 - y0) + 1)).convert_alpha()
    _ob_c = block
    return block

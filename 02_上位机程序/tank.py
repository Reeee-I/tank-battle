# -*- coding: utf-8 -*-
"""tank.py —— 坦克类（纯几何/运动逻辑，不依赖 pygame，便于无头测试）

运动规则（与板端协议位含义一致）：
    bit0 左   → 逆时针旋转（每次 ROTATE_SPEED 度）
    bit1 右   → 顺时针旋转
    bit2 上   → 沿炮管朝向 前进
    bit3 下   → 沿炮管朝向 后退
    bit4 开火 → 由 Game 处理（此处不关心）

物理：
  - 坦克为 30x30 正方形（AABB 碰撞），中心点 (x, y) 精确位置；
  - 逐轴移动 + 碰撞回退：先试 X 轴、再试 Y 轴，实现"贴墙滑动"效果；
  - 角度制：0° 朝右(+x)，顺时针为正（与屏幕坐标 y 向下一致）。
"""

import math

from serial_handler import BIT_LEFT, BIT_RIGHT, BIT_UP, BIT_DOWN
from obstacle import rects_overlap

TANK_SIZE = 30.0          # 坦克车身边长（像素）


class Tank(object):
    def __init__(self, player_id, x, y, angle=0.0,
                 lives=3, move_speed=3.0, rotate_speed=2.0):
        self.player_id = player_id          # 1 或 2
        self.x = float(x)
        self.y = float(y)
        self.angle = float(angle) % 360.0   # 炮管/车头朝向（度）
        self.lives = lives
        self.score = 0
        self.move_speed = move_speed        # 像素/帧（每帧由 Game 按加速道具状态刷新）
        self.rotate_speed = rotate_speed    # 度/帧
        self.base_move_speed = float(move_speed)   # 无加速道具时的基准速度
        # 出生点（被击中后重生位置与朝向）
        self.spawn = (float(x), float(y), float(angle) % 360.0)
        # 以下时间戳由 Game 统一用 time.monotonic() 维护
        self.invincible_until = 0.0         # 重生无敌结束时刻
        self.cooldown_until = 0.0           # 开火冷却结束时刻
        # 道具增益状态（0.0 = 未激活；结束时刻由 Game 统一维护）
        self.speed_until = 0.0              # 加速道具结束时刻
        self.cannon_until = 0.0             # 炮弹增强结束时刻
        self.shield_until = 0.0             # 道具护盾结束时刻（抵挡 1 发后立即清零）

    # ------------------------------ 几何 ------------------------------
    @property
    def half(self):
        """半边长（用于碰撞与边界判断）"""
        return TANK_SIZE / 2.0

    def rect(self):
        """返回 (x, y, w, h)（AABB 左上角 + 宽高）"""
        h = self.half
        return (self.x - h, self.y - h, TANK_SIZE, TANK_SIZE)

    def hit_rect(self, rx, ry, rw, rh):
        """是否与矩形 (rx,ry,rw,rh) 相交（与 Obstacle.hit_rect 同接口，
        使"障碍物 + 对方坦克"可统一作为阻挡物传给 update）"""
        h = self.half
        return rects_overlap(rx, ry, rw, rh,
                             self.x - h, self.y - h, TANK_SIZE, TANK_SIZE)

    def respawn(self):
        """回到出生点（位置 + 朝向），不重置生命/得分"""
        self.x, self.y, self.angle = self.spawn

    def clear_buffs(self):
        """清除全部道具增益（阵亡重生时调用——防滚雪球的平衡规则）"""
        self.speed_until = 0.0
        self.cannon_until = 0.0
        self.shield_until = 0.0

    # ------------------------------ 控制 ------------------------------
    def update(self, mask, blockers, arena_w, arena_h):
        """按按键掩码执行一次转向与移动（每帧调用一次）

        blockers：阻挡物列表（障碍物 + 对方坦克，均需提供 hit_rect 接口）
        """
        # 1) 转向
        if mask & BIT_LEFT:
            self.angle = (self.angle - self.rotate_speed) % 360.0
        if mask & BIT_RIGHT:
            self.angle = (self.angle + self.rotate_speed) % 360.0
        # 2) 前后移动（沿炮管朝向）
        rad = math.radians(self.angle)
        if mask & BIT_UP:
            self._try_move(math.cos(rad) * self.move_speed,
                           math.sin(rad) * self.move_speed,
                           blockers, arena_w, arena_h)
        if mask & BIT_DOWN:
            self._try_move(-math.cos(rad) * self.move_speed,
                           -math.sin(rad) * self.move_speed,
                           blockers, arena_w, arena_h)

    # ------------------------------ 内部 ------------------------------
    def _try_move(self, dx, dy, blockers, arena_w, arena_h):
        """逐轴移动：X 被挡则只动 Y，反之亦然 → 贴墙可滑动"""
        if self._place_free(self.x + dx, self.y, blockers, arena_w, arena_h):
            self.x += dx
        if self._place_free(self.x, self.y + dy, blockers, arena_w, arena_h):
            self.y += dy

    def _place_free(self, x, y, blockers, arena_w, arena_h):
        """(x,y) 处是否可停留：不出边界且不与任何阻挡物相交"""
        h = self.half
        if x - h < 0.0 or x + h > arena_w or y - h < 0.0 or y + h > arena_h:
            return False
        for bl in blockers:
            if bl.hit_rect(x - h, y - h, TANK_SIZE, TANK_SIZE):
                return False
        return True

    def muzzle_point(self):
        """炮口位置：车头前方（用于生成子弹，避免子弹出生在车内）"""
        rad = math.radians(self.angle)
        return (self.x + math.cos(rad) * (self.half + 8.0),
                self.y + math.sin(rad) * (self.half + 8.0))

    def __repr__(self):
        return 'Tank%d(pos=(%g,%g) angle=%g lives=%d score=%d)' % (
            self.player_id, self.x, self.y, self.angle,
            self.lives, self.score)

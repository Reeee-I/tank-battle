# -*- coding: utf-8 -*-
"""bullet.py —— 子弹类（纯几何/运动逻辑，不依赖 pygame，便于无头测试）

规则：
  - 圆形，默认半径 5 像素，默认速度 5 像素/帧（60FPS 下约 300px/s）；
  - 沿发射瞬间坦克的炮管朝向直线飞行；
  - 越出战场边界即消失（alive=False）；
  - damage 为该发子弹命中扣血数：炮弹增强道具生效期间发射为 2（开火瞬间快照，
    与弹体视觉一致）；普通为 1；
  - 与障碍物/坦克的碰撞由 Game 判定（本类只提供几何查询方法）。
"""

import math

BULLET_RADIUS = 5.0
BULLET_SPEED = 5.0


class Bullet(object):
    def __init__(self, x, y, angle_deg, owner,
                 radius=BULLET_RADIUS, speed=BULLET_SPEED, damage=1):
        self.x = float(x)
        self.y = float(y)
        self.radius = float(radius)
        self.speed = float(speed)
        self.damage = int(damage)               # 命中扣血（炮弹增强=2，普通=1）
        self.owner = owner                      # 发射者玩家号：1/2
        rad = math.radians(angle_deg)
        self.vx = math.cos(rad) * self.speed    # 水平速度（像素/帧）
        self.vy = math.sin(rad) * self.speed    # 垂直速度
        self.alive = True

    def update(self, arena_w, arena_h):
        """每帧移动一次；完全离开战场后标记死亡"""
        self.x += self.vx
        self.y += self.vy
        margin = self.radius * 2.0
        if (self.x < -margin or self.x > arena_w + margin or
                self.y < -margin or self.y > arena_h + margin):
            self.alive = False

    def hits_rect(self, rx, ry, rw, rh):
        """子弹圆是否与矩形 (rx,ry,rw,rh) 相交（圆↔矩形最近点法）"""
        nx = max(rx, min(self.x, rx + rw))
        ny = max(ry, min(self.y, ry + rh))
        dx = self.x - nx
        dy = self.y - ny
        return (dx * dx + dy * dy) <= (self.radius * self.radius)

    def __repr__(self):
        return 'Bullet(owner=%d pos=(%g,%g))' % (self.owner, self.x, self.y)

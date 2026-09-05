# -*- coding: utf-8 -*-
"""obstacle.py —— 障碍物类（纯几何逻辑，不依赖 pygame，便于无头测试）

障碍物为矩形（AABB），提供：
  - rects_overlap(...)  : 两矩形是否相交（坦克移动碰撞用）
  - Obstacle.hit_circle(): 圆是否碰到本障碍物（子弹碰撞用）
"""


def rects_overlap(ax, ay, aw, ah, bx, by, bw, bh):
    """判断两个轴对齐矩形是否相交（含边缘相切视为不相交）"""
    return (ax < bx + bw) and (bx < ax + aw) and (ay < by + bh) and (by < ay + ah)


class Obstacle(object):
    """固定障碍物：由 中心点(cx, cy) + 宽高(w, h) 定义"""

    def __init__(self, cx, cy, w, h):
        self.cx = float(cx)
        self.cy = float(cy)
        self.w = float(w)
        self.h = float(h)
        self.x = self.cx - self.w / 2.0      # 左上角 x
        self.y = self.cy - self.h / 2.0      # 左上角 y

    # -- 几何查询 --
    def rect(self):
        """返回 (x, y, w, h) 便于与坦克矩形做相交测试"""
        return (self.x, self.y, self.w, self.h)

    def hit_rect(self, rx, ry, rw, rh):
        """是否与矩形 (rx, ry, rw, rh) 相交"""
        return rects_overlap(rx, ry, rw, rh,
                             self.x, self.y, self.w, self.h)

    def hit_circle(self, px, py, r):
        """是否与圆心 (px,py)、半径 r 的圆相交（圆↔矩形最近点法）"""
        nx = max(self.x, min(px, self.x + self.w))
        ny = max(self.y, min(py, self.y + self.h))
        dx = px - nx
        dy = py - ny
        return (dx * dx + dy * dy) <= (r * r)

    def __repr__(self):
        return 'Obstacle(center=(%g,%g) size=%gx%g)' % (
            self.cx, self.cy, self.w, self.h)

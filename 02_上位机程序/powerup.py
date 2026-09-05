# -*- coding: utf-8 -*-
"""powerup.py —— 道具类（纯几何/逻辑，不依赖 pygame，便于无头测试）

道具种类（效果数值与生成节奏常量集中在 game.py，便于统一调平衡）：
  - KIND_SPEED   'speed'   加速     持续 POWERUP_SPEED_DURATION 秒，移动速度 ×1.5
  - KIND_CANNON  'cannon'  炮弹增强 持续 POWERUP_CANNON_DURATION 秒，命中扣 2 血
  - KIND_HEALTH  'health'  血包     立即 +1 命（上限 START_LIVES；满血拾取无效并消耗）
  - KIND_SHIELD  'shield'  护盾     持续 POWERUP_SHIELD_DURATION 秒 或 抵挡 1 发，
                                    （先到先失效；挡下的一击不掉血、不重生、不清其他增益）

拾取/寿命规则（平衡设计）：
  - 道具刷在场地上，坦克碾过即拾取（圆形拾取半径 POWERUP_RADIUS 与坦克 AABB 相交）；
  - 自生成起 POWERUP_LIFETIME 秒无人拾取即自动消失（防场上长期堆积/死道具）；
  - 本类仅保存种类/位置/出生时刻并提供几何查询；生成时机与拾取结算由 Game 负责。
"""

KIND_SPEED = 'speed'
KIND_CANNON = 'cannon'
KIND_HEALTH = 'health'
KIND_SHIELD = 'shield'

# 场上可随机出现的道具池（等概率 25%）
KINDS = [KIND_SPEED, KIND_CANNON, KIND_HEALTH, KIND_SHIELD]

# 道具全名（README/图例/结算等处用）
KIND_NAMES = {
    KIND_SPEED: '加速',
    KIND_CANNON: '炮弹增强',
    KIND_HEALTH: '血包',
    KIND_SHIELD: '护盾',
}
# HUD 增益栏短名（省宽度：加速/炮强/护盾）
BUFF_SHORT_NAMES = {
    KIND_SPEED: '加速',
    KIND_CANNON: '炮强',
    KIND_SHIELD: '护盾',
}

POWERUP_RADIUS = 14.0          # 拾取半径（道具视觉直径 ≈28px）


class PowerUp(object):
    """场上的一件道具：种类 + 位置 + 出生时刻"""

    def __init__(self, x, y, kind, born_at):
        self.x = float(x)
        self.y = float(y)
        if kind not in KIND_NAMES:
            raise ValueError('未知道具种类 %r，可选：%s'
                             % (kind, '、'.join(KINDS)))
        self.kind = kind
        self.born_at = float(born_at)

    def hits_rect(self, rx, ry, rw, rh):
        """道具圆是否与矩形 (rx,ry,rw,rh) 相交（圆↔矩形最近点法，与 Bullet 同款）"""
        nx = max(rx, min(self.x, rx + rw))
        ny = max(ry, min(self.y, ry + rh))
        dx = self.x - nx
        dy = self.y - ny
        return (dx * dx + dy * dy) <= (POWERUP_RADIUS * POWERUP_RADIUS)

    def __repr__(self):
        return 'PowerUp(%s pos=(%g,%g))' % (self.kind, self.x, self.y)

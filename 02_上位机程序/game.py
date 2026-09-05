# -*- coding: utf-8 -*-
"""game.py —— 游戏主逻辑与渲染（双人坦克对战）

职责：
  1. 维护对战状态：坦克/子弹/障碍物/生命/得分/胜负；
  2. 每帧从 SerialHub（或键盘）读取两玩家按键掩码并驱动坦克；
  3. 子弹飞行、碰撞检测（坦克 / 障碍物 / 边界 / 无敌护盾 / 道具护盾）；
  4. 道具系统：随机生成（避障碍/坦克、限量、超时消失）与碾过拾取结算；
  5. 生命归零判定胜负（重开方式：鼠标点击 / 任一手柄按 K2）；
  6. 集中完成全部渲染（背景/障碍/道具/坦克/子弹/HUD/胜负画面）。

设计说明：
  - 本模块顶层不 import pygame，纯逻辑 update() 可在无 pygame 环境跑
    （无头测试）；渲染所需 pygame 在 run()/draw() 内局部导入；
  - 规则常量集中在下方（转向手感/道具平衡等只需改这里）；
  - 时间统一走 time.monotonic()（可注入假时钟做确定性测试）。
"""

import random
import time

from serial_handler import (BIT_LEFT, BIT_RIGHT, BIT_UP, BIT_DOWN, BIT_FIRE,
                            BIT_RESTART, PLAYER1, PLAYER2)
from tank import Tank, TANK_SIZE
from bullet import Bullet
from obstacle import Obstacle
from powerup import (PowerUp, KIND_SPEED, KIND_CANNON, KIND_HEALTH,
                     KIND_SHIELD, KINDS, BUFF_SHORT_NAMES)

# ============================== 规则常量 ==============================
WINDOW_W, WINDOW_H = 800, 600      # 战场窗口尺寸
FPS = 60                           # 目标帧率

START_LIVES = 3                    # 初始生命
MOVE_SPEED = 3.0                   # 移动速度：像素/帧（60FPS 下约 180px/s）
ROTATE_SPEED = 2.0                 # 转向速度：度/帧（约 120°/s，手感流畅档）
                                   # ※ 如需严格按题面"每个按键事件转5°"，
                                   #   可改为在收到按键指令时一次性转 5°，这里保留常量便于调参
BULLET_SPEED = 5.0                 # 子弹速度：像素/帧（约 300px/s）
BULLET_RADIUS = 5.0                # 子弹半径
MAX_BULLETS = 3                    # 每辆坦克最多同时在场的子弹数
FIRE_COOLDOWN = 0.2                # 开火冷却：秒（200ms）
INVINCIBLE_TIME = 1.0              # 被击中重生后的无敌时长：秒
SCORE_PER_HIT = 10                 # 每命中对方一次的得分

# ============================== 道具规则（平衡见注释） ==============================
# 平衡总纲：道具只提供"临时/一次性"优势，且：
#   - 中频少量（v2.5 起适度下调频率）：首件 6s 后出现、之后每 10~15s 随机一件、
#     场上同时最多 2 件（道具给对局加变数，但不喧宾夺主；生成率约比初版低 1/4）；
#   - 每件 10s 无人拾取自动消失（场上不堆积、角落不留死道具）；
#   - 阵亡重生清除全部增益（被打回去就是代价，防滚雪球一路滚到底）；
#   - 护盾挡下一发即失效、且有时限（不能长期龟缩免疫）；
#   - 炮弹增强单发伤害大（-2）→ 持续时间短（6s），且伤害在开火瞬间快照
#     （有爆发窗口，可被护盾/走位/对枪反制）；
#   - 血包 +1 且上限 3 → 落后方唯一的翻盘资源；满血拾取无效并消耗
#     （对领先方是纯负收益，天然把血包留给更需要的一方，形成反滚雪球）；
#   - 同类道具重复拾取不叠加、刷新为满时长。
POWERUP_SPAWN_FIRST = 6.0          # 开局后多久出现第一件道具：秒
POWERUP_SPAWN_MIN = 10.0           # 之后每件的随机间隔下界：秒
POWERUP_SPAWN_MAX = 15.0           # 之后每件的随机间隔上界：秒
POWERUP_MAX_ON_FIELD = 2           # 场上同时最多道具数
POWERUP_LIFETIME = 10.0            # 一件道具无人拾取的生存时长：秒
POWERUP_SPEED_DURATION = 6.0       # 加速持续：秒
POWERUP_SPEED_MULT = 1.5           # 加速移动倍率
POWERUP_CANNON_DURATION = 6.0      # 炮弹增强持续：秒
POWERUP_CANNON_DAMAGE = 2          # 炮弹增强：每次命中扣血
POWERUP_HEALTH_GAIN = 1            # 血包：回复生命数（上限 START_LIVES）
POWERUP_SHIELD_DURATION = 8.0      # 护盾持续：秒（或抵挡 1 发，先到先失效）
TOAST_DURATION = 1.2                # 拾取/回血浮动提示的显示时长：秒

# 出生点：(x, y, 初始朝向°) —— 玩家1 左朝右、玩家2 右朝左，相向而对
SPAWNS = {
    PLAYER1: (150, 300, 0.0),
    PLAYER2: (650, 300, 180.0),
}

# ============================== 地图 ==============================
# 每张地图定义为：(显示名, 障碍列表)，障碍为 (中心x, 中心y, 宽, 高)。
# 平衡设计约束（tests/test_maps.py 自动校验，改图后必须保持）：
#   1) 全部关于战场中线 x=400 左右对称 → 两玩家地形完全公平；
#   2) 两出生点 (150,300)/(650,300) 周边留空 → 开局/重生不被卡死；
#   3) 出生→出生 的水平直线（y≈300）被中央掩体遮挡 → 刚开局无法隔空直射，
#      必须先走位绕开掩体再交火（修复旧版"开局即对射"的不平衡）；
#   4) 全图连通（坦克可到达任意空地，无死角死区）。
MAPS = {
    # 经典战场：原中央横墙 + 新增中央道口掩体（挡开局直射）+ 两侧立柱
    'classic': ('经典战场', [
        (400, 245, 110, 60),    # 中央上横墙
        (400, 300, 100, 50),    # 中央道口掩体
        (295, 435, 70, 90),     # 左侧立柱
        (505, 435, 70, 90),     # 右侧立柱
    ]),
    # 十字要塞：横竖主梁叠出实心十字，四角留台
    'cross': ('十字要塞', [
        (400, 300, 360, 44),    # 横主梁
        (400, 300, 44, 240),    # 竖主梁
        (280, 80, 60, 50),      # 左上台
        (520, 80, 60, 50),      # 右上台
        (280, 520, 60, 50),     # 左下台
        (520, 520, 60, 50),     # 右下台
    ]),
    # 中央堡垒：大堡居中，上下矮墙 + 四角块
    'fortress': ('中央堡垒', [
        (400, 300, 160, 120),   # 中央堡垒
        (400, 70, 240, 26),     # 顶部矮墙
        (400, 530, 240, 26),    # 底部矮墙
        (160, 160, 70, 70),     # 左上角块
        (640, 160, 70, 70),     # 右上角块
        (160, 460, 70, 70),     # 左下角块
        (640, 460, 70, 70),     # 右下角块
    ]),
    # 回廊：上下两排错落横墙 + 中央掩体，走位空间大
    'maze': ('回廊', [
        (400, 300, 80, 44),     # 中央道口掩体
        (150, 130, 150, 40),    # 左上横墙
        (650, 130, 150, 40),    # 右上横墙
        (400, 130, 90, 40),     # 中央上横墙
        (260, 220, 80, 40),     # 左内上墙
        (540, 220, 80, 40),     # 右内上墙
        (150, 470, 150, 40),    # 左下横墙
        (650, 470, 150, 40),    # 右下横墙
        (400, 470, 90, 40),     # 中央下横墙
        (260, 380, 80, 40),     # 左内下墙
        (540, 380, 80, 40),     # 右内下墙
    ]),
    # 街巷：两侧巷房 + 中央掩体，利于近身周旋
    'street': ('街巷', [
        (400, 300, 70, 50),     # 中央道口掩体
        (120, 170, 80, 110),    # 左巷房1
        (120, 430, 80, 100),    # 左巷房2
        (680, 170, 80, 110),    # 右巷房1
        (680, 430, 80, 100),    # 右巷房2
        (290, 140, 56, 56),     # 左内上小屋
        (510, 140, 56, 56),     # 右内上小屋
        (290, 470, 56, 56),     # 左内下小屋
        (510, 470, 56, 56),     # 右内下小屋
    ]),
    # 石柱阵：中央屏障 + 上下错落立柱，考验预瞄与走位
    'columns': ('石柱阵', [
        (400, 300, 120, 50),    # 中央屏障
        (160, 130, 50, 50),     # 上排外柱
        (640, 130, 50, 50),     # 上排外柱
        (300, 130, 50, 50),     # 上排内柱
        (500, 130, 50, 50),     # 上排内柱
        (160, 470, 50, 50),     # 下排外柱
        (640, 470, 50, 50),     # 下排外柱
        (300, 470, 50, 50),     # 下排内柱
        (500, 470, 50, 50),     # 下排内柱
        (240, 300, 44, 44),     # 屏障左侧柱
        (560, 300, 44, 44),     # 屏障右侧柱
    ]),
}

# 默认地图：Game(map_id=None) 时使用，保证无参构造/测试确定可复现
DEFAULT_MAP_ID = 'classic'
# 全部地图 id（随机池）
MAP_IDS = list(MAPS)

# 键盘调试模式按键（板子未接时也能双人玩）：
#   玩家1：W 前进 / S 后退 / A 左转 / D 右转 / 空格 开火
#   玩家2：↑ 前进 / ↓ 后退 / ← 左转 / → 右转 / 回车 开火
KB_MAP = {
    PLAYER1: dict(up=ord('w'), down=ord('s'), left=ord('a'), right=ord('d')),
    PLAYER2: dict(up=273, down=274, left=276, right=275),  # pygame K_UP=273 ...
}
KB_FIRE = {PLAYER1: 32, PLAYER2: 13}       # 空格(32) / 回车(13)


class Game(object):
    """游戏主对象：构造后可只调 update()（无头）；run() 才需要 pygame"""

    def __init__(self, hub=None, screen=None, keyboard=False, debug=False,
                 map_id=None, menu=False):
        self.hub = hub                  # SerialHub（可为 None → 仅键盘）
        self.screen = screen            # pygame 窗口（None → 无头）
        self.keyboard = keyboard        # 是否启用键盘调试控制
        self.debug = debug              # 是否打印按键/重开诊断（main.py --debug）
        # 开始界面：menu=True 时程序启动先显示开始界面，按任意键/点击鼠标/
        # 任一手柄任意键进入对战；对局结束（K2/点击）重开不经过开始界面。
        # 默认 False 保持既有无头测试/QA 直接可玩。
        self.menu_active = bool(menu)
        # 地图选择：map_id='random' → 每局随机抽图（main.py 默认）；
        #           map_id=None → 默认地图 DEFAULT_MAP_ID（无参构造/测试确定可复现）；
        #           传具体地图 id（如 'classic'）→ 固定该图。
        if map_id == 'random':
            self._random_map = True
            self._fixed_map_id = None
        else:
            if map_id is None:
                map_id = DEFAULT_MAP_ID
            if map_id not in MAPS:
                raise ValueError('未知地图 id=%r，可选：%s'
                                 % (map_id, '、'.join(MAPS)))
            self._random_map = False
            self._fixed_map_id = map_id
        self.map_id = None              # 当前局地图 id（reset() 时确定）
        self.map_name = ''              # 当前局地图显示名
        self._now_fn = time.monotonic   # 可注入假时钟
        self._inject = {}               # {玩家号: 掩码} 测试注入，优先级最高
        self._fonts = {}                # 字体缓存
        self._bullet_cache = {}         # 子弹发光表面缓存
        self._powerup_cache = {}        # 道具发光表面缓存
        self._fps = 0.0
        self.reset()
        # 非"开始界面"直开模式（menu=False，测试/直连用）：开局即把满血
        # 下行给已绑定的手柄板（真机入口 main.py 用 menu=True，改为
        # 进入对战时在 start_game() 下发，开始界面上 LED 保持全灭）。
        if not self.menu_active:
            self._push_all_hp()

    # ------------------------------ LED 血量下行 ------------------------------
    def _push_hp(self, pid):
        """把玩家 pid 所控坦克的当前血量(0~3)下行给该玩家手柄板。

        板端 LED 语义（v2.8）：满血3=6灯(L0~L5)、2=4灯、1=2灯、0 死亡=全灭；
        身份由数码管 1/2 承担，LED 专用于血量。无串口（键盘/无头）为空操作。
        """
        if self.hub is None:
            return
        hp = int(max(0, min(START_LIVES, self.tanks[pid].lives)))
        self.hub.set_hp(pid, hp)

    def _push_all_hp(self):
        """两玩家血量一起下行（开局/重开时把血条复位为满血）"""
        for pid in (PLAYER1, PLAYER2):
            self._push_hp(pid)

    def _choose_map_id(self):
        """按地图模式挑出本局地图 id"""
        if self._random_map:
            return random.choice(MAP_IDS)
        return self._fixed_map_id

    # ------------------------------ 状态 ------------------------------
    def reset(self):
        """重新开始一局（鼠标点击 / 任一手柄 K2 / 测试调用）。

        随机地图模式下每次开局（含重开）都会重新抽一张地图；
        固定地图模式（构造时传具体 map_id）下重开保持同一张地图。
        """
        self.map_id = self._choose_map_id()
        self.map_name = MAPS[self.map_id][0]
        self.obstacles = [Obstacle(*t) for t in MAPS[self.map_id][1]]
        self.tanks = {
            PLAYER1: Tank(PLAYER1, *SPAWNS[PLAYER1], lives=START_LIVES,
                          move_speed=MOVE_SPEED, rotate_speed=ROTATE_SPEED),
            PLAYER2: Tank(PLAYER2, *SPAWNS[PLAYER2], lives=START_LIVES,
                          move_speed=MOVE_SPEED, rotate_speed=ROTATE_SPEED),
        }
        self.bullets = {PLAYER1: [], PLAYER2: []}
        self.game_over = False
        self.winner = None
        self._prev = {PLAYER1: 0, PLAYER2: 0}   # 上一帧掩码（开火边沿检测）
        # 道具状态：场上道具清空，计时器从开局时刻 + 首件延迟开始
        self.powerups = []
        self.next_powerup_at = self._now_fn() + POWERUP_SPAWN_FIRST
        # 浮动提示（拾取回血等），随 reset 清空
        self.toasts = []

    def set_clock(self, fn):
        """注入时间源（测试用）"""
        self._now_fn = fn

    # ------------------------------ 输入 ------------------------------
    def _read_mask(self, pid):
        """读取某玩家的最终按键掩码：测试注入 > 串口 > 键盘"""
        if pid in self._inject:
            return self._inject[pid]
        mask = 0
        if self.hub is not None:
            m, online = self.hub.get_control(pid)
            if online:
                mask |= m
        if self.keyboard:
            mask |= self._keyboard_mask(pid)
        return mask

    def _keyboard_mask(self, pid):
        """把键盘按键翻译成协议掩码（与板端语义一致）"""
        import pygame
        keys = pygame.key.get_pressed()
        kb = KB_MAP[pid]
        mask = 0
        if keys[kb['left']]:
            mask |= BIT_LEFT
        if keys[kb['right']]:
            mask |= BIT_RIGHT
        if keys[kb['up']]:
            mask |= BIT_UP
        if keys[kb['down']]:
            mask |= BIT_DOWN
        if keys[KB_FIRE[pid]]:
            mask |= BIT_FIRE
        return mask

    # ------------------------------ 主更新 ------------------------------
    def update(self):
        """推进一帧逻辑（固定步长，与渲染帧率一致）"""
        if self.menu_active:
            # 开始界面：只等"开始"输入，场上完全冻结
            self._check_menu_start()
            return
        if self.game_over:
            # 结算画面：允许"任一手柄按 K2"直接重开一局
            self._check_restart_from_boards()
            return
        now = self._now_fn()

        # 1) 两辆坦克：转向/移动 + 开火边沿（每帧按加速道具状态刷新实际速度）
        for pid in (PLAYER1, PLAYER2):
            tank = self.tanks[pid]
            # 移动阻挡物 = 障碍物 + 对方坦克（坦克之间不可互相穿过）
            other = self.tanks[PLAYER1 if pid == PLAYER2 else PLAYER2]
            blockers = self.obstacles + [other]
            mask = self._read_mask(pid)
            fired = bool(mask & BIT_FIRE) and not (self._prev[pid] & BIT_FIRE)
            # 加速道具生效期 → 实际速度 ×1.5；buff 到期自动回落基准速度
            tank.move_speed = tank.base_move_speed * (
                POWERUP_SPEED_MULT if now < tank.speed_until else 1.0)
            tank.update(mask, blockers, WINDOW_W, WINDOW_H)
            if fired:
                self._try_fire(pid, tank, now)
            self._prev[pid] = mask

        # 2) 子弹飞行与碰撞
        self._move_bullets(now)
        if self.game_over:
            return                     # 本帧已有人阵亡：道具系统随画面冻结

        # 3) 道具系统：到期清理 → 碾过拾取 → 定时生成
        self._update_powerups(now)

        # 4) 浮动提示（血包回血等）：过期清理
        self.toasts = [t for t in self.toasts if now - t['born'] < TOAST_DURATION]

    # ------------------------------ 开始界面 ------------------------------
    def start_game(self):
        """从开始界面进入对战（仅首次启动时显示开始界面；对局结束 K2/点击
        重开不经过这里，直接开下一局）。进入对战同时把满血下行给两块
        手柄板（开始界面期间 LED 保持全灭，身份看数码管）。"""
        if self.menu_active:
            if self.debug:
                print('[开始] 收到开始输入，进入对战')
            self.menu_active = False
            self._push_all_hp()         # 开局：手柄 LED 血条复位为满血

    def _check_menu_start(self):
        """开始界面：任一手柄/键盘有任何按键输入 → 开始对战"""
        for pid in (PLAYER1, PLAYER2):
            if self._read_mask(pid):
                self.start_game()
                return

    def _check_restart_from_boards(self):
        """结算画面：任一手柄按 K2(bit5, 单发) → 重开一局（板子无需键盘）。

        键盘没有 K2；游戏中的空格/回车仅作开火，不再触发重开
        （重开方式收敛为：鼠标点击 / 任一手柄 K2——用户需求）。
        """
        for pid in (PLAYER1, PLAYER2):
            mask = self._read_mask(pid)
            restart_req = bool(mask & BIT_RESTART) and \
                not (self._prev[pid] & BIT_RESTART)
            self._prev[pid] = mask
            if restart_req:
                if self.debug:
                    print('[重开] 玩家%d 手柄 K2 触发重新开始' % pid)
                self.reset()
                self._push_all_hp()     # 重开：两块手柄 LED 血条复位为满血
                return

    # ------------------------------ 开火/碰撞 ------------------------------
    def _try_fire(self, pid, tank, now):
        """尝试发射一枚子弹（冷却 / 数量上限 / 炮口不能嵌在障碍里）"""
        if now < tank.cooldown_until:
            return
        if len(self.bullets[pid]) >= MAX_BULLETS:
            return
        mx, my = tank.muzzle_point()
        # 炮口必须留在场内（含弹体半径余量），贴边朝外时无法开火，避免无效弹
        if not (BULLET_RADIUS <= mx <= WINDOW_W - BULLET_RADIUS and
                BULLET_RADIUS <= my <= WINDOW_H - BULLET_RADIUS):
            return
        for ob in self.obstacles:
            if ob.hit_circle(mx, my, BULLET_RADIUS + 1.0):
                return                       # 炮口顶着障碍：不开火
        # 伤害在开火瞬间快照：炮弹增强生效期发射的子弹每发 -2 血（视觉同步发光弹）
        dmg = POWERUP_CANNON_DAMAGE if now < tank.cannon_until else 1
        self.bullets[pid].append(
            Bullet(mx, my, tank.angle, pid, radius=BULLET_RADIUS,
                   speed=BULLET_SPEED, damage=dmg))
        tank.cooldown_until = now + FIRE_COOLDOWN

    def _move_bullets(self, now):
        """子弹移动 + 碰撞：障碍消失 / 命中敌人扣血重生 / 越界移除。

        规则边界：若本帧某发子弹造成致命一击（game_over=True），
        立即停止本帧后续一切命中结算并丢弃残弹（防重复扣分/幽灵子弹）；
        同归于尽时按处理顺序先手(P1)获胜——两侧子弹先各自结算仍会有
        先后判定，规则取"先完成致命一击的一方"胜出。
        """
        for pid in (PLAYER1, PLAYER2):
            if self.game_over:
                break                      # 已有人阵亡：清场冻结
            enemy = self.tanks[PLAYER1 if pid == PLAYER2 else PLAYER2]
            rest = []
            for b in self.bullets[pid]:
                if self.game_over:
                    break                  # 致命一击发生：忽略本帧后续子弹
                if not b.alive:
                    continue
                b.update(WINDOW_W, WINDOW_H)
                if not b.alive:
                    continue               # 越界消失
                # 撞障碍：子弹消失
                blocked = False
                for ob in self.obstacles:
                    if ob.hit_circle(b.x, b.y, b.radius):
                        blocked = True
                        break
                if blocked:
                    continue
                # 命中敌方坦克：重生无敌 / 道具护盾 吸收子弹不掉血；
                # 否则按子弹携带伤害结算（炮弹增强 -2 / 普通 -1）
                if b.hits_rect(*enemy.rect()):
                    if now < enemy.invincible_until:
                        pass                       # 重生无敌：吸收（不扣血不破盾）
                    elif now < enemy.shield_until:
                        # 道具护盾：完整挡下这一发 → 护盾立即消失，
                        # 不掉血、不重生、不清其他增益（平衡规则）
                        enemy.shield_until = 0.0
                    else:
                        self._on_hit(pid, enemy, now, damage=b.damage)
                    if self.game_over:
                        break              # 本帧终结：其余残弹一并清场
                    continue               # 子弹消失（命中 / 护盾 / 无敌吸收）
                rest.append(b)
            if not self.game_over:
                self.bullets[pid] = rest   # game_over 时列表已被 _end_game 清空

    def _on_hit(self, shooter_pid, victim, now, damage=1):
        """子弹命中结算：得分 +10；按伤害扣血 → 重生无敌 + 清增益 或 游戏结束"""
        victim.lives -= damage
        self.tanks[shooter_pid].score += SCORE_PER_HIT
        if victim.lives <= 0:
            victim.lives = 0
            self._end_game(shooter_pid)
        else:
            victim.respawn()
            victim.invincible_until = now + INVINCIBLE_TIME
            victim.clear_buffs()       # 阵亡重生清除全部增益/护盾（防滚雪球）
        self._push_hp(victim.player_id)  # 血量变化 → 手柄 LED 血条联动（0 即全灭）

    def _end_game(self, winner_pid):
        """一方生命归零：游戏结束，清除残留子弹冻结画面"""
        self.game_over = True
        self.winner = winner_pid
        self.bullets[PLAYER1] = []
        self.bullets[PLAYER2] = []

    # ------------------------------ 道具系统 ------------------------------
    def _update_powerups(self, now):
        """推进道具：①到期清理 → ②碾过拾取 → ③定时生成（每帧一次）"""
        # ① 超时无人拾取的道具消失（POWERUP_LIFETIME）
        for p in self.powerups[:]:
            if now - p.born_at >= POWERUP_LIFETIME:
                self.powerups.remove(p)

        # ② 拾取：坦克矩形与道具圆相交即"碾过拾取"
        #    （两人同帧碾上同一件 → 按玩家号顺序先到先得，规则确定）
        for p in self.powerups[:]:
            for pid in (PLAYER1, PLAYER2):
                if p.hits_rect(*self.tanks[pid].rect()):
                    self._apply_powerup(pid, p, now)
                    self.powerups.remove(p)
                    break

        # ③ 定时生成：到点且场上未满 → 刷 1 件；满场/无空地 → 短暂重试
        if now >= self.next_powerup_at:
            if len(self.powerups) < POWERUP_MAX_ON_FIELD and \
                    self._spawn_powerup(now):
                self.next_powerup_at = now + random.uniform(
                    POWERUP_SPAWN_MIN, POWERUP_SPAWN_MAX)
            else:
                self.next_powerup_at = now + 0.5   # 场上已满或无空地：稍后重试

    def _spawn_powerup(self, now):
        """在场地上随机找一块"坦克可停靠"的空地刷一件道具；找不到返回 False"""
        kind = random.choice(KINDS)          # 四种等概率
        for _ in range(60):                  # 多次随机尝试找合法位置
            x = random.uniform(TANK_SIZE, WINDOW_W - TANK_SIZE)
            y = random.uniform(TANK_SIZE, WINDOW_H - TANK_SIZE)
            if self._spot_clear(x, y):
                self.powerups.append(PowerUp(x, y, kind, now))
                return True
        return False

    def _spot_clear(self, x, y):
        """道具中心 (x,y) 处是否可刷：整辆坦克能停在此处（不出界、不压障碍/
        其他道具/坦克）→ 道具必可被碾到拾取"""
        h = TANK_SIZE / 2.0
        rx, ry = x - h, y - h
        if rx < 0.0 or ry < 0.0 or rx + TANK_SIZE > WINDOW_W or \
                ry + TANK_SIZE > WINDOW_H:
            return False
        for ob in self.obstacles:
            if ob.hit_rect(rx, ry, TANK_SIZE, TANK_SIZE):
                return False
        for p in self.powerups:
            if p.hits_rect(rx, ry, TANK_SIZE, TANK_SIZE):
                return False
        for tank in self.tanks.values():
            if tank.hit_rect(rx, ry, TANK_SIZE, TANK_SIZE):
                return False
        return True

    def _apply_powerup(self, pid, pu, now):
        """拾取结算：按种类即时生效（同类重复拾取不叠加、刷新满时长）"""
        t = self.tanks[pid]
        if pu.kind == KIND_SPEED:
            t.speed_until = now + POWERUP_SPEED_DURATION
        elif pu.kind == KIND_CANNON:
            t.cannon_until = now + POWERUP_CANNON_DURATION
        elif pu.kind == KIND_HEALTH:
            if t.lives < START_LIVES:
                t.lives = min(START_LIVES, t.lives + POWERUP_HEALTH_GAIN)
                # 回血成功：坦克头顶绿色"生命 +1"上浮提示 + 手柄 LED 血条回亮
                self.toasts.append({'pid': pid, 'born': now, 'text': '生命 +1',
                                    'color': self.GREEN})
                self._push_hp(pid)
            else:
                # 满血拾取：无效果但道具仍消耗（防囤积）→ 灰字提示原因
                self.toasts.append({'pid': pid, 'born': now, 'text': '生命已满',
                                    'color': self.TEXT_DIM})
        elif pu.kind == KIND_SHIELD:
            t.shield_until = now + POWERUP_SHIELD_DURATION

    # ============================== 渲染 ==============================
    # 颜色
    BG_COLOR = (24, 26, 34)
    GRID_COLOR = (35, 39, 52)
    WALL_COLOR = (110, 118, 138)
    OB_COLOR = (96, 101, 118)
    OB_EDGE = (58, 62, 76)
    OB_HI = (150, 156, 172)
    TEXT_COLOR = (226, 230, 240)
    TEXT_DIM = (150, 156, 172)
    GREEN = (80, 200, 120)
    ORANGE = (240, 165, 60)
    GRAY = (110, 116, 130)
    P1_COLOR = (88, 152, 255)          # 玩家1：蓝
    P2_COLOR = (255, 96, 96)           # 玩家2：红
    GUN_COLOR = (70, 76, 90)

    # 道具配色（四种一眼可分）与图标
    POWERUP_COLORS = {
        KIND_SPEED: (250, 205, 60),    # 加速：黄（闪电/双箭头）
        KIND_CANNON: (255, 120, 60),   # 炮弹增强：橙红（弹头+准星）
        KIND_HEALTH: (80, 200, 120),   # 血包：绿（白十字）
        KIND_SHIELD: (110, 200, 255),  # 护盾：青（盾形）
    }

    def run(self):
        """主循环入口（main.py 调用）：事件 / 更新 / 渲染 @60FPS"""
        import pygame
        clock = pygame.time.Clock()
        running = True
        while running:
            clock.tick(FPS)
            self._fps = clock.get_fps()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if self.debug:
                        print('[按键] key=%s(%d) name=%s unicode=%r'
                              % (ev.key, ev.key, pygame.key.name(ev.key),
                                 getattr(ev, 'unicode', '')))
                    if self.menu_active:
                        # 开始界面：Esc 退出；其余任意键进入对战
                        if ev.key == pygame.K_ESCAPE:
                            running = False
                        else:
                            self.start_game()
                    elif ev.key == pygame.K_ESCAPE:   # 对战中 Esc：退出
                        running = False
                    # 注：R / 回车 重开已按用户需求移除；键盘仅负责移动/开火
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if self.menu_active:
                        self.start_game()            # 开始界面：点击任意处开始
                    elif self.game_over:
                        # 结算画面：鼠标点击任意处 → 重开一局（与键盘无关）
                        self.restart_on_click()
            self.update()
            self.draw()
            pygame.display.flip()

    def restart_on_click(self):
        """结算画面被鼠标点击时调用：直接重开一局（不依赖键盘/输入法）"""
        if self.game_over:
            if self.debug:
                print('[重开] 鼠标点击触发')
            self.reset()
            self._push_all_hp()         # 重开：两块手柄 LED 血条复位为满血

    # ------------------------------ 底层渲染 ------------------------------
    def _font(self, size, bold=False):
        """获取（带缓存的）中文字体。

        直接按常见字体文件路径探测（微软雅黑/黑体/宋体），避免调用
        pygame.font.SysFont/match_font 的全盘字体枚举（在某些 Windows
        环境下会触发 pygame 的 sysfont 崩溃）；找不到则退回默认字体。
        """
        key = (size, bold)
        if key not in self._fonts:
            import pygame
            import os
            font = None
            win = os.environ.get('WINDIR') or r'C:\Windows'
            font_dir = os.path.join(win, 'Fonts')
            if bold:
                candidates = ['msyhbd.ttc', 'simhei.ttf', 'msyh.ttc',
                              'simsun.ttc', 'Dengb.ttf']
            else:
                candidates = ['msyh.ttc', 'simhei.ttf', 'msyhbd.ttc',
                              'simsun.ttc', 'Deng.ttf']
            for name in candidates:
                path = os.path.join(font_dir, name)
                if os.path.exists(path):
                    try:
                        font = pygame.font.Font(path, size)
                        break
                    except Exception:
                        font = None
            if font is None:
                font = pygame.font.Font(None, size)   # 默认字体兜底
            if not bold:
                try:
                    font.set_bold(False)
                except Exception:
                    pass
            self._fonts[key] = font
        return self._fonts[key]

    @staticmethod
    def _text(surface, font, s, color, x, y, align='left'):
        """渲染一行文字；align: left/center/right（x 为对应基准）"""
        img = font.render(s, True, color)
        rect = img.get_rect()
        if align == 'center':
            rect.centerx = int(x)
        elif align == 'right':
            rect.right = int(x)
        else:
            rect.x = int(x)
        rect.y = int(y)
        surface.blit(img, rect)
        return rect

    def _heart(self, surface, cx, cy, size, color):
        """自绘红心（避免 emoji 字体兼容问题）"""
        import pygame
        r = size * 0.30
        pygame.draw.circle(surface, color,
                           (int(cx - size * 0.25), int(cy - size * 0.12)), int(r))
        pygame.draw.circle(surface, color,
                           (int(cx + size * 0.25), int(cy - size * 0.12)), int(r))
        pygame.draw.polygon(surface, color, [
            (int(cx - size * 0.52), int(cy - size * 0.05)),
            (int(cx + size * 0.52), int(cy - size * 0.05)),
            (int(cx), int(cy + size * 0.52))])

    # ------------------------------ 场景 ------------------------------
    def draw(self):
        """绘制一帧（需要 pygame 与 screen）"""
        if self.screen is None:
            return
        import pygame
        surf = self.screen
        now = self._now_fn()
        self._draw_arena_background(surf, now)
        self._draw_powerups(surf, now)
        self._draw_tanks_and_bullets(surf, now)
        self._draw_toasts(surf, now)
        if self.menu_active:
            # 开始界面：不画 HUD/结算，直接覆盖菜单（field 背景透出增加氛围）
            self._draw_menu(surf, now)
            return
        # HUD
        self._draw_hud(surf, now)
        # 结束画面
        if self.game_over:
            self._draw_game_over(surf)

    def _draw_arena_background(self, surface, now):
        """背景网格 + 战场边框 + 出生点光环 + 障碍物"""
        import pygame
        surf = surface
        surf.fill(self.BG_COLOR)
        for gx in range(0, WINDOW_W, 40):
            pygame.draw.line(surf, self.GRID_COLOR, (gx, 0), (gx, WINDOW_H))
        for gy in range(0, WINDOW_H, 40):
            pygame.draw.line(surf, self.GRID_COLOR, (0, gy), (WINDOW_W, gy))
        # 战场边框
        pygame.draw.rect(surf, self.WALL_COLOR, (0, 0, WINDOW_W, WINDOW_H), 3)
        # 出生点光环
        for pid, (sx, sy, _a) in SPAWNS.items():
            color = self.P1_COLOR if pid == PLAYER1 else self.P2_COLOR
            pygame.draw.circle(surf, color, (int(sx), int(sy)), 26, 2)
        # 障碍物
        for ob in self.obstacles:
            rect = pygame.Rect(int(ob.x), int(ob.y), int(ob.w), int(ob.h))
            pygame.draw.rect(surf, self.OB_COLOR, rect, border_radius=8)
            pygame.draw.rect(surf, self.OB_HI, rect, 2, border_radius=8)
            pygame.draw.line(surf, self.OB_HI,
                             (rect.x + 6, rect.y + 3), (rect.right - 6, rect.y + 3), 2)
            pygame.draw.rect(surf, self.OB_EDGE, rect, 4, border_radius=8)

    def _draw_powerups(self, surface, now):
        """道具（发光图标；剩余不足 3s 时闪烁提醒即将消失）"""
        for p in self.powerups:
            rem = POWERUP_LIFETIME - (now - p.born_at)
            if rem < 3.0 and int(now * 8) % 2 == 0:
                continue                       # 闪烁相位：跳过本帧绘制
            psurf, pside = self._powerup_surface(p.kind)
            surface.blit(psurf, (int(p.x) - pside // 2, int(p.y) - pside // 2))

    def _draw_tanks_and_bullets(self, surface, now):
        """坦克 + 子弹"""
        for pid in (PLAYER1, PLAYER2):
            self._draw_tank(surface, pid, self.tanks[pid], now)
        for pid in (PLAYER1, PLAYER2):
            for b in self.bullets[pid]:
                self._draw_bullet(surface, pid, b)

    def _draw_toasts(self, surface, now):
        """拾取回血等浮动提示：从坦克头顶向上飘并渐隐（1.2s）"""
        import pygame
        for t in self.toasts:
            age = now - t['born']
            if age < 0.0 or age >= TOAST_DURATION:
                continue
            tk = self.tanks[t['pid']]
            x = int(tk.x)
            y = int(tk.y) - 24 - int(age * 38.0)
            if y < 4:
                continue
            img = self._font(16, bold=True).render(t['text'], True, t['color'])
            # 逐帧渐隐（对 per-pixel alpha 表面做通道相乘）
            alpha = int(230 * (1.0 - age / TOAST_DURATION))
            img = img.copy()
            img.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(img, (x - img.get_width() // 2, y))

    def _draw_menu(self, surface, now):
        """开始界面：标题 / 操作说明 / 道具简介 / 闪烁"开始"提示。
        半透明遮罩叠在开局场景上；按任意键/点击/手柄按键进入对战。
        （位置常量与 tests/text_layout_qa.py 的 texts_menu() 保持一致）"""
        import pygame
        veil = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        veil.fill((12, 14, 22, 178))
        surface.blit(veil, (0, 0))
        cx = WINDOW_W / 2
        # 标题 + 副标题
        self._text(surface, self._font(52, bold=True), '双人坦克对战',
                   (235, 240, 255), cx, 96, align='center')
        self._text(surface, self._font(17), 'STC-B 学习板手柄 · 双人同屏对战',
                   self.TEXT_DIM, cx, 178, align='center')
        # 操作说明（玩家1蓝 / 玩家2红）
        self._text(surface, self._font(15),
                   '玩家1（蓝）  手柄：导航键转向/移动 · K1 开火      键盘：WASD + 空格',
                   self.P1_COLOR, cx, 240, align='center')
        self._text(surface, self._font(15),
                   '玩家2（红）  手柄：导航键转向/移动 · K1 开火      键盘：方向键 + 回车',
                   self.P2_COLOR, cx, 266, align='center')
        # 道具简介
        self._text(surface, self._font(14),
                   '道具：碾过发光图标即拾取 —— 加速 / 炮弹增强(命中-2血) / 血包(+1命) / 护盾(挡1发)',
                   self.TEXT_DIM, cx, 304, align='center')
        # 开始提示（闪烁亮/暗两相）
        blink = int(now * 2.0) % 2 == 0
        self._text(surface, self._font(20, bold=True), '按任意键 或 点击鼠标 开始',
                   (235, 240, 255) if blink else self.TEXT_DIM,
                   cx, 376, align='center')
        self._text(surface, self._font(13),
                   '对局结束后：点击鼠标 或 任一手柄按 K2 再来一局',
                   self.TEXT_DIM, cx, 424, align='center')
        self._text(surface, self._font(13), 'Esc 退出',
                   self.TEXT_DIM, cx, 560, align='center')

    def _draw_tank(self, surface, pid, tank, now):
        import pygame
        import math
        x, y, ang = tank.x, tank.y, tank.angle
        rad = math.radians(ang)
        base = self.P1_COLOR if pid == PLAYER1 else self.P2_COLOR
        edge = (20, 40, 90) if pid == PLAYER1 else (110, 22, 22)
        h = TANK_SIZE / 2.0

        # 车体（旋转矩形多边形）
        corners = []
        for ox, oy in ((-h, -h), (h, -h), (h, h), (-h, h)):
            corners.append((x + ox * math.cos(rad) - oy * math.sin(rad),
                            y + ox * math.sin(rad) + oy * math.cos(rad)))
        pts = [(int(px), int(py)) for px, py in corners]
        pygame.draw.polygon(surface, base, pts)
        pygame.draw.polygon(surface, edge, pts, 2)

        # 炮管（深色粗线，末端与子弹出膛点(muzzle_point=半长+8)视觉衔接）
        bx = x + math.cos(rad) * (h + 6.0)
        by = y + math.sin(rad) * (h + 6.0)
        pygame.draw.line(surface, self.GUN_COLOR,
                         (int(x + math.cos(rad) * 4.0), int(y + math.sin(rad) * 4.0)),
                         (int(bx), int(by)), 5)
        # 炮口高亮
        pygame.draw.circle(surface, (200, 208, 224),
                           (int(bx), int(by)), 3)

        # 重生无敌：呼吸闪烁白圈（重生保护，最多 1s）
        if now < tank.invincible_until:
            if int(now * 8) % 2 == 0:
                pygame.draw.circle(surface, (255, 255, 255),
                                   (int(x), int(y)), int(h + 8), 2)
        # 道具护盾：青色粗环（可挡 1 发；与重生无敌白圈区分，闪烁更慢）
        if now < tank.shield_until:
            if int(now * 6) % 2 == 0:
                pygame.draw.circle(surface, self.POWERUP_COLORS[KIND_SHIELD],
                                   (int(x), int(y)), int(h + 9), 4)

    def _bullet_surface(self, pid, boosted=False):
        """子弹发光表面（SRCALPHA，带透明外圈，缓存复用）。
        boosted=炮弹增强弹：外圈更大更亮 + 白核，便于对手一眼识别高风险弹"""
        key = (pid, boosted)
        if key not in self._bullet_cache:
            import pygame
            color = self.P1_COLOR if pid == PLAYER1 else self.P2_COLOR
            r = int(BULLET_RADIUS)
            ring = (r + 8) if boosted else (r + 4)
            side = 2 * ring + 2
            surf = pygame.Surface((side, side), pygame.SRCALPHA)
            c = side // 2
            # 外圈微光(半透明) → 弹体 → 白色高光
            if boosted:
                pygame.draw.circle(surf, color + (110,), (c, c), r + 7)
                pygame.draw.circle(surf, (255, 255, 255), (c, c), r + 4, 2)
            pygame.draw.circle(surf, color + (80,), (c, c), r + 3)
            pygame.draw.circle(surf, color, (c, c), r)
            pygame.draw.circle(surf, (255, 255, 255), (c, c),
                               max(1, r - 1 if boosted else r - 2))
            self._bullet_cache[key] = (surf, side)
        return self._bullet_cache[key]

    def _draw_bullet(self, surface, pid, bullet):
        surf, side = self._bullet_surface(pid, boosted=bullet.damage > 1)
        surface.blit(surf, (int(bullet.x) - side // 2, int(bullet.y) - side // 2))

    # ------------------------------ 道具渲染 ------------------------------
    def _powerup_surface(self, kind):
        """道具发光图标表面（SRCALPHA，含发光 + 底色圆 + 白色图标，缓存复用）"""
        if kind not in self._powerup_cache:
            import pygame
            color = self.POWERUP_COLORS[kind]
            side = 40
            surf = pygame.Surface((side, side), pygame.SRCALPHA)
            c = side // 2
            # 外发光（两层半透明）→ 底色圆 + 白描边
            pygame.draw.circle(surf, color + (60,), (c, c), 19)
            pygame.draw.circle(surf, color + (120,), (c, c), 15)
            pygame.draw.circle(surf, color, (c, c), 12)
            pygame.draw.circle(surf, (255, 255, 255), (c, c), 12, 2)
            self._draw_powerup_glyph(surf, kind, c)
            self._powerup_cache[kind] = (surf, side)
        return self._powerup_cache[kind]

    @staticmethod
    def _draw_powerup_glyph(surf, kind, c):
        """在道具底色圆上画白色图标（以圆心 c,c 为基准，四种各不相同）"""
        import pygame
        WHITE = (255, 255, 255)
        if kind == KIND_SPEED:
            # 加速：闪电
            pygame.draw.polygon(surf, WHITE, [
                (c + 3, c - 9), (c - 5, c + 1), (c - 1, c + 1),
                (c - 4, c + 9), (c + 6, c - 1), (c + 1, c - 1)])
        elif kind == KIND_CANNON:
            # 炮弹增强：弹头（白核 + 准星环）
            pygame.draw.circle(surf, WHITE, (c, c - 1), 3)
            pygame.draw.circle(surf, WHITE, (c, c - 1), 7, 2)
        elif kind == KIND_HEALTH:
            # 血包：白十字
            pygame.draw.rect(surf, WHITE, (c - 7, c - 3, 14, 6))
            pygame.draw.rect(surf, WHITE, (c - 3, c - 7, 6, 14))
        elif kind == KIND_SHIELD:
            # 护盾：盾形描边
            pygame.draw.polygon(surf, WHITE, [
                (c, c - 9), (c - 7, c - 6), (c - 7, c + 2),
                (c - 4, c + 6), (c, c + 9), (c + 4, c + 6),
                (c + 7, c + 2), (c + 7, c - 6)], 2)

    # ------------------------------ HUD ------------------------------
    def _draw_hud(self, surface, now):
        for pid in (PLAYER1, PLAYER2):
            self._draw_player_hud(surface, pid, now)
        # 顶部中央：连接/对战状态
        if not self.game_over:
            desc = []
            for pid in (PLAYER1, PLAYER2):
                desc.append('玩家%d:%s' % (pid, self._conn_desc(pid)))
            self._text(surface, self._font(15), '   '.join(desc),
                       self.TEXT_COLOR, WINDOW_W / 2, 12, align='center')
        # 等待提示（串口模式且尚无任何板子绑定）
        if (self.hub is not None and not self.game_over and
                self.hub.bound_count() == 0):
            self._text(surface, self._font(17), '等待手柄连接… 给两块开发板上电后自动识别',
                       self.TEXT_DIM, WINDOW_W / 2, WINDOW_H / 2 - 60,
                       align='center')
        # 底部操作提示（居中，位于 FPS 上方一行，避免与右下角 FPS 重叠）
        hint = ('手柄：导航键=转向/移动  K1=开火      '
                '键盘：P1 WASD+空格   P2 方向键+回车      Esc=退出')
        self._text(surface, self._font(13), hint, self.TEXT_DIM,
                   WINDOW_W / 2, WINDOW_H - 48, align='center')
        # FPS（右下角）
        self._text(surface, self._font(15),
                   '%4.1f FPS' % self._fps, self.TEXT_DIM,
                   WINDOW_W - 14, WINDOW_H - 28, align='right')
        # 当前地图名（左下角，随机地图时便于认出本局地图）
        self._text(surface, self._font(13),
                   '地图·%s' % self.map_name, self.TEXT_DIM,
                   16, WINDOW_H - 28, align='left')

    def _conn_desc(self, pid):
        """生成玩家连接状态描述文本（在线/断开/等待/键盘）"""
        if self.hub is None:
            return '键盘模式'
        if not self.hub.is_bound(pid):
            return '等待连接'
        m, online = self.hub.get_control(pid)
        port = self.hub.binding_port(pid) or '?'
        return ('%s 在线' % port) if online else ('%s 断开!' % port)

    def _draw_player_hud(self, surface, pid, now):
        """左上（玩家1）/右上（玩家2）信息块：名称/连接点/红心/得分"""
        tank = self.tanks[pid]
        color = self.P1_COLOR if pid == PLAYER1 else self.P2_COLOR
        align = 'left' if pid == PLAYER1 else 'right'
        x = 16 if pid == PLAYER1 else WINDOW_W - 16

        # 第1行：名称 + 连接状态点 + 连接描述
        self._text(surface, self._font(17, bold=True), '玩家%d' % pid,
                   color, x, 12, align=align)
        dot_x = (x + 8 + 62) if pid == PLAYER1 else (x - 8 - 62)
        if self.hub is None:
            dot_c = self.GRAY
        elif not self.hub.is_bound(pid):
            dot_c = self.GRAY
        else:
            _m, online = self.hub.get_control(pid)
            dot_c = self.GREEN if online else self.ORANGE
        import pygame
        pygame.draw.circle(surface, dot_c, (int(dot_x), 22), 5)

        # 第2行：红心（实心=剩余生命，空心=已损失）
        hy = 44
        gap = 22
        if pid == PLAYER1:
            hx0 = 16
            for i in range(START_LIVES):
                c = color if i < tank.lives else self.GRAY
                self._heart(surface, hx0 + i * gap, hy, 16, c)
        else:
            for i in range(START_LIVES):
                c = color if i < tank.lives else self.GRAY
                self._heart(surface, x - 16 - (START_LIVES - 1 - i) * gap, hy, 16, c)

        # 第3行：得分 / 连接描述
        self._text(surface, self._font(14), '得分 %d' % tank.score,
                   self.TEXT_COLOR, x, 62, align=align)
        self._text(surface, self._font(12), self._conn_desc(pid),
                   self.TEXT_DIM, x, 80, align=align)
        # 第4行：道具增益栏（加速/炮强/护盾 图标文本 + 剩余秒数）
        self._draw_buff_bar(surface, pid, now)

    def _draw_buff_bar(self, surface, pid, now):
        """当前生效中的道具增益：'加速 5s / 炮强 4s / 护盾 8s' 一行
        （左上靠左、右上靠右排列；无增益时不绘制，避免占位噪点）。

        倒计时：显示向上取整的剩余整秒（6→5→…→1），归零瞬间该增益恰好到期，
        与效果判定（now < *_until）共用同一时钟，显示与效果严格同步。
        """
        t = self.tanks[pid]
        buffs = []
        if now < t.speed_until:
            buffs.append((KIND_SPEED, t.speed_until))      # 存绝对到期时刻
        if now < t.cannon_until:
            buffs.append((KIND_CANNON, t.cannon_until))
        if now < t.shield_until:
            buffs.append((KIND_SHIELD, t.shield_until))
        if not buffs:
            return
        tokens = []
        for kind, until in buffs:
            secs = self._buff_seconds(until, now)
            tokens.append((kind, '%s %ds' % (BUFF_SHORT_NAMES[kind], secs)))
        font = self._font(12)
        y = 102
        gap = 10
        if pid == PLAYER1:
            x = 16
            for kind, text in tokens:
                r = self._text(surface, font, text,
                               self.POWERUP_COLORS[kind], x, y)
                x = r.right + gap
        else:
            x = WINDOW_W - 16
            for kind, text in reversed(tokens):
                r = self._text(surface, font, text,
                               self.POWERUP_COLORS[kind], x, y, align='right')
                x = r.left - gap

    @staticmethod
    def _buff_seconds(until, now):
        """增益剩余整秒：向上取整（生效中恒 ≥1s）；已到期/未激活 → 0"""
        import math
        return int(math.ceil(max(0.0, until - now)))

    def _draw_game_over(self, surface):
        import pygame
        winner = self.tanks[self.winner]
        color = self.P1_COLOR if self.winner == PLAYER1 else self.P2_COLOR
        # 半透明遮罩
        veil = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        veil.fill((10, 12, 18, 160))
        surface.blit(veil, (0, 0))
        # 中央面板
        cx, cy = WINDOW_W / 2, WINDOW_H / 2
        self._text(surface, self._font(46, bold=True),
                   '玩家%d 获胜！' % self.winner, color,
                   cx, cy - 70, align='center')
        self._text(surface, self._font(20),
                   '得分 %d : %d' % (self.tanks[PLAYER1].score,
                                     self.tanks[PLAYER2].score),
                   self.TEXT_COLOR, cx, cy - 8, align='center')
        self._text(surface, self._font(17),
                   '点击鼠标 或 任一手柄按 K2 重新开始', self.TEXT_DIM,
                   cx, cy + 34, align='center')
        self._text(surface, self._font(14),
                   '按 Esc 键退出', self.TEXT_DIM,
                   cx, cy + 62, align='center')

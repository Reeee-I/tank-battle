# -*- coding: utf-8 -*-
"""tests/test_logic.py —— 无头逻辑自测（无需 pygame / 无需硬件）

运行：python tests/test_logic.py
覆盖：协议解析器、坦克移动/转向/边界/障碍、开火与冷却、子弹与障碍、
      命中-扣血-重生-无敌吸收、胜负判定、R 重开、串口心跳判定、
      道具系统（定时生成/限量/超时消失/碾过拾取/加速/炮弹增强/血包/护盾/
      阵亡清增益）。
全部通过打印 PASS 汇总并以 0 退出；失败抛出 AssertionError。
"""

import sys
import time

sys.path.insert(0, '.')          # 使 `import serial_handler` 等可用
sys.path.insert(0, 'PC')         # 兼容在 PC/ 目录与项目根目录两种运行方式

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from serial_handler import (PacketParser, PLAYER1, PLAYER2,
                            BIT_LEFT, BIT_RIGHT, BIT_UP, BIT_DOWN, BIT_FIRE,
                            BIT_RESTART, BIT_K3, SerialHub, HEARTBEAT_TIMEOUT)
from tank import Tank, TANK_SIZE
from bullet import Bullet
from powerup import (PowerUp, KIND_SPEED, KIND_CANNON, KIND_HEALTH,
                     KIND_SHIELD, KINDS)
from game import (Game, SPAWNS, SCORE_PER_HIT, START_LIVES, WINDOW_W, WINDOW_H,
                  POWERUP_SPAWN_FIRST, POWERUP_LIFETIME, POWERUP_MAX_ON_FIELD,
                  POWERUP_CANNON_DAMAGE)


class FakeClock(object):
    """可手动推进的假时钟（确定性测试用）"""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class SpyHub(object):
    """记录 set_hp 调用（LED 血量下行）的假串口集线器；
    只读查询全部返回"空态"，使 Game 在无真实板子时也能驱动。"""

    def __init__(self):
        self.calls = []              # [(玩家号, 血量), ...] 按 set_hp 顺序

    def set_hp(self, pid, hp):
        self.calls.append((pid, hp))

    def get_control(self, pid, now=None):
        return (0, False)

    def bound_count(self):
        return 0

    def is_bound(self, pid):
        return False

    def binding_port(self, pid):
        return None


def run_frames(game, clock, n):
    """推进 n 帧（每帧 1/60 秒）"""
    for _ in range(n):
        clock.advance(1.0 / 60.0)
        game.update()


def test_parser():
    """协议解析器：正常包 / 噪声 / 垃圾重同步 / 连续包"""
    p = PacketParser()
    assert p.feed_bytes(bytes([0xAA, 0x01, 0x14])) == [(1, 0x14)]
    assert p.feed_bytes(bytes([0xAA, 0x02, 0x00])) == [(2, 0x00)]
    # 前导噪声
    assert p.feed_bytes(bytes([0x11, 0x55, 0xAA, 0x01, 0x08])) == [(1, 0x08)]
    # 玩家号非法 → 滑动窗口找下一个包头
    assert p.feed_bytes(bytes([0xAA, 0x99, 0xAA, 0x01, 0x04])) == [(1, 0x04)]
    # 连续两个完整包
    assert p.feed_bytes(bytes([0xAA, 0x01, 0x04, 0xAA, 0x02, 0x10])) == [
        (1, 0x04), (2, 0x10)]
    print('  [PASS] 协议解析器')


def new_game():
    g = Game(hub=None, keyboard=False)
    clock = FakeClock()
    g.set_clock(clock)
    return g, clock


def test_move_forward():
    """前进：沿 0° 方向每帧 3px"""
    g, clock = new_game()
    g._inject[PLAYER1] = BIT_UP
    run_frames(g, clock, 10)
    t1 = g.tanks[PLAYER1]
    assert abs(t1.x - (SPAWNS[PLAYER1][0] + 30)) < 1e-6, t1
    assert abs(t1.y - SPAWNS[PLAYER1][1]) < 1e-6, t1
    print('  [PASS] 前进移动（速度 3px/帧）')


def test_rotate():
    """转向：右转每帧 2°（约 120°/s 手感档）"""
    g, clock = new_game()
    g._inject[PLAYER1] = BIT_RIGHT
    run_frames(g, clock, 9)
    assert abs(g.tanks[PLAYER1].angle - 18.0) < 1e-6
    g2, clock2 = new_game()
    g2._inject[PLAYER1] = BIT_LEFT
    run_frames(g2, clock2, 5)
    assert abs(g2.tanks[PLAYER1].angle - (-10.0) % 360) < 1e-6
    print('  [PASS] 转向（2°/帧，左右对称）')


def test_boundary():
    """边界：坦克不可越出战场（纯物理，开阔场 → 清空障碍）"""
    g, clock = new_game()
    g.obstacles = []                 # 边界测试与地图无关：清障碍测纯边界
    g.tanks[PLAYER2].y = 80.0            # 挪开对方坦克，避免被其阻挡（互撞规则）
    g._inject[PLAYER1] = BIT_UP
    run_frames(g, clock, 500)
    x = g.tanks[PLAYER1].x
    assert x <= 800 - 15 + 1e-6 and x >= 800 - 15 - 4.0, x
    print('  [PASS] 战场边界限制')


def test_obstacle_block_tank():
    """障碍物：坦克无法穿过（贴边停下）"""
    g, clock = new_game()
    t1 = g.tanks[PLAYER1]
    t1.x, t1.y, t1.angle = 280.0, 245.0, 0.0   # 正对中央横墙左缘(x=345)
    g._inject[PLAYER1] = BIT_UP
    run_frames(g, clock, 60)
    # 车体右缘不得越过障碍左缘：x + 15 <= 345
    assert t1.x + 15.0 <= 345.0 + 1e-6, t1
    # 且已被顶住（因 3px/帧步进，停点与墙面相差不超过一个步长）
    assert t1.x >= 345.0 - 15.0 - 3.0 - 1e-6, t1
    print('  [PASS] 障碍物阻挡坦克')


def test_fire_and_cooldown():
    """开火：边沿单发 + 200ms 冷却 + 同屏最多 3 发"""
    g, clock = new_game()
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)                    # t≈1000.017：发第 1 弹，冷却至 ≈1000.217
    assert len(g.bullets[PLAYER1]) == 1
    run_frames(g, clock, 3)                    # 持续按住：无上升沿 → 不再发射
    assert len(g.bullets[PLAYER1]) == 1, '按住不应连发'

    # —— 冷却：松开后立刻再按（总耗时仍 <200ms）→ 不发射 ——
    g._inject[PLAYER1] = 0
    run_frames(g, clock, 1)
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)
    assert len(g.bullets[PLAYER1]) == 1, '200ms 冷却期内不应发射'

    # —— 冷却结束（再等 >200ms）后重新按 → 第 2 发 ——
    g._inject[PLAYER1] = 0
    run_frames(g, clock, 1)
    clock.advance(0.30)
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)
    assert len(g.bullets[PLAYER1]) == 2, '冷却结束后应可再发射'

    # —— 同屏上限 3 发（继续按最多只到 3）——
    for _ in range(6):
        g._inject[PLAYER1] = 0
        run_frames(g, clock, 1)
        clock.advance(0.25)
        g._inject[PLAYER1] = BIT_FIRE
        run_frames(g, clock, 1)
    assert len(g.bullets[PLAYER1]) == 3, '同屏最多 3 发'
    print('  [PASS] 开火：边沿单发/200ms冷却/3发上限')


def test_bullet_obstacle():
    """子弹撞障碍物消失且不伤害任何坦克"""
    g, clock = new_game()
    t1 = g.tanks[PLAYER1]
    t1.x, t1.y, t1.angle = 300.0, 245.0, 0.0   # 近距离正对中央横墙
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)
    assert len(g.bullets[PLAYER1]) == 1
    run_frames(g, clock, 30)
    assert len(g.bullets[PLAYER1]) == 0, '子弹应被障碍物吸收'
    assert g.tanks[PLAYER2].lives == START_LIVES
    print('  [PASS] 子弹被障碍物拦截')


def _fire_hit_setup(g, clock, target_x, target_y, frames=10):
    """让玩家1朝固定敌人位置打一发并推进 frames 帧"""
    t2 = g.tanks[PLAYER2]
    t2.x, t2.y, t2.angle = float(target_x), float(target_y), 180.0
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)          # 发弹
    g._inject[PLAYER1] = 0
    run_frames(g, clock, frames)     # 飞行碰撞


def test_hit_respawn_score():
    """命中：敌人生命-1、射手+10分、敌人回出生点并进入无敌"""
    g, clock = new_game()
    # 玩家2 放在玩家1 炮口正前方很近处（约 50px），几帧内必命中
    _fire_hit_setup(g, clock, 200, 300, frames=15)
    t2 = g.tanks[PLAYER2]
    assert t2.lives == START_LIVES - 1, t2
    assert g.tanks[PLAYER1].score == SCORE_PER_HIT
    # 重生回出生点
    assert (abs(t2.x - SPAWNS[PLAYER2][0]) < 1e-6 and
            abs(t2.y - SPAWNS[PLAYER2][1]) < 1e-6), t2
    assert t2.invincible_until > clock(), '应处于无敌期'
    print('  [PASS] 命中：扣血/加分/重生/无敌')


def test_invincible_absorb():
    """无敌期内被击中：不掉血，子弹被护盾吸收"""
    g, clock = new_game()
    # 制造一次命中使玩家2 进入无敌
    _fire_hit_setup(g, clock, 200, 300, frames=15)
    t2 = g.tanks[PLAYER2]
    assert t2.invincible_until > clock()
    lives_before = t2.lives
    score_before = g.tanks[PLAYER1].score
    # 立刻把玩家2 移到前方再补一枪（仍在无敌期内）
    _fire_hit_setup(g, clock, 200, 300, frames=15)
    assert t2.lives == lives_before, '无敌期不应扣血'
    assert g.tanks[PLAYER1].score == score_before, '无敌期命中不得分'
    print('  [PASS] 无敌护盾吸收子弹')


def test_game_over_and_reset():
    """生命归零：游戏结束显示胜者；R 重开恢复初始状态"""
    g, clock = new_game()
    # 直接压到 1 血再打中
    g.tanks[PLAYER2].lives = 1
    _fire_hit_setup(g, clock, 200, 300, frames=15)
    assert g.game_over and g.winner == PLAYER1
    assert g.tanks[PLAYER2].lives == 0
    assert len(g.bullets[PLAYER1]) == 0 and len(g.bullets[PLAYER2]) == 0

    # 结束后 update 冻结（不注入 K2/开火键；开火在结算画面已不触发任何动作）
    x_before = g.tanks[PLAYER1].x
    g._inject[PLAYER1] = BIT_UP
    run_frames(g, clock, 10)
    assert g.tanks[PLAYER1].x == x_before
    assert g.game_over is True            # 未按 K2/点击 → 仍保持结算

    # 重开 = reset()（对应鼠标点击 / 手柄 K2）
    g.reset()
    g.reset()
    assert g.game_over is False and g.winner is None
    assert g.tanks[PLAYER1].lives == START_LIVES
    assert g.tanks[PLAYER2].lives == START_LIVES
    assert g.tanks[PLAYER1].score == 0 and g.tanks[PLAYER2].score == 0
    assert len(g.bullets[PLAYER1]) == 0
    print('  [PASS] 胜负判定与重开(reset)')


def test_bullet_out_of_bounds():
    """子弹飞出场外自动移除（列表不无限增长）——开阔场直射越过全图"""
    g, clock = new_game()
    g.obstacles = []                 # 越界回收测试与地图无关：清障碍确保子弹直达边界
    # 把玩家2 挪到别处，避免挡住弹道（P1 在 y=300 直射向右）
    g.tanks[PLAYER2].y = 80.0
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)
    assert len(g.bullets[PLAYER1]) == 1
    # 从 x≈173 出发以 5px/帧 飞到右边界外约需 (800-173)/5+2 ≈ 127 帧
    run_frames(g, clock, 160)
    assert len(g.bullets[PLAYER1]) == 0, '越界子弹应被回收'
    assert g.tanks[PLAYER2].lives == START_LIVES  # 全程未误伤
    print('  [PASS] 子弹越界自动回收')


def test_ko_clears_all_no_double_score():
    """致命一击本帧：残弹全部清场、不重复结算（防幽灵子弹/重复加分）"""
    g, clock = new_game()
    g.tanks[PLAYER1].x, g.tanks[PLAYER1].y, g.tanks[PLAYER1].angle = 100.0, 300.0, 0.0
    t2 = g.tanks[PLAYER2]
    t2.x, t2.y, t2.angle = 300.0, 300.0, 180.0
    t2.lives = 1
    # 同帧构造：A 弹将致命命中；B 弹仍在飞行（旧实现会残留为幽灵子弹）
    g.bullets[PLAYER1] = [
        Bullet(280.0, 300.0, 0.0, PLAYER1),
        Bullet(340.0, 300.0, 0.0, PLAYER1),
    ]
    run_frames(g, clock, 1)
    assert g.game_over and g.winner == PLAYER1
    assert t2.lives == 0
    assert g.tanks[PLAYER1].score == SCORE_PER_HIT, '致命一击只计一次分'
    assert g.bullets[PLAYER1] == [] and g.bullets[PLAYER2] == [], '无幽灵子弹残留'
    print('  [PASS] KO 清场：无重复结算/无幽灵子弹')


def test_tank_tank_no_overlap():
    """坦克之间不可互相穿过（互撞阻挡）——纯物理，清空障碍避免撞入地图掩体"""
    g, clock = new_game()
    g.obstacles = []                 # 本测试把坦克放到中场直线上，需避开地图中央掩体
    t1, t2 = g.tanks[PLAYER1], g.tanks[PLAYER2]
    t1.x, t1.y, t1.angle = 300.0, 300.0, 0.0
    t2.x, t2.y, t2.angle = 380.0, 300.0, 180.0
    g._inject[PLAYER1] = BIT_UP          # 双向对开
    g._inject[PLAYER2] = BIT_UP
    run_frames(g, clock, 300)
    d = abs(t1.x - t2.x)
    assert d >= 30.0 - 1e-6, '坦克不得重叠(间距 %.1f)' % d
    assert d <= 36.0, '坦克应能相互顶住(间距 %.1f)' % d
    print('  [PASS] 坦克互撞阻挡（间距 %.1fpx）' % d)


def test_restart_via_K2_on_gameover():
    """结算画面：任一手柄按 K2(bit5) 重开；K1(开火)/旧键盘键不再触发"""
    g, clock = new_game()
    g._end_game(PLAYER2)                      # 制造对局结束
    assert g.game_over
    # K1(开火)在结算画面不再触发重开（已按需求移除）
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)
    assert g.game_over, '按 K1 不应重开'
    # 手柄按 K2(bit5) → 重开
    g._inject[PLAYER1] = 0
    run_frames(g, clock, 1)
    g._inject[PLAYER1] = BIT_RESTART
    run_frames(g, clock, 1)
    assert not g.game_over and g.winner is None, '按 K2 应重开'
    assert g.tanks[PLAYER1].lives == START_LIVES
    assert g.tanks[PLAYER2].lives == START_LIVES
    print('  [PASS] 结算画面按 K2 重开（K1 不再触发）')


def test_restart_on_click():
    """结算画面：鼠标点击任意处 → 重开一局（不依赖键盘/输入法）"""
    g, clock = new_game()
    g._end_game(PLAYER1)
    assert g.game_over
    g.restart_on_click()                      # 等价于鼠标点击结算画面
    assert not g.game_over and g.winner is None
    assert g.tanks[PLAYER1].lives == START_LIVES
    print('  [PASS] 结算画面鼠标点击重开')


def test_hub_heartbeat():
    """串口心跳：超时判定断线、恢复后重连"""
    hub = SerialHub(preferred=None)   # 不 start()，纯逻辑测试
    now = time.monotonic()
    with hub._lock:
        hub._state[PLAYER1]['port'] = 'COM9'
        hub._state[PLAYER1]['last'] = now - 0.1
        hub._state[PLAYER1]['mask'] = BIT_UP | BIT_FIRE
    mask, online = hub.get_control(PLAYER1, now=now)
    assert online and mask == (BIT_UP | BIT_FIRE)
    mask, online = hub.get_control(PLAYER1, now=now + HEARTBEAT_TIMEOUT + 0.1)
    assert not online and mask == 0, '超时应判离线且掩码清零'
    assert hub.binding_port(PLAYER1) == 'COM9'
    assert hub.bound_count() == 1
    assert hub.is_bound(PLAYER2) is False
    print('  [PASS] 串口心跳/断线判定')


def _dl_hit_once(g, clock, target_x, target_y, frames=15):
    """玩家1 朝目标位置打一发（命中 → 触发血量下行推送）"""
    t2 = g.tanks[PLAYER2]
    t2.x, t2.y, t2.angle = float(target_x), float(target_y), 180.0
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)
    g._inject[PLAYER1] = 0
    run_frames(g, clock, frames)


def test_led_hp_downlink_push():
    """手柄 LED 血量联动（PC 下行推送时机）：
    直开开局推满血；命中→2、死亡→0 推最新血量；血包回血→推；
    K2 重开后两板重新推满血 3。hub=None/无板不影响（键盘模式）。"""
    hub = SpyHub()
    g = Game(hub=hub, keyboard=False)     # menu=False：开局即推满血
    clock = FakeClock()
    g.set_clock(clock)
    assert hub.calls == [(PLAYER1, 3), (PLAYER2, 3)], hub.calls
    hub.calls.clear()

    # 命中：玩家2 3→2 → 应推送 (玩家2, 2)
    _dl_hit_once(g, clock, 200, 300)
    assert (PLAYER2, 2) in hub.calls, hub.calls
    assert g.tanks[PLAYER2].lives == 2
    hub.calls.clear()
    clock.advance(1.2)                            # 等重生无敌(1s)结束

    # 死亡：玩家2 压到 1 命再被打中 → 归零推 0、对局结束
    g.tanks[PLAYER2].lives = 1
    _dl_hit_once(g, clock, 200, 300)
    assert (PLAYER2, 0) in hub.calls, hub.calls
    assert g.game_over and g.tanks[PLAYER2].lives == 0
    hub.calls.clear()

    # K2 重开：两板重新推满血 3
    g._inject[PLAYER1] = BIT_RESTART
    run_frames(g, clock, 1)
    assert hub.calls == [(PLAYER1, 3), (PLAYER2, 3)], hub.calls
    assert not g.game_over
    print('  [PASS] LED血量下行：开局满血/命中/死亡/重开 推送时机正确')


def test_led_hp_downlink_heal_and_menu():
    """血包回血也推最新血量；开始界面期间不推（LED 保持全灭），
    正式开局（任一手柄按键/点击）才推满血。"""
    hub = SpyHub()
    g = Game(hub=hub, keyboard=False, menu=True)   # menu=True：开局不推
    clock = FakeClock()
    g.set_clock(clock)
    assert hub.calls == [], '开始界面期间不应推送（LED 保持全灭）'
    g._inject[PLAYER1] = BIT_K3
    run_frames(g, clock, 1)                       # 任意键开始 → 推满血
    assert not g.menu_active
    assert hub.calls == [(PLAYER1, 3), (PLAYER2, 3)], hub.calls
    hub.calls.clear()

    # 血包回血：玩家1 1 命 → 拾取 +1 → 推送 (玩家1, 2)
    g.next_powerup_at = clock() + 1000.0          # 冻结生成器，防干扰
    t1 = g.tanks[PLAYER1]
    t1.lives = 1
    t1.x, t1.y = 220.0, 200.0                     # 开阔处停坦克
    g.powerups.append(PowerUp(220.0, 200.0, KIND_HEALTH, clock()))
    run_frames(g, clock, 1)
    assert t1.lives == 2, '血包 +1 命'
    assert (PLAYER1, 2) in hub.calls, hub.calls
    print('  [PASS] LED血量下行：血包回血推送 / 开始界面不推·开局才推满血')


def pu_game():
    """道具测试专用：假时钟 Game 后重新 reset —— 道具计时器以假时钟为准"""
    g, clock = new_game()
    g.reset()
    return g, clock


def _p1_fire_once(g, clock, frames=45):
    """玩家1 沿当前朝向打一发并推进 frames 帧（发射 1 帧后松手）"""
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)
    g._inject[PLAYER1] = 0
    run_frames(g, clock, frames)


def _open_lane(g, x1=300.0, x2=500.0):
    """清空障碍并摆好对射阵型：P1 在 x1、P2 在 x2，同在 y=300 相向"""
    g.obstacles = []
    t1, t2 = g.tanks[PLAYER1], g.tanks[PLAYER2]
    t1.x, t1.y, t1.angle = x1, 300.0, 0.0
    t2.x, t2.y, t2.angle = x2, 300.0, 180.0
    return t1, t2


def test_powerup_spawn_schedule():
    """道具生成：开局约 5s 出第一件；间隔内不再刷；场上上限 2；位置合法"""
    g, clock = pu_game()
    run_frames(g, clock, 1)                        # t≈1000.017 < 1005
    assert g.powerups == [], '首件应在开局 5s 后出现'
    clock.advance(POWERUP_SPAWN_FIRST)
    run_frames(g, clock, 1)                        # t≈1005.017：刷第 1 件
    assert len(g.powerups) == 1
    p = g.powerups[0]
    assert p.kind in KINDS, '道具种类来自随机池'
    # 位置合法：整辆坦克可停（不出界、不压障碍、不与坦克/其他道具重叠）
    h = TANK_SIZE / 2.0
    assert 0.0 <= p.x - h and p.x + h <= WINDOW_W
    assert 0.0 <= p.y - h and p.y + h <= WINDOW_H
    for ob in g.obstacles:
        assert not ob.hit_rect(p.x - h, p.y - h, TANK_SIZE, TANK_SIZE), ob
    for tk in g.tanks.values():
        assert not tk.hit_rect(p.x - h, p.y - h, TANK_SIZE, TANK_SIZE)
    # 8~12s 间隔内不再刷第 2 件
    run_frames(g, clock, 60)                       # +1s
    assert len(g.powerups) == 1
    # 强推计时 → 第 2 件；已达上限 → 第 3 件不再出现
    g.next_powerup_at = clock()
    run_frames(g, clock, 1)
    assert len(g.powerups) == 2
    g.next_powerup_at = clock()
    run_frames(g, clock, 1)
    assert len(g.powerups) == POWERUP_MAX_ON_FIELD, '场上上限 %d 件'
    print('  [PASS] 道具定时生成/限量/位置合法')


def test_powerup_expiry():
    """道具 10s 无人拾取自动消失（计时从出生时刻起算）"""
    g, clock = pu_game()
    g.next_powerup_at = clock() + 60.0             # 冻结生成器，专注测过期
    t1 = g.tanks[PLAYER1]
    t1.x, t1.y = 200.0, 100.0                      # 挪开坦克防误拾取
    g.powerups.append(PowerUp(300.0, 200.0, KIND_HEALTH, clock()))
    clock.advance(POWERUP_LIFETIME - 0.2)
    run_frames(g, clock, 1)
    assert len(g.powerups) == 1, '未满 10s 不应消失'
    clock.advance(0.3)
    run_frames(g, clock, 1)
    assert g.powerups == [], '超 10s 应自动消失'
    print('  [PASS] 道具超时自动消失（10s）')


def test_powerup_health_pickup():
    """血包：碾过即拾取 +1 命（上限 3）；满血拾取无效且道具仍消耗"""
    g, clock = pu_game()
    g.next_powerup_at = clock() + 60.0
    t1 = g.tanks[PLAYER1]
    t1.x, t1.y = 220.0, 200.0                      # 开阔处
    t1.lives = 1
    g.powerups.append(PowerUp(220.0, 200.0, KIND_HEALTH, clock()))
    run_frames(g, clock, 1)
    assert g.powerups == [], '拾取后道具应消失'
    assert t1.lives == 2, '血包 +1 命'

    g2, clock2 = pu_game()
    g2.next_powerup_at = clock2() + 60.0
    t2 = g2.tanks[PLAYER2]
    t2.x, t2.y = 560.0, 200.0
    g2.powerups.append(PowerUp(560.0, 200.0, KIND_HEALTH, clock2()))
    run_frames(g2, clock2, 1)
    assert g2.powerups == [], '满血也应消耗道具'
    assert t2.lives == START_LIVES, '满血拾取不增加生命（上限 3）'
    print('  [PASS] 血包：碾过拾取 +1 命 / 满血无效不囤积')


def test_powerup_speed():
    """加速：生效期速度 ×1.5；到期自动回落基础速度"""
    g, clock = pu_game()
    g.next_powerup_at = clock() + 60.0             # 冻结生成器（防中途拾取干扰）
    t1 = g.tanks[PLAYER1]
    t1.x, t1.y, t1.angle = 300.0, 100.0, 0.0       # 空旷横道
    t1.speed_until = clock() + 5.0
    g._inject[PLAYER1] = BIT_UP
    run_frames(g, clock, 10)
    assert abs(t1.x - 345.0) < 1e-6, \
        '10 帧 × 3px/帧 ×1.5 = 45px，实际 %.1f' % (t1.x - 300.0)
    clock.advance(5.0)                             # 加速到期
    run_frames(g, clock, 10)
    assert abs(t1.x - 375.0) < 1e-6, '到期后回落 3px/帧'
    print('  [PASS] 加速：×1.5 生效 / 到期回落')


def test_powerup_cannon():
    """炮弹增强：命中 -2 血（增强期 2 发带走满血 3 命）"""
    g, clock = pu_game()
    g.next_powerup_at = clock() + 1000.0
    t1, t2 = _open_lane(g)
    t1.cannon_until = clock() + 5.0
    t2.lives = START_LIVES
    _p1_fire_once(g, clock, frames=45)
    assert t2.lives == START_LIVES - POWERUP_CANNON_DAMAGE, \
        '增强弹单发 -2 血（剩 %d）' % t2.lives
    assert g.tanks[PLAYER1].score == SCORE_PER_HIT, '命中仍只计一次分'
    clock.advance(1.3)                             # 冷却 + 重生无敌结束
    _p1_fire_once(g, clock, frames=90)             # 回出生点后射程更长
    assert g.game_over and g.winner == PLAYER1, '第二发增强弹直接带走'
    assert t2.lives == 0
    assert g.tanks[PLAYER1].score == 2 * SCORE_PER_HIT
    print('  [PASS] 炮弹增强：命中 -2 血 / 2 发带走满血')


def test_powerup_shield_blocks_once():
    """道具护盾：完整挡 1 发（不掉血/不重生/不清其他增益）后立即失效"""
    g, clock = pu_game()
    g.next_powerup_at = clock() + 1000.0
    t1, t2 = _open_lane(g)
    t2.lives = 2
    t2.shield_until = clock() + 10.0
    t2.speed_until = clock() + 10.0
    _p1_fire_once(g, clock, frames=45)
    assert t2.lives == 2, '护盾挡击不掉血'
    assert t2.shield_until == 0.0, '挡下后护盾立即失效'
    assert t2.speed_until > clock(), '挡击不清其他增益'
    assert abs(t2.x - 500.0) < 1e-6, '未被击回重生点'
    assert g.tanks[PLAYER1].score == 0, '挡击不得分'
    _p1_fire_once(g, clock, frames=45)             # 第二发：护盾已无 → 正常结算
    assert t2.lives == 1
    assert g.tanks[PLAYER1].score == SCORE_PER_HIT
    print('  [PASS] 护盾：挡 1 发后失效 / 挡击不扣血不重生')


def test_powerup_shield_expires():
    """道具护盾：限时未被打 → 到期自动失效（先到先失效）"""
    g, clock = pu_game()
    g.next_powerup_at = clock() + 1000.0
    t1, t2 = _open_lane(g)
    t2.shield_until = clock() + 0.5
    clock.advance(0.6)
    run_frames(g, clock, 1)
    _p1_fire_once(g, clock, frames=45)
    assert t2.lives == START_LIVES - 1, '护盾到期后命中正常 -1 血'
    print('  [PASS] 护盾限时到期失效')


def test_death_clears_buffs():
    """阵亡重生清除全部增益与护盾（防滚雪球平衡规则）"""
    g, clock = pu_game()
    g.next_powerup_at = clock() + 1000.0
    t1, t2 = _open_lane(g)
    t2.lives = 2
    t2.speed_until = clock() + 20.0
    t2.cannon_until = clock() + 20.0
    t2.shield_until = clock() + 20.0
    _p1_fire_once(g, clock, frames=45)             # 第 1 发：护盾挡下
    assert t2.lives == 2 and t2.shield_until == 0.0
    assert t2.speed_until > clock() and t2.cannon_until > clock()
    _p1_fire_once(g, clock, frames=45)             # 第 2 发：真命中 → 重生清空
    assert t2.lives == 1
    assert t2.speed_until == 0.0 and t2.cannon_until == 0.0
    assert t2.shield_until == 0.0
    assert abs(t2.x - SPAWNS[PLAYER2][0]) < 1e-6, '命中后回出生点'
    print('  [PASS] 阵亡重生清除全部增益与护盾')


def test_buff_countdown_display():
    """增益栏倒计时：生效中恒显示 ≥1s（向上取整）；归零瞬间效果同步消失"""
    assert Game._buff_seconds(1006.0, 1000.0) == 6
    assert Game._buff_seconds(1005.4, 1000.0) == 6
    assert Game._buff_seconds(1005.0, 1000.0) == 5
    assert Game._buff_seconds(1000.4, 1000.0) == 1
    assert Game._buff_seconds(1000.0, 1000.0) == 0
    assert Game._buff_seconds(999.0, 1000.0) == 0
    # 集成：6s 加速随时间递减，到期瞬间显示与效果同时归零
    g, clock = pu_game()
    g.next_powerup_at = clock() + 60.0
    t1 = g.tanks[PLAYER1]
    t1.speed_until = clock() + 6.0
    run_frames(g, clock, 12)                    # +0.2s：剩 5.8s → 显示 6s
    assert g._buff_seconds(t1.speed_until, clock()) == 6
    clock.advance(5.2)
    run_frames(g, clock, 1)                     # 剩 0.6s → 显示 1s
    assert g._buff_seconds(t1.speed_until, clock()) == 1
    clock.advance(0.7)
    run_frames(g, clock, 1)                     # 超过 6s → 归零
    assert g._buff_seconds(t1.speed_until, clock()) == 0
    assert not (clock() < t1.speed_until), '效果与倒计时应同步结束'
    print('  [PASS] 增益倒计时：≥1s 递减 / 归零即失效')


def test_menu_gate_and_start():
    """开始界面：菜单期间完全冻结；任意按键/点击后进入对战"""
    g, clock = new_game()
    g.menu_active = True
    x0 = g.tanks[PLAYER1].x
    # 无输入：菜单冻结（坦克不动、不刷道具）
    run_frames(g, clock, 10)
    assert g.tanks[PLAYER1].x == x0, '开始界面前坦克不应移动'
    assert g.powerups == [], '开始界面前不应刷道具'
    # 出现任意按键 → 本帧退出菜单（不推进移动），下一帧起正常对战
    g._inject[PLAYER1] = BIT_FIRE
    run_frames(g, clock, 1)
    assert not g.menu_active, '按键应退出开始界面'
    assert g.tanks[PLAYER1].x == x0, '退出菜单的当帧不应推进'
    g._inject[PLAYER1] = 0
    g._inject[PLAYER1] = BIT_UP
    run_frames(g, clock, 10)
    assert abs(g.tanks[PLAYER1].x - (x0 + 30.0)) < 1e-6, '开战后正常移动'
    # start_game() 本身幂等：菜单已关时调用无副作用
    g.start_game()
    assert not g.menu_active
    # 用户反馈场景：K3(bit6) 也应能开始（协议已补 bit6=K3，随数据包上报）
    g3, clock3 = new_game()
    g3.menu_active = True
    g3._inject[PLAYER1] = BIT_K3
    run_frames(g3, clock3, 1)
    assert not g3.menu_active, 'K3 应能退出开始界面'
    g3._inject[PLAYER1] = 0
    g3._inject[PLAYER2] = BIT_K3
    run_frames(g3, clock3, 1)
    assert not g3.menu_active, 'K3 已退出菜单后无副作用（不触发其他逻辑）'
    print('  [PASS] 开始界面：冻结等待 / 任意输入开战')


def test_no_menu_after_restart():
    """结算后 K2 / 鼠标点击 重开：直接进入下一局，不再显示开始界面"""
    g, clock = new_game()
    assert not g.menu_active
    g._end_game(PLAYER1)
    g._inject[PLAYER1] = BIT_RESTART
    run_frames(g, clock, 1)
    assert not g.game_over and not g.menu_active, 'K2 重开应直接开战'
    g._inject[PLAYER1] = BIT_UP
    run_frames(g, clock, 10)
    assert abs(g.tanks[PLAYER1].x - (SPAWNS[PLAYER1][0] + 30)) < 1e-6
    # 鼠标点击重开同理
    g._inject[PLAYER1] = 0
    g._end_game(PLAYER2)
    g.restart_on_click()
    assert not g.menu_active and not g.game_over
    print('  [PASS] 重开直接开始下一局（不经过开始界面）')


def test_health_toast_feedback():
    """血包拾取反馈：回血绿色'生命 +1'浮动提示；满血灰字'生命已满'；1.2s 后清理"""
    g, clock = pu_game()
    g.next_powerup_at = clock() + 60.0
    t1 = g.tanks[PLAYER1]
    t1.x, t1.y = 220.0, 200.0
    t1.lives = 1
    g.powerups.append(PowerUp(220.0, 200.0, KIND_HEALTH, clock()))
    run_frames(g, clock, 1)
    assert t1.lives == 2, '血包 +1 命'
    assert len(g.toasts) == 1 and g.toasts[0]['text'] == '生命 +1'
    assert g.toasts[0]['color'] == g.GREEN
    clock.advance(1.25)                          # 超过 1.2s 提示时长
    run_frames(g, clock, 1)
    assert g.toasts == [], '提示应按时自动清理'

    g2, clock2 = pu_game()
    g2.next_powerup_at = clock2() + 60.0
    t2 = g2.tanks[PLAYER2]
    t2.x, t2.y = 560.0, 200.0
    g2.powerups.append(PowerUp(560.0, 200.0, KIND_HEALTH, clock2()))
    run_frames(g2, clock2, 1)
    assert t2.lives == START_LIVES, '满血不增加'
    assert len(g2.toasts) == 1 and g2.toasts[0]['text'] == '生命已满'
    print('  [PASS] 血包反馈：回血/满血浮动提示与自动清理')


def main():
    print('双人坦克对战 · 无头逻辑自测')
    print('-' * 50)
    tests = [
        test_parser, test_move_forward, test_rotate, test_boundary,
        test_obstacle_block_tank, test_fire_and_cooldown,
        test_bullet_obstacle, test_bullet_out_of_bounds,
        test_hit_respawn_score,
        test_invincible_absorb, test_ko_clears_all_no_double_score,
        test_tank_tank_no_overlap, test_restart_via_K2_on_gameover,
        test_restart_on_click,
        test_game_over_and_reset,
        test_hub_heartbeat,
        test_led_hp_downlink_push,
        test_led_hp_downlink_heal_and_menu,
        test_powerup_spawn_schedule, test_powerup_expiry,
        test_powerup_health_pickup, test_powerup_speed,
        test_powerup_cannon, test_powerup_shield_blocks_once,
        test_powerup_shield_expires, test_death_clears_buffs,
        test_buff_countdown_display, test_menu_gate_and_start,
        test_no_menu_after_restart, test_health_toast_feedback,
    ]
    for t in tests:
        t()
    print('-' * 50)
    print('全部 %d 项测试通过 ✓' % len(tests))
    return 0


if __name__ == '__main__':
    sys.exit(main())

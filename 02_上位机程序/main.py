# -*- coding: utf-8 -*-
"""main.py —— 双人坦克对战 · 程序入口

用法：
    python main.py                     # 自动扫描并绑定两块开发板串口
    python main.py --p1 COM3 --p2 COM5 # 手动指定玩家1/玩家2 串口
    python main.py --no-keyboard       # 关闭键盘调试控制（纯手柄模式）

说明：
  - 手柄数据由 SerialHub 在独立线程接收，不阻塞游戏主循环；
  - 哪块板发来哪个玩家的包，就自动绑定到哪个玩家（无需记线序）；
  - 键盘调试模式默认开启（无板子也能双人试玩）。
"""

import argparse
import os
import sys


class _Tee(object):
    """同时输出到多个流（控制台 + 日志文件），供 --debug 使用"""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for st in self._streams:
            try:
                st.write(data)
                st.flush()
            except Exception:
                pass

    def flush(self):
        for st in self._streams:
            try:
                st.flush()
            except Exception:
                pass


def parse_args():
    parser = argparse.ArgumentParser(
        prog='双人坦克对战',
        description='使用两块 STC-B 开发板作手柄的双人坦克对战（PC 端）')
    parser.add_argument('--p1', metavar='COM口', default=None,
                        help='玩家1 对应的串口（如 COM3）；缺省自动扫描绑定')
    parser.add_argument('--p2', metavar='COM口', default=None,
                        help='玩家2 对应的串口（如 COM5）；缺省自动扫描绑定')
    parser.add_argument('--no-keyboard', action='store_true',
                        help='关闭键盘调试控制（纯手柄模式）')
    parser.add_argument('--debug', action='store_true',
                        help='打印按键与"重新开始"触发诊断（排查 R 键问题时使用）')
    return parser.parse_args()


def main():
    args = parse_args()
    preferred = [c for c in (args.p1, args.p2) if c]

    # pygame 初始化（窗口 1280x720 宽屏，标题"双人坦克对战"）
    import pygame
    import assets
    from serial_handler import SerialHub
    from game import Game, WINDOW_W, WINDOW_H, MAPS

    if pygame.version.vernum < (2, 0, 0):
        print('[错误] 需要 pygame 2.0 及以上版本：pip install -U pygame')
        return 1

    pygame.init()
    screen = pygame.display.set_mode((assets.SCREEN_W, assets.SCREEN_H))
    pygame.display.set_caption('双人坦克对战')

    print('=' * 58)
    print('  双人坦克对战 - PC 端')
    print('=' * 58)
    print('  - 每局随机抽取一张地图开局（共 %d 张，见画面左下角地图名）'
          % len(MAPS))
    print('  - 手柄：导航键转向/移动，K1 开火；K2 = 结算时重开')
    print('  - 键盘：P1 用 WASD+空格；P2 用方向键+回车（仅移动/开火）')
    print('  - 对局结束重开：点击鼠标 或 任一手柄按 K2；Esc 退出')
    print('-' * 58)

    # 串口：自动扫描/手动指定，接收线程由 SerialHub 管理
    hub = SerialHub(preferred=preferred if preferred else None)
    links = hub.start()
    candidates = hub.candidates()
    for err in hub.errors():            # 如 pyserial 缺失等（不阻断键盘模式）
        print('  [警告] %s' % err)
    if candidates:
        print('  已尝试打开串口：%s（绿点出现即连接成功，见画面顶部）'
              % '、'.join(candidates))
    else:
        print('  [提示] 未发现可用串口 → 可使用键盘进行双人对战（手柄插入后自动重连）')
    print('  对局结束后：点击鼠标 或 任一手柄按 K2 重开；Esc 退出 ...')
    print('  开始界面：按任意键 / 点击鼠标 / 任一手柄按键 开始对战（重开不再显示）')
    print('=' * 58)
    sys.stdout.flush()

    game = Game(hub=hub, screen=screen, keyboard=not args.no_keyboard,
                debug=args.debug, map_id='random', menu=True)
    log_file = None
    if args.debug:
        # 诊断输出同时写文件，避免"双击启动看不到控制台"时拿不到日志
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'debug_keys.log')
        log_file = open(log_path, 'a', encoding='utf-8')
        sys.stdout = _Tee(sys.__stdout__, log_file)
        print('[诊断模式] 已开启：按键与"重开"触发将打印到控制台，'
              '并追加写入 %s' % log_path)
        print('           对局结束后请分别试：点击鼠标 → 任一手柄按 K2。')
    try:
        game.run()
    finally:
        hub.stop()          # 关闭接收线程与串口
        if log_file is not None:
            log_file.close()
        pygame.quit()
    print('已退出。')


if __name__ == '__main__':
    main()

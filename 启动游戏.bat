@echo off
chcp 936 >nul
title 双人坦克对战 - 启动游戏（玩家1=蓝牙）
cd /d "%~dp0"

echo ============================================================
echo   启动游戏（玩家1 = 蓝牙手柄）
echo   --------------------------------------------------------
echo   [前提] 先双击过 启动BLE桥接.bat，且 "BLE桥接-勿关"
echo          窗口已提示"链路已就绪"；本脚本不负责开桥接。
echo   玩家2：未插有线板 = 键盘（方向键+回车）
echo ============================================================

echo.
echo [1/2] 检查蓝牙链路（最多 10 秒）...
python "%~dp002_上位机程序\tools\wait_link.py" COM20 10
if errorlevel 1 goto :nolink

echo [2/2] 链路 OK，启动游戏 ...
cd /d "%~dp002_上位机程序"
python main.py --p1 COM20
goto :end

:nolink
echo.
echo [未就绪] COM20 上没有收到蓝牙数据，请依次检查：
echo   1) 是否先双击了 启动BLE桥接.bat，并等到提示"链路已就绪"；
echo   2) 蓝牙板是否上电（必要时断电 3 秒重上电再开桥接）；
echo   3) VSPD 里 COM20/21 是否存在（没有就打开 VSPD 点 Apply）。
pause
exit /b 1

:end
echo.
echo 游戏已退出。
pause

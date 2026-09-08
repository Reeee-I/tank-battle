@echo off
chcp 936 >nul
title 双人坦克对战 - 蓝牙手柄一键启动
cd /d "%~dp0"

echo ============================================================
echo   双人坦克对战（PC）· 蓝牙手柄一键启动
echo   --------------------------------------------------------
echo   玩家1 = 蓝牙手柄板（BT05 BLE，需已上电）
echo   玩家2 = 有线手柄板（COM4）或键盘
echo   --------------------------------------------------------
echo   [若连不上] 蓝牙板断电3秒重上电；仍不行请先"关蓝牙→开蓝牙"再重上电
echo ============================================================

echo.
echo [0/3] 检查 COM21 是否被旧桥接占用 ...
python -c "import serial; serial.Serial('COM21',9600,timeout=0.2).close()"
if errorlevel 1 goto :busy

echo [1/3] 启动 BLE 桥接（新窗口，勿关闭）...
start "BLE桥接-勿关" cmd /k python "%~dp002_上位机程序\tools\ble_bridge.py" --com COM21 --addr 00:15:83:F0:15:97

echo [2/3] 等待蓝牙链路就绪（最多 45 秒）...
python "%~dp002_上位机程序\tools\wait_link.py" COM20 45
if errorlevel 1 goto :fail

echo.
echo [3/3] 链路 OK，启动游戏（玩家1=蓝牙，玩家2=COM4 有线板）...
cd /d "%~dp002_上位机程序"
python main.py --p1 COM20 --p2 COM4
goto :end

:busy
echo.
echo [提示] COM21 已被占用：可能有一个旧的"BLE桥接"窗口还开着！
echo   请把旧桥接窗口关闭，然后重新双击本脚本。
pause
exit /b 1

:fail
echo.
echo [失败] 45 秒内未收到蓝牙手柄数据：
echo   1) 确认蓝牙板已上电（数码管亮、模块 LED 闪烁）；
echo   2) 蓝牙板断电 3 秒重上电（让模块重新广播）；
echo   3) 仍不行：先"设置-蓝牙-关闭再打开蓝牙"，蓝牙板再断电重上电一次；
echo   4) 重新双击本脚本；仍不行看桥接窗口报错。
pause
goto :eof

:end
echo.
echo 游戏已退出。感谢使用蓝牙手柄！
pause

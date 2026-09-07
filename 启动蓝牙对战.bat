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
echo   [若 45 秒内没连上] 请把蓝牙板断电 3 秒重上电，再重跑本脚本
echo ============================================================

echo.
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

:fail
echo.
echo [失败] 45 秒内未收到蓝牙手柄数据：
echo   1) 确认蓝牙板已上电（数码管亮、模块 LED 闪烁）；
echo   2) 蓝牙板断电 3 秒重上电（让模块重新广播）；
echo   3) 重新双击本脚本；仍不行看桥接窗口报错。
pause
goto :eof

:end
echo.
echo 游戏已退出。感谢使用蓝牙手柄！
pause

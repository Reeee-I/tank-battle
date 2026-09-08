@echo off
chcp 936 >nul
title 蓝牙手柄 - 启动BLE桥接
cd /d "%~dp0"

echo ============================================================
echo   蓝牙手柄 · 启动 BLE 桥接（只开桥接，不开游戏）
echo   --------------------------------------------------------
echo   [前提] 蓝牙板已上电；若刚用过请先断电3秒重上电
echo ============================================================

echo.
echo [1/2] 检查 COM21 是否被旧桥接占用 ...
python -c "import serial; serial.Serial('COM21',9600,timeout=0.2).close()"
if errorlevel 1 goto :busy

echo [2/2] 启动 BLE 桥接窗口（标题为"BLE桥接-勿关"）...
start "BLE桥接-勿关" cmd /k python "%~dp002_上位机程序\tools\ble_bridge.py" --com COM21 --addr 00:15:83:F0:15:97

echo.
echo  等待链路就绪（最多 45 秒）...
python "%~dp002_上位机程序\tools\wait_link.py" COM20 45
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   链路已就绪！请另开一个终端启动游戏：
echo.
echo     cd 02_上位机程序
echo     python main.py --p1 COM20            （玩家2 用键盘）
echo     python main.py --p1 COM20 --p2 COM4  （玩家2 用有线板）
echo.
echo   玩之前请保持 "BLE桥接-勿关" 窗口开着，不要关闭。
echo ============================================================
pause
goto :eof

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
echo   4) 若提示"打开 COM20 失败"：请先打开 VSPD 主界面确认 COM20/21 并点 Apply；
echo   5) 重新双击本脚本。
pause
goto :eof

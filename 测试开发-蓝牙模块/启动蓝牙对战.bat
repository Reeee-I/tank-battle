@echo off
chcp 936 >nul
title 蓝牙对战一键启动（BT05 BLE 桥接）
cd /d "%~dp0"

echo ============================================
echo   蓝牙对战 - 一键启动（玩家1=蓝牙 / 玩家2=有线COM4）
echo   [注意] 请先给蓝牙测试板通电；若 40 秒没连上，
echo          请把蓝牙板断电重上电一次再重跑本脚本。
echo ============================================

echo.
echo [1/3] 启动 BLE 桥接程序（新窗口，勿关闭）...
start "BLE桥接-勿关" cmd /k python "%~dp003_测试工具\ble_bridge.py" --com COM21 --addr 00:15:83:F0:15:97

echo [2/3] 等待蓝牙链路就绪（最多 45 秒）...
python "%~dp003_测试工具\wait_link.py" COM20 45
if errorlevel 1 goto :fail

echo.
echo [3/3] 链路 OK，启动游戏（玩家1=蓝牙手柄，玩家2=有线板 COM4）...
cd /d "%~dp0..\02_上位机程序"
python main.py --p1 COM20 --p2 COM4
goto :end

:fail
echo.
echo [失败] 45 秒内未收到蓝牙手柄数据。
echo   1) 确认蓝牙板已上电（数码管亮、模块 LED 闪烁）；
echo   2) 把蓝牙板断电 3 秒重上电（让模块重新广播）；
echo   3) 然后重新双击本脚本。
echo   另：桥接窗口若报错请把内容发我排查。
pause
goto :eof

:end
echo 游戏已退出。谢谢使用！
pause

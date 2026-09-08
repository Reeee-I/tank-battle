@echo off
chcp 936 >nul
title BLE桥接（蓝牙手柄）- 保持本窗口运行
cd /d "%~dp0"

echo ============================================================
echo   蓝牙手柄 · BLE 桥接（本窗口就是桥接窗口）
echo   --------------------------------------------------------
echo   出现 "notify 已开启" 并开始滚动 aa 01 数据 = 链路就绪
echo   此时可双击 启动游戏.bat 开游戏；玩完关闭本窗口即可
echo ============================================================

echo.
echo 检查 COM21 是否被旧桥接占用 ...
python -c "import serial; serial.Serial('COM21',9600,timeout=0.2).close()"
if errorlevel 1 goto :busy

echo 启动桥接 ...
python "%~dp002_上位机程序\tools\ble_bridge.py" --com COM21 --addr 00:15:83:F0:15:97 --debug

echo.
echo 桥接已退出。
pause
goto :eof

:busy
echo.
echo [提示] COM21 已被占用：请先关闭旧的桥接窗口，再运行本脚本。
pause
exit /b 1

@echo off
title PhiLia093 Bot
echo 正在启动虚拟环境...
cd /d D:\GitHub\PhiLia093_Discord_Bot\Bot\DiscordBot
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo 错误：无法激活虚拟环境，请确保 venv 文件夹存在。
    pause
    exit /b %errorlevel%
)
echo 虚拟环境已激活，正在运行机器人...
python main.py
echo 机器人已停止。
pause
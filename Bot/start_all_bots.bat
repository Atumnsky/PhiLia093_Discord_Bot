@echo off
title Start all bots
echo Starting WhatsApp bot...
start "WhatsappBot" cmd /c "D:\GitHub\PhiLia093_WhatsApp_Bot\Bot\start_W_bot.bat"
echo Starting Discord bot...
start "PhiLia093 Discord" cmd /c "D:\GitHub\PhiLia093_Discord_Bot\Bot\start_D_bot.bat"
echo Both bots launched.
timeout /t 3 >nul
exit

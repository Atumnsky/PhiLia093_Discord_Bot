@echo off
title PhiLia093 Bot
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [error] Python is not installed or not on PATH.
        pause
        exit /b 1
    )
    "venv\Scripts\python.exe" -m pip install --upgrade pip
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [error] Could not install dependencies.
        pause
        exit /b 1
    )
)

echo [run] Starting PhiLia093...
"venv\Scripts\python.exe" main.py
echo.
echo Bot stopped.
pause

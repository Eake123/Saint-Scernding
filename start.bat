@echo off
cd /d "%~dp0"
if not exist .venv (
    echo First run: setting things up...
    py -3.11 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)
.venv\Scripts\python.exe bot.py
pause

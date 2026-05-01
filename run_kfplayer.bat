@echo off
setlocal
cd /d "%~dp0"

if exist env\Scripts\pythonw.exe (
    start "" env\Scripts\pythonw.exe main.py
    exit /b 0
)

if exist .venv\Scripts\pythonw.exe (
    start "" .venv\Scripts\pythonw.exe main.py
    exit /b 0
)

start "" pyw.exe -3 main.py

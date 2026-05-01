@echo off
setlocal
cd /d "%~dp0"

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed in the current Python environment.
    echo.
    echo Build this app from a clean minimal environment, not the 5GB repo env.
    echo Example:
    echo   py -3.12 -m venv C:\kfplayer-build-env
    echo   C:\kfplayer-build-env\Scripts\python -m pip install --upgrade pip
    echo   C:\kfplayer-build-env\Scripts\python -m pip install -r "%~dp0requirements-build.txt"
    echo   C:\kfplayer-build-env\Scripts\pyinstaller "%~dp0KFPlayer.spec" --noconfirm
    exit /b 1
)

pyinstaller "%~dp0KFPlayer.spec" --noconfirm
if errorlevel 1 exit /b %errorlevel%

echo.
echo Build complete: "%~dp0dist\KFPlayer"

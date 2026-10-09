@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Не найдено окружение .venv. Подготовьте его по DEVELOPER.md.
    pause
    exit /b 1
)
if not exist "%~dp0rclone_mega.py" (
    echo Не найден файл rclone_mega.py.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0rclone_mega.py"

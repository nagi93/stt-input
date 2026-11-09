@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo stt-input (Muse Voice Paste) を更新します...

python tools\update.py
if errorlevel 1 (
  echo [エラー] 更新に失敗しました。
  pause
  exit /b 1
)
pause

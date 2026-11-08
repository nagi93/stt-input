@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo stt-input (Muse Voice Paste) をインストールします...

python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [エラー] 依存パッケージのインストールに失敗しました。Python 3.11+ が必要です。
  pause
  exit /b 1
)

rem PCの環境 (GPU/VRAM/RAM/CPU) を見てモデルを選び、config.json へ書き、
rem CUDA ライブラリの導入とモデルの事前ダウンロードまで行う
python tools\setup_env.py
if errorlevel 1 (
  echo [エラー] 環境セットアップに失敗しました。
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo 完了しました。次回ログインから自動起動します。今すぐ使う場合は run.bat を実行してください。
pause

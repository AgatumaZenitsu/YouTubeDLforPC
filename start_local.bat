@echo off
title YouTube DL - Local Server
cls

echo ===================================================
echo   YouTube DL ローカルサーバーを起動しています...
echo   (この画面を閉じるとアプリが終了します)
echo ===================================================
echo.

:: 1. ブラウザでアプリのURLを自動的に開く
echo [1/2] ブラウザを起動しています...
start http://localhost:10000

:: 2. Pythonのバックエンドサーバーを起動
echo [2/2] Pythonサーバーを起動しています...
echo.
python app.py

:: 万が一エラーで落ちた場合に画面をすぐに閉じず、エラー内容を確認できるようにする
if %errorlevel% neq 0 (
    echo.
    echo ⚠️ エラーが発生したためサーバーを停止しました。
    pause
)
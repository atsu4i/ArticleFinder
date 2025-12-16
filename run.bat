@echo off
chcp 65001 > nul
setlocal

REM 論文検索自動化ツール - Windows用起動スクリプト
REM このファイルをダブルクリックして実行してください

echo =========================================
echo   論文検索自動化ツール - 起動中
echo =========================================
echo.

REM スクリプトのディレクトリに移動
cd /d "%~dp0"

REM 仮想環境が存在するか確認
if not exist "venv" (
    echo ❌ エラー: 仮想環境が見つかりません
    echo.
    echo 先に setup.bat を実行してセットアップを完了してください
    echo.
    pause
    exit /b 1
)

REM .envファイルが存在するか確認
if not exist ".env" (
    echo ⚠️  警告: .envファイルが見つかりません
    echo.
    echo .env.exampleをコピーして.envを作成し、
    echo Gemini API Keyを設定してください
    echo.
    pause
    exit /b 1
)

REM 仮想環境を有効化
echo ✓ 仮想環境を有効化中...
call venv\Scripts\activate.bat

REM Streamlitアプリを起動
echo ✓ アプリケーションを起動中...
echo.
echo ブラウザが自動的に開きます
echo 開かない場合は、以下のURLにアクセスしてください:
echo   → http://localhost:8502
echo.
echo アプリを終了するには、このウィンドウで Ctrl+C を押してください
echo.
echo =========================================
echo.

streamlit run main.py --server.port 8502

REM アプリ終了後
echo.
echo アプリケーションを終了しました
pause

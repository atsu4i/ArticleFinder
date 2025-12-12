@echo off
chcp 65001 > nul
setlocal

REM 論文検索自動化ツール - Windows用セットアップスクリプト
REM このファイルをダブルクリックして実行してください

echo =========================================
echo   論文検索自動化ツール - セットアップ
echo =========================================
echo.

REM スクリプトのディレクトリに移動
cd /d "%~dp0"

REM Pythonがインストールされているか確認
echo ✓ Pythonのバージョンを確認中...
python --version > nul 2>&1
if errorlevel 1 (
    echo ❌ エラー: Python 3がインストールされていません
    echo.
    echo Pythonをインストールしてください:
    echo https://www.python.org/downloads/
    echo.
    echo インストール時に「Add Python to PATH」にチェックを入れてください
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo   %PYTHON_VERSION% が見つかりました
echo.

REM 仮想環境が既に存在するか確認
if exist "venv" (
    echo ✓ 既存の仮想環境が見つかりました
    echo.
) else (
    echo ✓ Python仮想環境を作成中...
    python -m venv venv
    if errorlevel 1 (
        echo ❌ エラー: 仮想環境の作成に失敗しました
        echo.
        pause
        exit /b 1
    )
    echo   仮想環境を作成しました
    echo.
)

REM 仮想環境を有効化
echo ✓ 仮想環境を有効化中...
call venv\Scripts\activate.bat

REM 依存パッケージをインストール
echo ✓ 必要なパッケージをインストール中...
echo   (数分かかる場合があります)
echo.
python -m pip install --upgrade pip > nul 2>&1
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ❌ エラー: パッケージのインストールに失敗しました
    echo.
    pause
    exit /b 1
)
echo   すべてのパッケージをインストールしました
echo.

REM .envファイルを作成（存在しない場合）
if not exist ".env" (
    echo ✓ 環境設定ファイル(.env)を作成中...
    copy .env.example .env > nul
    echo   .envファイルを作成しました
    echo.
    echo ⚠️  重要: .envファイルを編集してGemini API Keyを設定してください
    echo    API Keyの取得先: https://makersuite.google.com/app/apikey
    echo.
) else (
    echo ✓ .envファイルは既に存在します
    echo.
)

echo =========================================
echo   ✅ セットアップが完了しました！
echo =========================================
echo.
echo 次のステップ:
echo 1. .envファイルを開いてGemini API Keyを設定
echo 2. run.bat をダブルクリックしてアプリを起動
echo.
pause

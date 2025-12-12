#!/bin/bash

# 論文検索自動化ツール - Mac用セットアップスクリプト
# このファイルをダブルクリックして実行してください

# スクリプトのディレクトリに移動
cd "$(dirname "$0")"

echo "========================================="
echo "  論文検索自動化ツール - セットアップ"
echo "========================================="
echo ""

# Pythonがインストールされているか確認
echo "✓ Pythonのバージョンを確認中..."
if ! command -v python3 &> /dev/null; then
    echo "❌ エラー: Python 3がインストールされていません"
    echo ""
    echo "Pythonをインストールしてください:"
    echo "https://www.python.org/downloads/"
    echo ""
    read -p "Enterキーを押して終了..."
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo "  $PYTHON_VERSION が見つかりました"
echo ""

# 仮想環境が既に存在するか確認
if [ -d "venv" ]; then
    echo "✓ 既存の仮想環境が見つかりました"
    echo ""
else
    echo "✓ Python仮想環境を作成中..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "❌ エラー: 仮想環境の作成に失敗しました"
        echo ""
        read -p "Enterキーを押して終了..."
        exit 1
    fi
    echo "  仮想環境を作成しました"
    echo ""
fi

# 仮想環境を有効化
echo "✓ 仮想環境を有効化中..."
source venv/bin/activate

# 依存パッケージをインストール
echo "✓ 必要なパッケージをインストール中..."
echo "  (数分かかる場合があります)"
echo ""
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "❌ エラー: パッケージのインストールに失敗しました"
    echo ""
    read -p "Enterキーを押して終了..."
    exit 1
fi
echo "  すべてのパッケージをインストールしました"
echo ""

# .envファイルを作成（存在しない場合）
if [ ! -f ".env" ]; then
    echo "✓ 環境設定ファイル(.env)を作成中..."
    cp .env.example .env
    echo "  .envファイルを作成しました"
    echo ""
    echo "⚠️  重要: .envファイルを編集してGemini API Keyを設定してください"
    echo "   API Keyの取得先: https://makersuite.google.com/app/apikey"
    echo ""
else
    echo "✓ .envファイルは既に存在します"
    echo ""
fi

echo "========================================="
echo "  ✅ セットアップが完了しました！"
echo "========================================="
echo ""
echo "次のステップ:"
echo "1. .envファイルを開いてGemini API Keyを設定"
echo "2. run.command をダブルクリックしてアプリを起動"
echo ""
read -p "Enterキーを押して終了..."

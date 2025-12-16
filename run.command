#!/bin/bash

# 論文検索自動化ツール - Mac用起動スクリプト
# このファイルをダブルクリックして実行してください

# スクリプトのディレクトリに移動
cd "$(dirname "$0")"

echo "========================================="
echo "  論文検索自動化ツール - 起動中"
echo "========================================="
echo ""

# 仮想環境が存在するか確認
if [ ! -d "venv" ]; then
    echo "❌ エラー: 仮想環境が見つかりません"
    echo ""
    echo "先に setup.command を実行してセットアップを完了してください"
    echo ""
    read -p "Enterキーを押して終了..."
    exit 1
fi

# .envファイルが存在するか確認
if [ ! -f ".env" ]; then
    echo "⚠️  警告: .envファイルが見つかりません"
    echo ""
    echo ".env.exampleをコピーして.envを作成し、"
    echo "Gemini API Keyを設定してください"
    echo ""
    read -p "Enterキーを押して終了..."
    exit 1
fi

# 仮想環境を有効化
echo "✓ 仮想環境を有効化中..."
source venv/bin/activate

# Streamlitアプリを起動
echo "✓ アプリケーションを起動中..."
echo ""
echo "ブラウザが自動的に開きます"
echo "開かない場合は、以下のURLにアクセスしてください:"
echo "  → http://localhost:8502"
echo ""
echo "アプリを終了するには、このウィンドウで Ctrl+C を押してください"
echo ""
echo "========================================="
echo ""

streamlit run main.py --server.port 8502

# アプリ終了後
echo ""
echo "アプリケーションを終了しました"
read -p "Enterキーを押してウィンドウを閉じる..."

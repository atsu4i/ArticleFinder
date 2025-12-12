# CLAUDE.md

このファイルは、Claude Code によるプロジェクト開発の記録です。

## プロジェクト概要

**PubMed論文検索自動化ツール** - 医学研究における参考文献探しを効率化するツール

### 開発背景

医師が論文を書く際の参考文献探しの課題：
- PubMedで手作業で Similar articles と Cited by を辿る作業が非常に時間がかかる
- 大量の論文タイトルを読んで関連性を判断する必要がある
- 同じ作業を繰り返すと重複チェックが困難

### ソリューション

1. **自動探索**: PubMed API を使って関連論文を再帰的に自動取得
2. **AI評価**: Gemini API でアブストラクトと研究テーマの関連性を自動評価
3. **プロジェクト管理**: 評価済み論文をキャッシュして重複評価を防止

## 技術スタック

### バックエンド
- **Python 3.8+**
- **PubMed E-utilities API**: 論文情報の取得
  - ESummary: メタデータ取得
  - EFetch: アブストラクト取得
  - ELink: 関連論文・引用論文の取得
- **Gemini API (gemini-pro)**: 論文の関連性評価

### フロントエンド
- **Streamlit**: WebベースGUI
  - リアルタイム進捗表示
  - インタラクティブなフィルタリング
  - JSON エクスポート機能

### データ管理
- **ローカルファイルシステム**: プロジェクトデータの永続化
  - `projects/{project_name}/metadata.json`: プロジェクト情報
  - `projects/{project_name}/articles.json`: 評価済み論文データ

## アーキテクチャ

### モジュール構成

```
article_finder.py        # 論文探索のメインロジック
├── pubmed_api.py       # PubMed API 連携
├── gemini_evaluator.py # Gemini AI 評価
└── project_manager.py  # プロジェクト管理

main.py                 # Streamlit WebGUI
```

### データフロー

```
1. ユーザー入力
   ├── 起点論文 (PMID/URL)
   ├── 研究テーマ
   └── 探索設定

2. ArticleFinder.find_articles()
   ├── プロジェクトキャッシュチェック
   ├── PubMed API: 論文情報取得
   ├── Gemini API: 関連性評価（キャッシュ未存在時のみ）
   ├── プロジェクトに保存
   └── 再帰的探索（関連性あり論文のみ）

3. 結果出力
   ├── GUI表示（スコア順ソート）
   ├── JSON エクスポート
   └── プロジェクト保存
```

## 主要機能の実装詳細

### 1. 重複チェック機構

**課題**: 複数回の検索で同じ論文を再評価すると API コストが増大

**解決策**:
- プロジェクトごとに評価済み論文を `articles.json` に保存
- 論文評価前に PMID でキャッシュチェック
- キャッシュヒット時は Gemini API を呼ばずスコアを再利用

```python
# article_finder.py の実装
if project and project.has_article(pmid):
    article = project.get_article(pmid)  # キャッシュから取得
    # スコアは再利用、is_relevant は現在の閾値で再計算
    article["is_relevant"] = article["relevance_score"] >= relevance_threshold
    stats["total_skipped"] += 1
else:
    # 新規評価
    evaluation = self.evaluator.evaluate_relevance(...)
    stats["total_evaluated"] += 1
```

### 2. 関連性閾値の動的再計算

**課題**: 閾値を変更すると、過去の論文が探索対象外のまま残る

**例**:
- 1回目: 閾値80点 → 65点の論文は is_relevant=False
- 2回目: 閾値60点 → 65点の論文は本来 is_relevant=True にすべき

**解決策**:
- `relevance_score` はキャッシュから取得（API コスト削減）
- `is_relevant` は現在の閾値で再計算（柔軟な探索）

```python
score = article.get("relevance_score", 0)
article["is_relevant"] = score >= relevance_threshold  # 現在の閾値で再判定
```

### 3. レート制限対応

**PubMed API**: 1秒に3リクエストまで

```python
# pubmed_api.py
REQUEST_DELAY = 0.34  # 安全のため0.34秒間隔

def _rate_limit(self):
    current_time = time.time()
    time_since_last_request = current_time - self.last_request_time
    if time_since_last_request < self.REQUEST_DELAY:
        time.sleep(self.REQUEST_DELAY - time_since_last_request)
    self.last_request_time = time.time()
```

### 4. 探索アルゴリズム

**幅優先探索**を採用：

```
階層0: 起点論文
  ├── 評価 → is_relevant=True
  └── Similar/Cited by 取得

階層1: 起点論文の関連論文
  ├── 各論文を評価
  ├── is_relevant=True の論文のみ次階層へ
  └── is_relevant=False の論文は打ち切り

階層2: さらに関連論文を探索
  └── max_depth または max_articles に達するまで継続
```

**メリット**:
- 関連性の低い論文の分岐を早期に打ち切り
- 探索範囲の爆発を防止
- より関連性の高い論文に集中

## 設計判断

### なぜ Gemini API を選択したか

1. **コスト**: 無料枠が大きい（GPT-4比）
2. **速度**: 応答が比較的高速
3. **日本語対応**: 日本語の評価理由生成が自然
4. **アクセス性**: API Key の取得が簡単
5. **モデル選択**: 複数のモデルから用途に応じて選択可能

### 利用可能なGeminiモデル

すべて無料枠あり（[公式ドキュメント](https://ai.google.dev/gemini-api/docs/pricing?hl=ja)）

| モデル | 特徴 | 用途 |
|--------|------|------|
| gemini-2.5-flash-preview-09-2025 | 最新プレビュー版（デフォルト） | 推奨、最新機能を試せる |
| gemini-2.5-flash | 最新の安定版高速モデル | バランスの取れた評価 |
| gemini-2.5-flash-lite | 最も高速で低コスト | 大量の論文を超高速処理 |
| gemini-2.5-pro | 最高精度モデル | 複雑な推論、精密な評価 |
| gemini-2.0-flash | 安定版マルチモーダル | 安定性重視の場合 |
| gemini-2.0-flash-lite | 安定版軽量モデル | 安定性とコストのバランス |

### なぜ Streamlit を選択したか

1. **開発速度**: Python のみでWebアプリを迅速に構築
2. **医師向け**: シンプルで直感的なUI
3. **リアルタイム更新**: 進捗表示が容易
4. **デプロイ**: Streamlit Cloud で簡単に公開可能

### プロジェクト管理の実装方法

**選択肢**:
- SQLite データベース
- JSON ファイル（採用）

**JSON を選んだ理由**:
1. **シンプル**: セットアップ不要、ファイルだけで完結
2. **可搬性**: ディレクトリごとコピーで移行可能
3. **可読性**: テキストエディタで直接確認・編集可能
4. **バックアップ**: ファイルシステムのバックアップで十分

## パフォーマンス最適化

### API 呼び出し削減

1. **キャッシュ**: 評価済み論文は再評価しない
2. **バッチ処理なし**: 論文ごとに個別評価（ユーザー要件）
3. **早期終了**: is_relevant=False の論文は次階層探索しない

### 典型的な実行時間

- **50論文、深さ2**: 約5-10分
- **100論文、深さ2**: 約10-20分
- **200論文、深さ3**: 約30-60分

**ボトルネック**:
- PubMed API レート制限（1秒3リクエスト）
- Gemini API 応答時間（1論文あたり1-3秒）

## セキュリティ

### API Key 管理

1. **.env ファイル**: ローカル開発用
2. **環境変数**: 本番デプロイ用
3. **.gitignore**: API Key を含むファイルは除外

### データプライバシー

- **ローカル保存**: 論文データは全てローカルに保存
- **API通信**: PubMed と Gemini のみ
- **個人情報**: 収集・送信しない

## 今後の拡張可能性

### 機能追加候補

1. **他のデータベース対応**:
   - Google Scholar
   - arXiv
   - CiNii

2. **評価モデルの選択**:
   - GPT-4
   - Claude
   - ローカルLLM（Llama など）

3. **可視化機能**:
   - 論文の関連図（ネットワークグラフ）
   - スコア分布のヒストグラム
   - 年代別の論文数推移

4. **エクスポート形式の追加**:
   - CSV
   - Excel
   - BibTeX（参考文献形式）
   - EndNote

5. **協調フィルタリング**:
   - 複数ユーザーの評価を統合
   - コミュニティベースのスコア

6. **自動要約**:
   - 関連論文群の要約レポート生成
   - 研究動向の分析

### アーキテクチャ改善

1. **非同期処理**: asyncio で API 呼び出しを並列化
2. **データベース化**: 大規模プロジェクト向けに SQLite/PostgreSQL 対応
3. **キュー処理**: Celery でバックグラウンド処理
4. **ユニットテスト**: pytest で品質保証

## 開発履歴

### 初期実装（v1.0）
- 基本的な論文探索機能
- Gemini API 評価
- Streamlit GUI

### プロジェクト管理機能追加（v1.1）
- プロジェクト管理モジュール
- 重複チェック機構
- キャッシュシステム

### 閾値動的再計算（v1.2）
- is_relevant の動的再計算
- 閾値変更時の柔軟な探索

## ライセンス

MIT License

## 開発環境

- Python 3.11
- macOS 14.6.0
- Claude Code (Sonnet 4.5)

## 参考資料

- [PubMed E-utilities API Documentation](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [Gemini API Documentation](https://ai.google.dev/)
- [Streamlit Documentation](https://docs.streamlit.io/)

---

Generated with Claude Code

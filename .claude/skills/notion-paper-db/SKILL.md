---
name: notion-paper-db
description: >-
  Notion の論文DB（「論文リスト」）を一括メンテナンスする。プロジェクト(multi_select)の
  一括付与や、PubMedリンク(url)の欠落補完など。登録は通常 ../PaperManager が自動で行うが、
  取りこぼし（プロジェクト未設定・PubMedリンク欠落）を後からまとめて直す用途。
  「Notionのプロジェクトを一括で入れて」「PubMedリンクが空のを埋めて」等で使う。
---

# Notion 論文DB 一括メンテナンス

通常、論文の Notion 登録は `../PaperManager` のアプリが自動で行う。本スキルは**その後の取りこぼし**を
Notion API で一括補修するためのもの（個別手作業の代替）。認証は ArticleFinder と同じ `.env`
（`NOTION_API_KEY` / `NOTION_DATABASE_ID`）を使う。

## 原則（必ず守る）

- **ユーザーの Notion への書き込みは確認してから。** 何を・どの範囲に・どの値で書くかを必ず先に提示する。
- 同梱スクリプトは**既定でドライラン**（対象を表示するだけ）。実行は `--apply` を付けたときだけ。
- まずドライランで対象件数と中身を見せ、ユーザーの了承を得てから `--apply`。
- multi_select の付与は**既存値を保持して追記**（クロバーしない）。
- Notion レート制限に配慮（スクリプトが1件ごとに ~0.35 秒あける）。

## DB のプロパティ（この DB 固有）

`プロジェクト`=multi_select / `PubMed`=url / `DOI`=url / `Title`=title
（変わった場合は `notion_bulk.py` 冒頭の定数を直す）

## 使い方

すべてリポジトリ直下（`.env` のある場所）から実行する。

```bash
# 1) 現状把握（空のプロパティ件数）
python3 .claude/skills/notion-paper-db/notion_bulk.py audit

# 2) プロジェクト未設定のページにラベルを一括付与
#    まずドライラン → 件数と中身を確認 → 了承後 --apply
python3 .claude/skills/notion-paper-db/notion_bulk.py set-project --label "pediatric-onco-nutrition"
python3 .claude/skills/notion-paper-db/notion_bulk.py set-project --label "pediatric-onco-nutrition" --apply

# 3) PubMedリンクが空のページを補完（PMIDは ArticleFinder の articles.json から照合）
#    --label でそのプロジェクトのページに限定できる
python3 .claude/skills/notion-paper-db/notion_bulk.py fill-pubmed \
  --project-dir projects/pediatric-onco-nutrition-ae-pubmed --label "pediatric-onco-nutrition"
python3 .claude/skills/notion-paper-db/notion_bulk.py fill-pubmed \
  --project-dir projects/pediatric-onco-nutrition-ae-pubmed --label "pediatric-onco-nutrition" --apply
```

## 補足

- `set-project` の対象は「`プロジェクト` が空」のページ。バッチ登録直後はこれが今回分と一致しやすい
  （PaperManager 登録分は作成日時も近い）。ドライランで中身を見て、別バッチが混ざっていないか確認する。
- `fill-pubmed` は **DOI 一致 → タイトル一致** の順で PMID を引き当て、**特定できないものは書き込まず報告**する
  （推測でリンクを張らない＝[[pdf-identity-verification]] と同じ思想）。照合不可は手動対応。
- 恒久的には登録側（`../PaperManager`）を直すのが本筋。本スキルは取りこぼしの事後補修用。

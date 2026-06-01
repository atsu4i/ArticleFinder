#!/usr/bin/env python3
"""ArticleFinder の articles.json の `comment` 欄に PDF 取得ステータスを追記する。

ブラウザ（Streamlit の text_area + 保存ボタン）経由より確実かつ低トークン。
ArticleFinder アプリは rerun ごとに articles.json をディスクから読み直すため、
ここでの外部編集は次の操作/リロードで反映され、アプリ側の保存で上書きされない。

使い方:
    python3 .claude/skills/fetch-paper-pdf/record_status.py \
        --project pediatric-onco-nutrition-ae-pubmed \
        --id 34061438 \
        --status "📄 PDF取得済み (2026-05-31)"

--id は PMID / DOI / article_id(pmid:.. , doi:..) のいずれでも可。
既存コメントは保持し、同一ステータス行が無ければ末尾に追記する（冪等）。
書き込みは tmp + os.replace でアトミックに行う。
"""
import argparse
import json
import os
import sys
import tempfile


def candidate_keys(identifier: str):
    identifier = str(identifier).strip()
    keys = [identifier]
    if identifier.startswith(("pmid:", "doi:")):
        return keys
    if identifier.isdigit():
        keys.append(f"pmid:{identifier}")
    else:
        keys.append(f"doi:{identifier}")
    return keys


def find_article_id(articles: dict, identifier: str):
    # 1) 候補キーで直接ヒット
    for key in candidate_keys(identifier):
        if key in articles:
            return key
    # 2) フォールバック: pmid / doi フィールドで照合
    ident = str(identifier).strip().removeprefix("pmid:").removeprefix("doi:")
    for aid, art in articles.items():
        if str(art.get("pmid", "")) == ident or str(art.get("doi", "")) == ident:
            return aid
    return None


def main():
    ap = argparse.ArgumentParser(description="ArticleFinder の comment にステータスを追記")
    ap.add_argument("--project", required=True, help="プロジェクト名（projects/ 配下）")
    ap.add_argument("--id", required=True, help="PMID / DOI / article_id")
    ap.add_argument("--status", required=True, help="追記するステータス行")
    ap.add_argument("--root", default=".", help="リポジトリルート（既定: カレント）")
    args = ap.parse_args()

    path = os.path.join(args.root, "projects", args.project, "articles.json")
    if not os.path.exists(path):
        sys.exit(f"NOT_FOUND: {path}")

    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    aid = find_article_id(articles, args.id)
    if aid is None:
        sys.exit(f"ARTICLE_NOT_FOUND: id={args.id}")

    art = articles[aid]
    existing = (art.get("comment") or "").rstrip()
    status = args.status.strip()

    if status in existing:
        print(f"SKIP (already present): {aid}")
        return

    art["comment"] = f"{existing}\n{status}".strip() if existing else status

    dir_ = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    print(f"OK: {aid} <- {status!r}")


if __name__ == "__main__":
    main()

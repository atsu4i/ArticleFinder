#!/usr/bin/env python3
"""Notion 論文DB（「論文リスト」）の一括メンテナンス。

ArticleFinder と同じ .env（NOTION_API_KEY / NOTION_DATABASE_ID）を使う。
PaperManager が自動登録した後の取りこぼし（プロジェクト未設定・PubMedリンク欠落）を補修する用途。

安全策: 既定は **ドライラン**（対象を表示するだけ）。実際に書き込むには --apply を付ける。
Notion レート制限に配慮し、書き込みは 1件ごとに ~0.35 秒あける。

サブコマンド:
  audit
      プロジェクト空 / PubMed空 のページ数を表示。
  set-project --label "<名前>" [--apply]
      「プロジェクト」(multi_select) が空のページに <名前> を付与（既存値があれば追記、無ければ作成）。
  fill-pubmed --project-dir projects/<name> [--label "<名前>"] [--apply]
      「PubMed」(url) が空のページに、ArticleFinder の articles.json から PMID を引き当てて
      https://pubmed.ncbi.nlm.nih.gov/{PMID}/ を設定。--label でそのプロジェクトのページに限定。
      DOI 一致 → タイトル一致 の順で照合し、特定できないものは書き込まず報告する（推測しない）。

Notion 側のプロパティ名（この DB 固有）:
  プロジェクト=multi_select, PubMed=url, DOI=url, Title=title
"""
import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

PROP_PROJECT = "プロジェクト"
PROP_PUBMED = "PubMed"
PROP_DOI = "DOI"
PROP_TITLE = "Title"
NV = "2022-06-28"
RATE = 0.35


def load_env(env_path):
    env = {}
    for line in Path(env_path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    key, db = env.get("NOTION_API_KEY"), env.get("NOTION_DATABASE_ID")
    if not key or not db:
        raise SystemExit(f"NOTION_API_KEY / NOTION_DATABASE_ID が {env_path} に見つかりません")
    return key, db


def headers(key):
    return {"Authorization": f"Bearer {key}", "Notion-Version": NV, "Content-Type": "application/json"}


def query_all(key, db, filt):
    out, cur = [], None
    while True:
        payload = {"page_size": 100}
        if filt:
            payload["filter"] = filt
        if cur:
            payload["start_cursor"] = cur
        req = urllib.request.Request(
            f"https://api.notion.com/v1/databases/{db}/query",
            data=json.dumps(payload).encode(), method="POST", headers=headers(key))
        d = json.load(urllib.request.urlopen(req, timeout=20))
        out += d["results"]
        if not d.get("has_more"):
            return out
        cur = d["next_cursor"]


def patch(key, page_id, props):
    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{page_id}",
        data=json.dumps({"properties": props}).encode(), method="PATCH", headers=headers(key))
    urllib.request.urlopen(req, timeout=20)


def title_of(pg):
    return "".join(t.get("plain_text", "") for t in pg["properties"].get(PROP_TITLE, {}).get("title", []))


def ndoi(d):
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (d or "").strip().lower())


def ntitle(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def cmd_audit(key, db, args):
    empty_proj = query_all(key, db, {"property": PROP_PROJECT, "multi_select": {"is_empty": True}})
    empty_pm = query_all(key, db, {"property": PROP_PUBMED, "url": {"is_empty": True}})
    print(f"プロジェクト空: {len(empty_proj)} 件")
    print(f"PubMed空:      {len(empty_pm)} 件")


def cmd_set_project(key, db, args):
    pages = query_all(key, db, {"property": PROP_PROJECT, "multi_select": {"is_empty": True}})
    print(f"対象（プロジェクト空）: {len(pages)} 件 → '{args.label}' を付与")
    if not args.apply:
        for pg in pages[:10]:
            print("  -", title_of(pg)[:60])
        print("（ドライラン。書き込むには --apply）")
        return
    ok, ng = 0, []
    for pg in pages:
        cur = [o["name"] for o in pg["properties"].get(PROP_PROJECT, {}).get("multi_select", [])]
        if args.label not in cur:
            cur.append(args.label)
        try:
            patch(key, pg["id"], {PROP_PROJECT: {"multi_select": [{"name": n} for n in cur]}})
            ok += 1
        except urllib.error.HTTPError as e:
            ng.append((title_of(pg)[:40], e.code))
        time.sleep(RATE)
    print(f"成功: {ok} / {len(pages)}")
    if ng:
        print("失敗:", ng)


def cmd_fill_pubmed(key, db, args):
    live = json.load(open(Path(args.project_dir) / "articles.json", encoding="utf-8"))
    by_doi, by_title = {}, {}
    for a in live.values():
        pm = a.get("pmid")
        if not pm:
            continue
        if a.get("doi"):
            by_doi[ndoi(a["doi"])] = pm
        if a.get("title"):
            by_title[ntitle(a["title"])] = pm
    filt = {"property": PROP_PUBMED, "url": {"is_empty": True}}
    if args.label:
        filt = {"and": [{"property": PROP_PROJECT, "multi_select": {"contains": args.label}}, filt]}
    pages = query_all(key, db, filt)
    print(f"対象（PubMed空{('・'+args.label if args.label else '')}）: {len(pages)} 件")
    resolved, unmatched = [], []
    for pg in pages:
        doi = pg["properties"].get(PROP_DOI, {}).get("url") or ""
        pm = (by_doi.get(ndoi(doi)) if doi else None) or by_title.get(ntitle(title_of(pg)))
        (resolved if pm else unmatched).append((pg, pm))
    print(f"  PMID特定: {len(resolved)} / 照合不可: {len(unmatched)}")
    for pg, _ in unmatched:
        print("   x", title_of(pg)[:60])
    if not args.apply:
        print("（ドライラン。書き込むには --apply）")
        return
    ok, ng = 0, []
    for pg, pm in resolved:
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pm}/"
        try:
            patch(key, pg["id"], {PROP_PUBMED: {"url": url}})
            ok += 1
        except urllib.error.HTTPError as e:
            ng.append((title_of(pg)[:40], e.code))
        time.sleep(RATE)
    print(f"成功: {ok} / {len(resolved)}")
    if ng:
        print("失敗:", ng)


def main():
    ap = argparse.ArgumentParser(description="Notion 論文DB 一括メンテナンス（既定ドライラン）")
    ap.add_argument("--env", default=".env", help="認証情報の .env パス（既定: ./.env）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit")
    sp = sub.add_parser("set-project")
    sp.add_argument("--label", required=True)
    sp.add_argument("--apply", action="store_true")
    fp = sub.add_parser("fill-pubmed")
    fp.add_argument("--project-dir", required=True, help="ArticleFinder のプロジェクトディレクトリ（articles.json を含む）")
    fp.add_argument("--label", default=None, help="このプロジェクトラベルのページに限定")
    fp.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    key, db = load_env(args.env)
    {"audit": cmd_audit, "set-project": cmd_set_project, "fill-pubmed": cmd_fill_pubmed}[args.cmd](key, db, args)


if __name__ == "__main__":
    main()

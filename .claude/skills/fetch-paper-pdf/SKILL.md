---
name: fetch-paper-pdf
description: >-
  ArticleFinder の論文から、機関認証経由で論文 PDF を半自動取得する。Chrome DevTools
  MCP（MCP専用Chrome 9222 接続）でブラウザを操作し、DOI機関プロキシリンク →
  出版社ページ → PDF実体URL を辿って ~/Downloads に保存し、file コマンドで検証する。
  「この論文のPDFを取って」「ArticleFinderからPDFを落として」「全文PDFを保存して」
  のような依頼で使う。ユーザーが正当にアクセス権を持つ論文のみが対象。
---

# 論文 PDF 取得（ArticleFinder + Chrome DevTools MCP）

ArticleFinder（`http://localhost:8502`）の論文から、機関認証を通して論文 PDF を取得する手順。
詳細な背景は `PDF_DOWNLOAD_AGENT_GUIDE.md` を参照。

## 原則（必ず守る）

- ユーザーが正当にアクセス権を持つ論文のみを対象にする。
- 機関認証・2FA・Cloudflare・ScienceDirect の人間確認は**ユーザー本人**が通す。Agent は通さない。
- Paywall・CAPTCHA・DRM・アクセス制限の**回避はしない**。表示済みページの通常操作と、取得可能な PDF の保存だけを行う。

## 省トークン運用（重要）

ブラウザ系ツールの**戻り値**がトークンの主因。確実性を保ったまま、以下を徹底する。

- **論文の特定・メタdata取得は UI スナップショットでなく JSON を Python で読む**。`take_snapshot` で論文一覧を撮らない。PMID/DOI/著者/年/タイトルは `articles.json`（または渡されたリスト）からスクリプトで抽出する（ファイル本体はコンテキストに入らない）。
- **`list_pages` / `select_page` を多用しない**。これらは全タブのURLを毎回フル出力する。特に ScienceDirect の署名付きPDF URL は1本で約2,500字。`new_page` / `navigate_page` の戻り値で足りる場面では呼ばない。
- **使い終わったタブは `close_page` で閉じる**。タブが残ると以後の列挙出力が膨らむ。ただしユーザーが元から開いていたタブは閉じない（自分が開いたタブのみ）。
- **確認用スクリーンショットは撮らない**。PDFか否かは `fetch` 戻り値（`contentType: application/pdf` と `bytes`）＋ `file` コマンドで確証できる。
- **定型出版社（Wiley/Springer/T&F）は記事ページを snapshot せず、DOIから PDF実体URLへ直行**して fetch する（出版社別プレイブック参照）。
- **snapshot が避けられない時（ScienceDirect の View PDF 特定など）は必ず `filePath` 保存 → `grep` で必要行だけ抽出**。インライン返却しない。

### 理想の最小フロー（Wiley 等の定型出版社）

1. リスト/JSON から DOI・著者・年・index を Python で取得（Bash、安い）
2. `new_page` で `…/doi/{doi}`（同一オリジンのタブ1枚）
3. `evaluate_script` で PDF実体URL を fetch → 命名規則のファイル名で保存（戻り値でPDF確認）
4. `file` で検証 → `record_status.py` で記録
5. `close_page` でタブを閉じる

→ snapshot 0・screenshot 0・list_pages 0。ScienceDirect だけは View PDF クリックのため grep 経由の snapshot 1回が要る。

## 入力：取得対象リスト

複数論文をまとめて処理する場合、ArticleFinder の「📥 フィルタ後データをダウンロード」JSON（または PMID/DOI の素のリスト）を受け取るのが効率的。

- **渡された JSON も `Read` で丸読みしない**。アブストラクト等で重い。`python3` / `jq` で `index・pmid・doi・著者・年・タイトル・comment` だけ抽出する。
- 配列の並び順を `[N]`（ファイル名のリスト番号）として使える。
- 抽出した対象を 1 件ずつ「取得 → `file` 検証 → `record_status.py` 記録 → タブを閉じる」で回す。

### 既取得・既試行の振り分け（ブラウザを開く前に）

リストには取得済みの論文も混ざる。`comment` マーカーで分類し、**取得済みはタブを開かない**（重複取得・トークン浪費の防止）。フィルタ後エクスポートは `comment` を含むので、抽出時に一緒に読む。

| `comment` | 扱い |
|---|---|
| `📄 PDF取得済み` を含む | スキップ |
| `🚫 PDF取得不可` を含む | 既定でスキップ（ユーザーが明示したら再試行） |
| `⚠️ PDF取得失敗：人間認証が必要` を含む | 再試行候補（認証が通っている可能性） |
| `⚠️ PDF取得失敗：…`（その他） | 再試行候補 |
| 空 / null | 新規取得 |

処理前に件数サマリ（取得済み／取得不可／要再試行／新規）を出してユーザーに確認する。`record_status.py` も冪等なので二重の安全網になる。

## 0. Preflight（毎回最初に確認）

1. MCP専用Chrome が 9222 で生きているか確認する。

   ```bash
   curl -s --max-time 3 http://127.0.0.1:9222/json/version
   ```

   `webSocketDebuggerUrl` が返らなければ未起動。次のコマンドで起動するようユーザーに案内する（`! <cmd>` でその場実行可）。

   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --remote-debugging-port=9222 \
     --user-data-dir="$HOME/chrome-mcp-profile" \
     --profile-directory="Default" --no-first-run --no-default-browser-check
   ```

2. `list_pages` を実行。`localhost:8502` 等のタブが見えれば接続OK。
   `about:blank` しか見えない場合は 9222 に繋がっていない（`.mcp.json` の `--browser-url=http://127.0.0.1:9222` とプラグイン無効化を確認 → Claude Code 再起動）。

3. 対象論文の「📝 メモ・コメント」欄をスナップショットで確認。すでに `📄 PDF取得済み` が入っていれば**スキップ**（重複取得を避ける）。

## 1. ArticleFinder から出版社ページへ

1. `localhost:8502` のタブを `select_page` で選ぶ。
2. `take_snapshot` で論文一覧を取得。対象論文の **DOI機関プロキシリンク**（「🔗 {doi} (機関プロキシ)」）を `click`。
   - 出版社ページが**新しいタブ**で開く。`list_pages` で新タブの URL を確認する。
3. 新タブを `select_page`。`wait_for`（["PDF","Abstract"] 等）で読み込み完了を待つ。
   - スナップショットが巨大なら `take_snapshot` の `filePath` でリポジトリ内に保存し、`grep` で PDF/View リンクだけ抽出する（作業後に削除）。
   - `cra_js_challenge` / `Just a moment` / CAPTCHA が出たら、**ユーザーに人間確認を依頼**して中断する。

## 2. PDF実体URLまで到達 → 保存

PDF実体URLが開いているタブ（同一オリジン）で、`evaluate_script` により取得して保存する。

> **注意:** `?download=true` のような添付ダウンロード用URLへ `navigate_page` で直接遷移しない。`ERR_ABORTED` になり、出版社既定名の重複ファイルが勝手に落ちる。必ず下記の `fetch` で取得し、`download` 属性で**自分が決めたファイル名**で保存する。`fetch` する URL 自体は `?download=true` 付きでよい。

```js
async () => {
  const url = location.href;
  const res = await fetch(url, { credentials: "include" });
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "<ファイル名>.pdf";   // 命名規則は下記
  document.body.appendChild(a); a.click(); a.remove();
  return { status: res.status, contentType: res.headers.get("content-type"), bytes: blob.size };
}
```

`contentType` が `application/pdf` で `bytes` が妥当なら成功。ファイルは MCP専用Chrome の既定ダウンロード先（通常 `~/Downloads`）に落ちる。

### ファイル名の規則

`{リスト番号}_{筆頭著者の姓}_{出版年}_{内容キーワード}.pdf`

- **リスト番号**: ArticleFinder の論文一覧での `[N]`（ダウンロード時点の表示順。フィルタで変わる点は許容）。
- **筆頭著者の姓**: `authors` 先頭の姓。スペースは詰める（例: `Roy Moulik` → `RoyMoulik`）。
- **出版年**: `pub_year`。
- **内容キーワード**: タイトルを要約した英小文字スネークケース 3〜5語（機械的な先頭N語ではなく要点を拾う）。
- 記号・空白・日本語はファイル名に使わない（英数字とアンダースコアのみ）。

例:

```text
10_RoyMoulik_2018_folate_deficiency_ALL_maintenance.pdf
11_Withey_2025_ferritin_folate_childhood_cancer.pdf
```

## 3. 検証

```bash
file ~/Downloads/<ファイル名>.pdf
```

`PDF document` なら成功。`HTML document` なら削除し、出版社別プレイブックに従って別ルートで再試行する。

## 4. 取得結果を articles.json に記録（毎回）

取得を試みた論文は、成否にかかわらず結果を `comment` 欄に残す。後からユーザーが取得状況を追えるようにするため。

**ブラウザのメモ欄操作はしない。** 同梱スクリプトで `projects/{project}/articles.json` を直接編集する（確実かつ低トークン）。ArticleFinder アプリは rerun ごとに articles.json を読み直すため、外部編集は次の操作/リロードでメモ欄に反映され、アプリ側の保存で上書きされない（書き込みは `os.replace` でアトミック）。

```bash
python3 .claude/skills/fetch-paper-pdf/record_status.py \
  --project <プロジェクト名> \
  --id <PMID または DOI> \
  --status "<ステータス文言>"
```

- `--id` は PMID / DOI / `pmid:..` / `doi:..` いずれも可。
- 既存コメントは保持して末尾に追記。同一ステータスが既にあればスキップ（冪等）。

ステータス文言（先頭に絵文字マーカー、`(YYYY-MM-DD)` を添える）:

| 状況 | 文言 |
|------|------|
| 取得成功 | `📄 PDF取得済み (2026-05-31)` |
| 人間確認が必要で失敗 | `⚠️ PDF取得失敗：人間認証が必要 (2026-05-31)` |
| 機関アクセス権なし | `🚫 PDF取得不可：機関アクセス権なし (2026-05-31)` |
| その他の失敗 | `⚠️ PDF取得失敗：<理由> (2026-05-31)` |

複数論文を処理する場合も、1件ごとに「取得 → 記録」をセットで行う。処理後はユーザーに、メモ欄反映にはプロジェクト再選択（リロード）が必要と伝える。

## 出版社別プレイブック

| 出版社 | PDF実体への到達方法 |
|--------|--------------------|
| **Wiley** | 論文ページの `Download PDF`、または `/doi/pdfdirect/{doi}?download=true` に直接遷移すると PDF 本体。`fetch` でそのまま取得できることが多い。 |
| **ScienceDirect / Elsevier** | 一番失敗しやすい。`pdfft` URL を**直接 fetch しない**（HTML が返る）。本文ページの **`View PDF` を通常クリック** → `pdf.sciencedirectassets.com/.../main.pdf` の実体URLまで遷移してから保存する。 |
| **Springer / Nature** | `Download PDF` または `citation_pdf_url`。`link.springer.com/content/pdf/{doi}.pdf` / `www.nature.com/articles/{id}.pdf`。 |
| **Taylor & Francis** | `/doi/epdf/...` は HTML ビューア。PDF 本体は `/doi/pdf/{doi}?download=true`。 |

## 後始末

デバッグ用に保存したスナップショットファイル等は作業後に削除する。
ユーザーが「全部落として」等と言わない限り、対象は明示された論文のみに留める。

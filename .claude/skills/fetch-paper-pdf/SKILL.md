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

## アクセス礼儀（レート・重要）

機械的・系統的ダウンロードと疑われると、機関単位でブロックされる恐れがある（特に Elsevier/ScienceDirect・Wiley/Atypon）。**バーストを避け、人間的なペースで取得する**こと。

- **1件取得するごとに待機を入れる**（ランダム化、目安 5〜15秒）。短時間に多数を連続取得しない。
- **1スクリプトで多数を高速 fetch しない**（旧版の「Wiley一括15件を0.7秒間隔」のようなバーストは禁止）。たとえ origin が複数DL許可済みでも、1件ずつ待機して取得する。
- 可能なら **navigate / クリックを挟んだ人間的ペース**を優先（fetch連打にしない）。
- ScienceDirect・Wiley など検知が厳しい先では間隔を広めにとる。
- 日次上限や複数日分散は必須としない（手動利用と同程度の量なら問題になりにくい、というユーザー方針）。ただし**明らかに過大な一括取得は避ける**。
- 取得後に図書館/機関からアクセス制限・警告が来ていないか、ユーザーが気づける形で進める。

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

**⚠️ 同一性の検証（必須）。** `content-type: application/pdf` ＋サイズだけでは**別論文の有効なPDF**を取り違えても通ってしまう（実害発生済み: 引用文献のPDFを誤取得）。次のいずれかで取得対象と一致するか確認する：

- 取得元URLに**対象の識別子が含まれるか**（SDなら asset URL に記事の `pii`、出版社なら DOI）。fetch 前に必ずチェックする。
- 取得後に PDF の埋め込みメタを確認：`pdfinfo file.pdf | grep -iE 'Title|Subject'` や `mdls -name kMDItemTitle file.pdf` が**対象のタイトル/DOI/PIIと整合**するか。少しでも疑わしければ破棄して取り直す。

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

DOIプロキシ（`https://doi-org.<proxy>/{doi}`）へ navigate すると、出版社のプロキシ origin の記事ページに着く。そこから下記で PDF 実体を取得。**navigate ごとに複数DL制限がリセット**される点を利用する。

| 出版社 | PDF実体への到達方法（2026-06 実証済み） |
|--------|--------------------|
| **Atypon系（Wiley / ASCO / ACS journals / JPEN等）** | 記事ページと**同一オリジン**で `${location.origin}/doi/pdfdirect/{doi}?download=true` を `fetch`。`<>()` を含む特殊文字DOIは `location.pathname.replace("/doi/","/doi/pdfdirect/")+"?download=true"` で構築（DOIを手で組まない）。複数件でも**1件ずつ・間に待機**（アクセス礼儀参照）。1スクリプトでの高速一括 fetch はしない。 |
| **ScienceDirect / Elsevier** | 最難。`pdfft` を**直接 fetch しない**（HTMLが返る）。記事ページの `citation_pdf_url`(=pdfft) へ **`location.href=` でJSページ遷移** → `crasolve` チャレンジが**自動通過**し `pdf.sciencedirectassets.com/.../main.pdf` に着く → そのタブで `fetch(location.href)` して保存。`linkinghub-elsevier-com` 経由で止まったら `www-sciencedirect-com/.../pii/{PII}` に直接 navigate。旧誌（AJCN等）がSDに載っている場合も同様。**⚠️ 重要:** 記事ページの**参考文献・関連論文セクションにも `pdfft`/「View PDF」リンクが多数ある**。`citation_pdf_url` が無い古い論文で「最初に見つかった pdfft アンカー」を拾うと**引用文献の別PDFを取得してしまう**（実害発生済み）。必ず **記事自身の pii（`location.pathname` の `/pii/{PII}`）に一致する** View PDF を選ぶこと。 |
| **Springer / BMC** | `${springer-proxy}/content/pdf/{doi}.pdf` を `fetch`（`10.1007` / `10.1186`）。新規originは複数DLブロックされるので **reload→1件** で回す。 |
| **MDPI** | `citation_pdf_url`（`{article}/pdf?version=..`）へ **navigate** すると添付DL（`ERR_ABORTED`）が発火 → `~/Downloads` の既定名ファイルを命名規則にリネーム。 |
| **LWW (journals.lww.com)** | GET遷移は記事へ戻される。記事ページHTMLから `downloadpdf.aspx?...&an={AN}` URL（または `an=` 値）を抽出し、記事ページ上で **`window.open(url)`** → ポップアップ扱いで添付DL発火 → リネーム。 |
| **PLOS** | `${origin}/{journal}/article/file?id={doi}&type=printable` を `fetch`（OA）。 |
| **Dove Press** | 記事ページの `/article/download/{id}` アンカーを `fetch`（OA）。 |
| **ecancer** | 記事URL + `/pdf` を `fetch`（OA）。 |
| **APJCP (waocp) 等のOA誌** | `citation_pdf_url` かページ内の `.pdf` アンカーを `fetch`。 |
| **Taylor & Francis** | `/doi/pdf/{doi}?download=true`。ただし機関契約が無いと不可（その場合は `🚫 取得不可`）。 |

### 汎用フォールバック（出版社不明時）

記事ページで evaluate_script を1回：`meta[name="citation_pdf_url"]` → 同一オリジンの `/doi/pdfdirect/{doi}?download=true` → ページ内の `.pdf`/「Download PDF」アンカー、の順に `fetch` を試す。`content-type` が `application/pdf` かつ `size>10000` を成功条件にする（スナップショット不要）。

### 取得不可と判断する条件

PDF URLが記事ページ（HTML）にリダイレクトされる／`fetch` がHTMLを返し続ける場合は**機関アクセス無し**。メール登録やアカウント必須（例: Cureus）も不可。これらは `🚫 PDF取得不可：理由` で記録し、深追いしない。

## DOIなしの論文

ArticleFinder で `doi` が空でも、諦める前に PubMed 本体を確認する。**ArticleFinder が DOI を取りこぼしているだけ**のことが多い（今回 6件中 5件に PubMed 側 DOI が存在した）。

1. **PubMed の ArticleId を確認**（DOI や PMC が無いか）。E-utilities は API なので低コスト：

   ```bash
   curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={PMID}&rettype=xml" \
     | grep -oE '<ArticleId IdType="[^"]+">[^<]+</ArticleId>' | sed 's/<[^>]*>/ /g'
   ```

   - **DOI が見つかれば** → 出版社別プレイブックで取得。見つけた DOI は articles.json の `doi` 欄に補完しておくと今後のリンク生成に効く（`os.replace` でアトミックに、既存DOIは上書きしない）。
   - DOI の HTML実体参照（`&lt; &gt;`）は `< >` にデコードして保存する。

2. **PMC（無料全文）を確認**：

   ```bash
   curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&db=pmc&id={PMID}&retmode=json"
   ```

   `pubmed_pmc` リンクがあれば、Europe PMC の直リン（`https://europepmc.org/articles/PMC{id}?pdf=render`）か PMC ページから取得。

3. **OA誌は機関認証不要**。SciELO（`10.1590`）等は記事ページの `?format=pdf` / `citation_pdf_url` を**プロキシを経由せず直接** `fetch` できる。

4. DOIもPMCも無く、本文サイトにも到達手段が無い（例: `AT9847` のような出版社内部IDのみ）場合は `🚫 PDF取得不可：DOI/PMCなし・経路無し` で記録する。

## 後始末

デバッグ用に保存したスナップショットファイル等は作業後に削除する。
ユーザーが「全部落として」等と言わない限り、対象は明示された論文のみに留める。

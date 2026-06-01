# Agentic PDF Download Guide

ArticleFinder の機関リンクから、Codex などの agentic AI が Chrome DevTools MCP 経由で論文 PDF を半自動取得するための手順です。

## 前提

- ユーザーが正当にアクセス権を持つ論文のみを対象にする。
- 機関認証、2FA、Cloudflare などの人間確認はユーザー本人が通す。
- Agent は、表示済みページの通常操作、PDFリンク探索、取得可能なPDFの保存だけを行う。
- Paywall、CAPTCHA、DRM、アクセス制限の回避は行わない。

## 推奨構成

通常Chromeとは別に、MCP専用Chromeプロファイルを用意する。

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-mcp-profile" \
  --profile-directory="Default" \
  --no-first-run \
  --no-default-browser-check
```

接続確認:

```bash
curl http://127.0.0.1:9222/json/version
```

`webSocketDebuggerUrl` が返れば Chrome 側は起動できている。

## Codex MCP設定

`~/.codex/config.toml` の `chrome-devtools` 設定を、既存Chromeへ接続する形にする。

```toml
[mcp_servers.chrome-devtools]
command = "npx"
args = ["-y", "chrome-devtools-mcp@latest", "--browser-url=http://127.0.0.1:9222"]
```

設定変更後は Codex を再起動する。反映されていれば、Agent が `list_pages` したときに、MCP専用Chromeで開いているタブが見える。

## Claude Code MCP設定

Claude Code でも同じことができる（2026-05-31 に Wiley・ScienceDirect で動作確認済み）。プロジェクト単位で管理するため、リポジトリ直下に `.mcp.json` を置く。

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": [
        "chrome-devtools-mcp@latest",
        "--browser-url=http://127.0.0.1:9222"
      ]
    }
  }
}
```

注意点:

- Chrome DevTools MCP を**プラグイン**として入れている場合、プラグインの起動引数には `--browser-url` が付かず、MCP専用Chrome（9222）ではなく自前の使い捨て Chrome を起動してしまう。上記 `.mcp.json` を置いたうえで、プロジェクトの `.claude/settings.json` でプラグインをこのプロジェクトのみ無効化すると、ツールの二重起動を防げる。

  ```json
  {
    "enabledPlugins": {
      "chrome-devtools-mcp@chrome-devtools-plugins": false
    }
  }
  ```

- 設定変更後は Claude Code を再起動する。`list_pages` で MCP専用Chromeのタブ（`localhost:8502` など）が見えれば接続成功。`about:blank` しか見えない場合は 9222 に繋がっていない。
- 保存は、PDF実体URLが開いているタブで `fetch(location.href, {credentials:"include"})` → Blob → `<a download>` クリックで発火させると、MCP専用Chromeの既定ダウンロード先（通常 `~/Downloads`）に保存される。保存後は `file` でPDFか確認する。

## 通常Chromeとの併用

macOS の `open -a "Google Chrome"` は、既に起動中のChromeプロセスに吸われることがある。通常プロファイルとMCP専用プロファイルを併用する場合は、次の順番が安定する。

1. 普段使いChromeを通常起動する。
2. MCP専用Chromeを上記コマンドで起動する。

すでにMCP専用Chromeだけが起動していて通常Chromeが開けない場合は、いったんChromeをすべて終了し、通常Chromeを先に起動してからMCP専用Chromeを起動する。

通常プロファイルを明示して起動する例:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir="$HOME/Library/Application Support/Google/Chrome" \
  --profile-directory="Default" \
  --new-window
```

同じ `user-data-dir` を複数のChromeプロセスで同時に使わない。

## 初回準備

MCP専用Chromeで次を済ませる。

1. `http://localhost:8502` を開く。
2. ArticleFinder の対象プロジェクトを開く。
3. 機関プロキシ設定が入っていることを確認する。
4. DOIリンクまたはArticle Linkerから機関認証を通す。
5. ScienceDirect などで人間確認が出た場合は、ユーザー本人が通す。

この状態を `~/chrome-mcp-profile` に維持する。同じ `--user-data-dir` を使えば、Cookieや通過済み状態が残る。

## Agentの基本操作

1. ArticleFinder の論文一覧で対象論文を開く。
2. DOI機関プロキシリンクをクリックする。
3. 出版社ページで次の表示を確認する。
   - `Full Access`
   - `Open access`
   - `Download PDF`
   - `View PDF`
   - `PDF`
4. PDFリンクを通常クリックする。
5. PDFビューアまたはPDF実体URLが開いたら保存する。
6. `~/Downloads` で `file` コマンドによりPDFであることを確認する。

確認例:

```bash
file ~/Downloads/target.pdf
```

PDFではなくHTMLが保存された場合は削除し、PDF実体URLまたは別のPDFリンクで再試行する。

### ファイル名の規則

後から内容を見分けやすいよう、次の規則で保存する。

```text
{リスト番号}_{筆頭著者の姓}_{出版年}_{内容キーワード}.pdf
```

- リスト番号: ArticleFinder の論文一覧での `[N]`
- 筆頭著者の姓: `authors` 先頭の姓（スペースは詰める。`Roy Moulik` → `RoyMoulik`）
- 出版年: `pub_year`
- 内容キーワード: タイトルを要約した英小文字スネークケース 3〜5語
- 記号・空白・日本語は使わず、英数字とアンダースコアのみ

例:

```text
10_RoyMoulik_2018_folate_deficiency_ALL_maintenance.pdf
11_Withey_2025_ferritin_folate_childhood_cancer.pdf
```

## 取得結果の記録

どの論文を取得済み（または取得失敗・取得不可）かを後から追えるよう、取得を試みた論文は ArticleFinder の「📝 メモ・コメント」欄に結果を残す。

記録は、ブラウザでメモ欄を操作するのではなく **`projects/{project}/articles.json` の `comment` フィールドを直接編集する**のが確実かつ低コスト。理由:

- ArticleFinder（Streamlit）は rerun のたびに articles.json をディスクから読み直す。したがって外部からの編集は次の操作/リロードでメモ欄に反映され、アプリ側のメモ保存で上書きされることもない。
- Streamlit の text_area + 保存ボタン経由は、論文件数が増えると挙動が不安定になりがちで、巨大なページスナップショットでトークン消費も大きい。

`articles.json` はトップレベルが `pmid:<PMID>` / `doi:<DOI>` をキーにした辞書で、各論文に `comment` 欄がある。書き込みは `os.replace` でアトミックに行い、既存コメントは保持して末尾に追記する。

Claude Code では同梱スクリプトを使う:

```bash
python3 .claude/skills/fetch-paper-pdf/record_status.py \
  --project <プロジェクト名> --id <PMID/DOI> --status "📄 PDF取得済み (YYYY-MM-DD)"
```

ステータス文言の例:

```text
📄 PDF取得済み (2026-05-31)
⚠️ PDF取得失敗：人間認証が必要 (2026-05-31)
🚫 PDF取得不可：機関アクセス権なし (2026-05-31)
```

メモ欄への反映には、ArticleFinder でプロジェクトを選び直す（リロードする）必要がある。

## 出版社別メモ

### Wiley

多くの場合、本文ページに `PDF` または `Download PDF` がある。`/doi/pdfdirect/{doi}` がPDF本体になることが多い。

例:

```text
https://onlinelibrary-wiley-com.<proxy>/doi/pdfdirect/10.1002/pbc.29104
```

### Springer / Nature

`Download PDF` リンクまたは `citation_pdf_url` がそのまま使えることが多い。

例:

```text
https://link.springer.com/content/pdf/{doi}.pdf
https://www.nature.com/articles/{article_id}.pdf
```

### Taylor & Francis

`/doi/epdf/...` はHTMLビューアになることがある。PDF本体は次の形で取得できる場合がある。

```text
https://www-tandfonline-com.<proxy>/doi/pdf/{doi}?download=true
```

### ScienceDirect

一番失敗しやすい。本文ページには入れても、`View PDF` クリック時に `?ref=cra_js_challenge&fr=RR-16` に戻される場合がある。

対策:

1. MCP専用Chromeを remote debugging 付きで起動する。
2. Codex MCPを `--browser-url=http://127.0.0.1:9222` で接続する。
3. ユーザー本人がMCP専用Chrome上でScienceDirectの人間確認を通す。
4. Agentは本文ページ上の `View PDF` を通常クリックする。
5. `pdf.sciencedirectassets.com/.../main.pdf?...` のPDF実体URLまで遷移したら保存する。

ScienceDirectでは、`fetch()` で `pdfft` URLを直接取得するとHTMLが返ることがある。通常クリックでPDF実体URLまで進んでから保存する方が安定する。

## トラブルシュート

### MCPから `about:blank` しか見えない

`~/.codex/config.toml` が `--browser-url=http://127.0.0.1:9222` 付きになっているか確認し、Codexを再起動する。

### `curl http://127.0.0.1:9222/json/version` が失敗する

MCP専用Chromeが remote debugging 付きで起動していない。起動コマンドを再実行する。

### ScienceDirectで `cra_js_challenge` に戻る

MCP専用Chrome上でユーザー本人が人間確認を通す。通過後も失敗する場合は、Chromeを終了して同じ `~/chrome-mcp-profile` で再起動する。

### PDF名なのにHTMLだった

保存後に `file` で確認する。HTMLなら削除し、PDF実体URLまたは出版社の別PDFリンクで再試行する。

### 通常Chromeが開けない

MCP専用Chromeが先に起動していると `open -a "Google Chrome"` がそちらに吸われる。Chromeをすべて終了し、通常Chromeを先に起動してからMCP専用Chromeを起動する。

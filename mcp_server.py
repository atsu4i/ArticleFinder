"""
ArticleFinder MCP Server
Claude Code から直接論文検索を実行するための MCP サーバー
"""

import sys
import os
import uuid
import threading
import json
from collections import deque
from datetime import datetime
from typing import Optional, Dict, Any

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

from article_finder import ArticleFinder
from project_manager import ProjectManager
from gemini_evaluator import GeminiEvaluator
from pubmed_api import PubMedAPI

# ジョブ管理（プロセス内インメモリ）
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()

PROJECTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects")
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

mcp = FastMCP(name="ArticleFinder")

SEARCH_MODE_PRESETS = {
    "fast": {
        "max_depth": 3,
        "max_articles": 200,
        "relevance_threshold": 80,
        "include_similar": True,
        "max_similar": 20,
        "include_cited_by": True,
        "max_cited_by": 20,
        "include_references": True,
        "pubmed_only": False
    },
    "standard": {
        "max_depth": 3,
        "max_articles": 500,
        "relevance_threshold": 80,
        "include_similar": True,
        "max_similar": 50,
        "include_cited_by": True,
        "max_cited_by": 50,
        "include_references": True,
        "pubmed_only": False
    },
    "deep": {
        "max_depth": 5,
        "max_articles": 1000,
        "relevance_threshold": 80,
        "include_similar": True,
        "max_similar": 100,
        "include_cited_by": True,
        "max_cited_by": 100,
        "include_references": True,
        "pubmed_only": False
    }
}


def normalize_search_mode(mode: Optional[str]) -> Optional[str]:
    if not mode:
        return None
    mode = str(mode).strip().lower()
    if mode in ("高速", "fast"):
        return "fast"
    if mode in ("標準", "standard", "std", "default"):
        return "standard"
    if mode in ("深掘り", "deep", "intensive"):
        return "deep"
    if mode in ("カスタム", "custom"):
        return None
    return None


def _run_search(job_id: str, params: dict):
    """バックグラウンドスレッドで find_articles() を実行"""
    progress_log = _jobs[job_id]["progress"]
    log_path = os.path.join(LOGS_DIR, f"{job_id}.log")

    def on_progress(msg: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        progress_log.append(line)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line + "\n")

    def should_stop() -> bool:
        return _jobs[job_id].get("stop_requested", False)

    # ログファイルのヘッダーを書き込む
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"# ArticleFinder Search Log\n")
        f.write(f"# job_id: {job_id}\n")
        f.write(f"# project: {params['project_name']}\n")
        f.write(f"# started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# tail -f {log_path}\n")
        f.write("#" * 60 + "\n")

    try:
        pm = ProjectManager(PROJECTS_DIR)
        project_name = params["project_name"]

        try:
            project = pm.load_project(project_name)
            on_progress(f"既存プロジェクト '{project_name}' を読み込みました")
        except ValueError:
            project = pm.create_project(
                name=project_name,
                research_theme=params["research_theme"]
            )
            on_progress(f"新規プロジェクト '{project_name}' を作成しました")

        finder = ArticleFinder(gemini_model=params.get("gemini_model"))

        mode_key = normalize_search_mode(params.get("mode"))
        mode_preset = SEARCH_MODE_PRESETS.get(mode_key, {}) if mode_key else {}

        result = finder.find_articles(
            start_pmid_or_url=params["start_pmid_or_url"],
            research_theme=params["research_theme"],
            max_depth=params.get("max_depth", mode_preset.get("max_depth", 2)),
            max_articles=params.get("max_articles", mode_preset.get("max_articles", 100)),
            relevance_threshold=params.get("relevance_threshold", mode_preset.get("relevance_threshold", 80)),
            year_from=params.get("year_from"),
            include_similar=params.get("include_similar", mode_preset.get("include_similar", True)),
            max_similar=params.get("max_similar", mode_preset.get("max_similar", 20)),
            include_cited_by=params.get("include_cited_by", mode_preset.get("include_cited_by", True)),
            max_cited_by=params.get("max_cited_by", mode_preset.get("max_cited_by", 20)),
            include_references=params.get("include_references", mode_preset.get("include_references", False)),
            pubmed_only=params.get("pubmed_only", mode_preset.get("pubmed_only", False)),
            progress_callback=on_progress,
            project=project,
            should_stop_callback=should_stop
        )

        final_status = "completed" if not result.get("interrupted") else "interrupted"
        with _jobs_lock:
            _jobs[job_id]["status"] = final_status
            _jobs[job_id]["result"] = {
                "stats": result["stats"],
                "total_articles": len(result.get("articles", [])),
                "project_name": project_name,
                "interrupted": result.get("interrupted", False)
            }
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write("#" * 60 + "\n")
            f.write(f"# 検索{('完了' if final_status == 'completed' else '中断')}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            stats = result["stats"]
            f.write(f"# 評価: {stats.get('total_evaluated', 0)}件 / 関連あり: {stats.get('total_relevant', 0)}件 / キャッシュ: {stats.get('total_skipped', 0)}件\n")

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(e)
        on_progress(f"エラー: {str(e)}")
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write("#" * 60 + "\n")
            f.write(f"# 検索失敗: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    finally:
        with _jobs_lock:
            # 完了フラグを立てて、同一プロジェクトのロックを解除
            _jobs[job_id]["running"] = False


@mcp.tool
def list_projects() -> dict:
    """
    保存されているプロジェクトの一覧を取得する。
    各プロジェクトの名前、研究テーマ、論文数、最終更新日時を返す。
    """
    pm = ProjectManager(PROJECTS_DIR)
    projects = pm.list_projects()

    result = []
    for p in projects:
        result.append({
            "name": p.get("name", ""),
            "research_theme": p.get("research_theme", ""),
            "total_articles": p.get("stats", {}).get("total_articles", 0),
            "total_relevant": p.get("stats", {}).get("total_relevant", 0),
            "created_at": p.get("created_at", ""),
            "updated_at": p.get("updated_at", "")
        })

    return {"projects": result, "total": len(result)}


@mcp.tool
def get_project_articles(
    project_name: str,
    relevant_only: bool = True,
    min_score: int = 0,
    max_results: int = 100,
    sort_by: str = "relevance_score"
) -> dict:
    """
    プロジェクト内の論文一覧を取得する。

    Args:
        project_name: プロジェクト名
        relevant_only: Trueの場合、関連ありと判定された論文のみ返す
        min_score: この値以上のスコアの論文のみ返す（0-100）
        max_results: 返す論文の最大数
        sort_by: ソートキー（"relevance_score" または "pub_year"）
    """
    pm = ProjectManager(PROJECTS_DIR)

    try:
        project = pm.load_project(project_name)
    except ValueError as e:
        return {"error": str(e), "articles": []}

    all_articles = project.get_all_articles()

    # フィルタリング
    filtered = []
    for article in all_articles:
        score = article.get("relevance_score", 0)
        is_relevant = article.get("is_relevant", False)

        if relevant_only and not is_relevant:
            continue
        if score < min_score:
            continue

        # 重いフィールドを省いて返す（トークン数削減）
        filtered.append({
            "pmid": article.get("pmid", ""),
            "article_id": article.get("article_id", ""),
            "title": article.get("title", ""),
            "authors": article.get("authors", ""),
            "journal": article.get("journal", ""),
            "pub_year": article.get("pub_year"),
            "doi": article.get("doi", ""),
            "url": article.get("url", ""),
            "relevance_score": score,
            "is_relevant": is_relevant,
            "relevance_reasoning": article.get("relevance_reasoning", ""),
            "abstract_summary_ja": article.get("abstract_summary_ja", ""),
            "depth": article.get("depth", 0),
            "source_type": article.get("source_type", ""),
            "citation_count": article.get("citation_count"),
            "altmetric_score": article.get("altmetric_score"),
            "evaluated_at": article.get("evaluated_at", "")
        })

    # ソート
    reverse = True
    if sort_by == "pub_year":
        filtered.sort(key=lambda x: x.get("pub_year") or 0, reverse=reverse)
    else:
        filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=reverse)

    # 最大件数で切り詰め
    filtered = filtered[:max_results]

    stats = project.get_stats()
    return {
        "project_name": project_name,
        "research_theme": project.metadata.get("research_theme", ""),
        "stats": stats,
        "articles": filtered,
        "returned_count": len(filtered)
    }


@mcp.tool
def start_search(
    start_pmid_or_url: str,
    research_theme: str,
    project_name: str,
    mode: Optional[str] = None,
    max_depth: int = 2,
    max_articles: int = 100,
    relevance_threshold: int = 80,
    year_from: Optional[int] = None,
    include_similar: bool = True,
    max_similar: int = 20,
    include_cited_by: bool = True,
    max_cited_by: int = 20,
    include_references: bool = False,
    pubmed_only: bool = False,
    gemini_model: Optional[str] = None
) -> dict:
    """
    論文検索を開始する。処理はバックグラウンドで実行され、job_id を即座に返す。
    検索の進捗確認には get_search_status(job_id) を使用すること。
    完了後は get_project_articles(project_name) で結果を取得できる。

    Args:
        start_pmid_or_url: 起点論文のPMID、PubMed URL、またはDOI
        research_theme: 研究テーマの詳細説明（例: "2型糖尿病患者におけるSGLT2阻害薬の心血管アウトカムに関する論文"）
        project_name: 保存先プロジェクト名（存在しない場合は自動作成）
        mode: 探索モード（高速/標準/深掘り もしくは fast/standard/deep）
        max_depth: 探索深さ（1〜3、デフォルト2）
        max_articles: 最大評価論文数（デフォルト100）
        relevance_threshold: 関連性スコアの閾値（0-100、デフォルト80）
        year_from: この年以降の論文のみ（Noneで制限なし）
        include_similar: Similar articlesを探索するか
        max_similar: Similar articlesの1論文あたりの最大取得数（デフォルト20）
        include_cited_by: Cited byを探索するか
        max_cited_by: Cited byの1論文あたりの最大取得数（デフォルト20）
        include_references: Referencesを探索するか
        pubmed_only: TrueにするとPubMed収録論文（PMIDあり）のみを対象にし、DOIのみの論文を除外する
        gemini_model: 使用するGeminiモデル名（Noneでデフォルトモデル）
    """
    # 同一プロジェクトへの並行検索をブロック
    with _jobs_lock:
        for job_id_existing, job in _jobs.items():
            if (job.get("project_name") == project_name
                    and job.get("running", False)):
                return {
                    "error": f"プロジェクト '{project_name}' で既に検索が実行中です。"
                             f"get_search_status('{job_id_existing}') で状態を確認してください。",
                    "existing_job_id": job_id_existing
                }

        job_id = str(uuid.uuid4())
        _jobs[job_id] = {
            "status": "running",
            "running": True,
            "project_name": project_name,
            "progress": deque(maxlen=200),
            "stop_requested": False,
            "started_at": datetime.now().isoformat()
        }

    params = {
        "start_pmid_or_url": start_pmid_or_url,
        "research_theme": research_theme,
        "project_name": project_name,
        "mode": mode,
        "max_depth": max_depth,
        "max_articles": max_articles,
        "relevance_threshold": relevance_threshold,
        "year_from": year_from,
        "include_similar": include_similar,
        "max_similar": max_similar,
        "include_cited_by": include_cited_by,
        "max_cited_by": max_cited_by,
        "include_references": include_references,
        "pubmed_only": pubmed_only,
        "gemini_model": gemini_model
    }

    thread = threading.Thread(target=_run_search, args=(job_id, params), daemon=True)
    thread.start()

    log_path = os.path.join(LOGS_DIR, f"{job_id}.log")
    return {
        "job_id": job_id,
        "project_name": project_name,
        "status": "running",
        "log_path": log_path,
        "tail_command": f"tail -f {log_path}",
        "message": (
            f"検索を開始しました。"
            f"別ターミナルで `tail -f {log_path}` を実行するとリアルタイムで進捗を確認できます。"
        )
    }


@mcp.tool
def get_search_status(job_id: str) -> dict:
    """
    実行中または完了した検索ジョブの状態と進捗ログを取得する。
    30〜60秒おきにポーリングして検索完了を確認することを推奨。

    Args:
        job_id: start_search で返された job_id
    """
    with _jobs_lock:
        job = _jobs.get(job_id)

    if not job:
        return {
            "error": f"ジョブ '{job_id}' が見つかりません。MCPサーバーが再起動した可能性があります。"
        }

    # 最新の進捗ログ（最大20件）
    progress_list = list(job["progress"])[-20:]

    response = {
        "job_id": job_id,
        "status": job["status"],
        "project_name": job.get("project_name", ""),
        "started_at": job.get("started_at", ""),
        "recent_progress": progress_list
    }

    if job["status"] == "completed":
        response["result"] = job.get("result", {})
        response["message"] = "検索が完了しました。get_project_articles() で結果を取得してください。"
    elif job["status"] == "interrupted":
        response["result"] = job.get("result", {})
        response["message"] = "検索が中断されました。途中までの結果は保存されています。"
    elif job["status"] == "failed":
        response["error"] = job.get("error", "不明なエラー")
        response["message"] = "検索が失敗しました。"
    else:
        response["message"] = "検索実行中です。しばらくしてから再度確認してください。"

    return response


@mcp.tool
def stop_search(job_id: str) -> dict:
    """
    実行中の検索を安全に停止する。
    停止リクエストを送信し、現在処理中の論文が完了した後に停止する。
    途中までの結果はプロジェクトに保存される。

    Args:
        job_id: start_search で返された job_id
    """
    with _jobs_lock:
        job = _jobs.get(job_id)

    if not job:
        return {"error": f"ジョブ '{job_id}' が見つかりません。"}

    if job["status"] != "running":
        return {
            "message": f"ジョブはすでに '{job['status']}' 状態です。停止不要です。",
            "status": job["status"]
        }

    with _jobs_lock:
        _jobs[job_id]["stop_requested"] = True

    return {
        "job_id": job_id,
        "message": "停止リクエストを送信しました。現在処理中の論文完了後に停止します。",
        "status": "stop_requested"
    }


@mcp.tool
def evaluate_article(
    pmid: str,
    research_theme: str,
    relevance_threshold: int = 60,
    gemini_model: Optional[str] = None
) -> dict:
    """
    1件の論文を指定した研究テーマに対して評価する。
    プロジェクトへの保存は行わない。評価のみを返す。

    Args:
        pmid: PubMed ID（数字のみ、またはPubMed URL）
        research_theme: 研究テーマの詳細説明
        relevance_threshold: 関連性スコアの閾値（0-100）
        gemini_model: 使用するGeminiモデル名（Noneでデフォルトモデル）
    """
    pubmed = PubMedAPI()
    actual_pmid = pubmed.extract_pmid_from_url(pmid)

    if not actual_pmid:
        return {"error": f"無効なPMIDまたはURL: {pmid}"}

    article = pubmed.get_article_info(actual_pmid)
    if not article:
        return {"error": f"論文情報を取得できませんでした: PMID {actual_pmid}"}

    evaluator = GeminiEvaluator(model_name=gemini_model)
    evaluation = evaluator.evaluate_relevance(research_theme, article, relevance_threshold)

    return {
        "pmid": actual_pmid,
        "title": article.get("title", ""),
        "authors": article.get("authors", ""),
        "journal": article.get("journal", ""),
        "pub_year": article.get("pub_year"),
        "doi": article.get("doi", ""),
        "url": article.get("url", ""),
        "abstract": article.get("abstract", "")[:500] + "..." if len(article.get("abstract", "")) > 500 else article.get("abstract", ""),
        "relevance_score": evaluation["score"],
        "is_relevant": evaluation["is_relevant"],
        "relevance_reasoning": evaluation["reasoning"]
    }


@mcp.tool
def export_project(
    project_name: str,
    output_path: Optional[str] = None
) -> dict:
    """
    プロジェクトの全データをJSONファイルにエクスポートする。

    Args:
        project_name: エクスポートするプロジェクト名
        output_path: 出力先ファイルパス（省略時はプロジェクトディレクトリに保存）
    """
    pm = ProjectManager(PROJECTS_DIR)

    try:
        project = pm.load_project(project_name)
    except ValueError as e:
        return {"error": str(e)}

    json_data = project.export_to_json()

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = project.metadata.get("safe_name", project_name)
        output_path = os.path.join(
            PROJECTS_DIR,
            safe_name,
            f"export_{timestamp}.json"
        )

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_data)

        stats = project.get_stats()
        return {
            "success": True,
            "output_path": output_path,
            "project_name": project_name,
            "total_articles": stats.get("total_articles", 0),
            "total_relevant": stats.get("total_relevant", 0)
        }
    except Exception as e:
        return {"error": f"エクスポート失敗: {str(e)}"}


if __name__ == "__main__":
    mcp.run()

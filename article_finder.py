"""
論文探索のメインロジック
PubMed APIとGemini評価を組み合わせて関連論文を探索
"""

from typing import Dict, List, Callable, Optional, Set
from pubmed_api import PubMedAPI
from gemini_evaluator import GeminiEvaluator
from project_manager import Project


class ArticleFinder:
    """論文探索を行うクラス"""

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        notion_api_key: Optional[str] = None,
        notion_database_id: Optional[str] = None
    ):
        """
        Args:
            gemini_api_key: Gemini API Key（省略時は環境変数から取得）
            gemini_model: 使用するGeminiモデル名（省略時はデフォルトモデル）
            notion_api_key: Notion API Key（省略時は環境変数から取得、未設定の場合Notion連携は無効）
            notion_database_id: Notion Database ID（省略時は環境変数から取得）
        """
        self.pubmed = PubMedAPI()
        self.evaluator = GeminiEvaluator(gemini_api_key, gemini_model)

        # Notion APIを初期化（オプション）
        self.notion = None
        if notion_api_key and notion_database_id:
            try:
                # 遅延import: Notion連携を使う場合のみimport
                from notion_api import NotionAPI
                self.notion = NotionAPI(notion_api_key, notion_database_id)
            except ImportError:
                print("Notion API is not available. Install notion-client: pip install notion-client")
                self.notion = None
            except Exception as e:
                print(f"Notion API initialization failed: {e}")
                self.notion = None

    def find_articles(
        self,
        start_pmid_or_url: str,
        research_theme: str,
        max_depth: int = 2,
        max_articles: int = 500,
        relevance_threshold: int = 60,
        year_from: Optional[int] = None,
        include_similar: bool = True,
        include_cited_by: bool = True,
        progress_callback: Optional[Callable] = None,
        project: Optional[Project] = None,
        should_stop_callback: Optional[Callable] = None,
        max_related_per_article: int = 20
    ) -> Dict:
        """
        論文を探索して関連論文を収集

        Args:
            start_pmid_or_url: 起点となる論文のPMIDまたはURL
            research_theme: 研究テーマ（詳細な説明）
            max_depth: 探索の深さ（1以上）
            max_articles: 収集する最大論文数
            relevance_threshold: 関連性スコアの閾値（0-100）
            year_from: この年以降の論文のみ（Noneの場合は制限なし）
            include_similar: Similar articlesを探索するか
            include_cited_by: Cited byを探索するか
            progress_callback: 進捗通知用コールバック関数
            project: プロジェクト（指定時は重複チェックとキャッシュを使用）
            should_stop_callback: 停止チェック用コールバック関数（Trueを返すと探索を停止）
            max_related_per_article: 1論文あたりの最大関連論文数（Similar/Cited byそれぞれに適用）

        Returns:
            {
                "articles": [論文情報のリスト],
                "stats": {
                    "total_found": int,
                    "total_evaluated": int,
                    "total_relevant": int,
                    "total_skipped": int,  # キャッシュからの取得数
                    "depth_reached": int
                }
            }
        """
        # 起点PMIDを抽出
        start_pmid = self.pubmed.extract_pmid_from_url(start_pmid_or_url)
        if not start_pmid:
            raise ValueError(f"Invalid PMID or URL: {start_pmid_or_url}")

        # プロジェクトが指定されている場合、既存データを読み込み
        if project:
            # 既存の論文データを取得
            existing_articles = project.get_all_articles()
            self._notify_progress(
                progress_callback,
                f"プロジェクトから既存データを読み込み（{len(existing_articles)}件）"
            )

        # 収集済み論文を管理
        collected_articles: Dict[str, Dict] = {}
        visited_pmids: Set[str] = set()

        # 統計情報
        stats = {
            "total_found": 0,
            "total_evaluated": 0,
            "total_relevant": 0,
            "total_skipped": 0,
            "depth_reached": 0
        }

        # 起点論文を処理
        self._notify_progress(progress_callback, f"起点論文を処理中 (PMID: {start_pmid})")

        # プロジェクトにキャッシュがあるかチェック
        if project and project.has_article(start_pmid):
            self._notify_progress(progress_callback, f"起点論文はキャッシュから取得")
            start_article = project.get_article(start_pmid)

            # スコアはキャッシュから使用するが、is_relevantは現在の閾値で再計算
            score = start_article.get("relevance_score", 0)
            start_article["is_relevant"] = score >= relevance_threshold

            # ソース情報を追加（キャッシュにない場合のみ）
            if "source_pmid" not in start_article:
                start_article["source_pmid"] = None
                start_article["source_type"] = "起点論文"

            stats["total_skipped"] = 1
        else:
            # キャッシュにない場合は取得・評価
            start_article = self.pubmed.get_article_info(start_pmid)
            if not start_article:
                raise ValueError(f"Failed to fetch article: PMID {start_pmid}")

            # 起点論文を評価
            self._notify_progress(progress_callback, f"起点論文を評価中")
            evaluation = self.evaluator.evaluate_relevance(
                research_theme,
                start_article,
                relevance_threshold
            )

            start_article.update({
                "relevance_score": evaluation["score"],
                "is_relevant": evaluation["is_relevant"],
                "relevance_reasoning": evaluation["reasoning"],
                "depth": 0,
                "source_pmid": None,
                "source_type": "起点論文"
            })

            stats["total_evaluated"] = 1

            # プロジェクトに保存
            if project:
                project.add_article(start_article)

        collected_articles[start_pmid] = start_article
        visited_pmids.add(start_pmid)
        stats["total_found"] = 1
        if start_article.get("is_relevant"):
            stats["total_relevant"] = 1

        # 深さ優先で探索
        # 起点論文は評価スコアに関わらず、必ず次の階層へ進む
        current_layer = [start_pmid]

        for depth in range(1, max_depth + 1):
            # 停止チェック
            if should_stop_callback and should_stop_callback():
                self._notify_progress(progress_callback, "停止リクエストを受け付けました")
                break

            if not current_layer or len(collected_articles) >= max_articles:
                break

            stats["depth_reached"] = depth

            self._notify_progress(
                progress_callback,
                f"探索階層 {depth}/{max_depth} を開始 (対象論文数: {len(current_layer)})"
            )

            # 次の階層の候補を取得
            next_layer = self._explore_layer(
                pmids=current_layer,
                research_theme=research_theme,
                depth=depth,
                visited_pmids=visited_pmids,
                collected_articles=collected_articles,
                max_articles=max_articles,
                relevance_threshold=relevance_threshold,
                year_from=year_from,
                include_similar=include_similar,
                include_cited_by=include_cited_by,
                progress_callback=progress_callback,
                stats=stats,
                project=project,
                should_stop_callback=should_stop_callback,
                max_related_per_article=max_related_per_article
            )

            current_layer = next_layer

        # 結果を整形
        articles_list = list(collected_articles.values())

        # 関連性スコアでソート
        articles_list.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

        # Notion連携（オプション）
        if self.notion:
            self._notify_progress(progress_callback, "Notionデータベースをチェック中...")
            try:
                articles_list = self.notion.batch_check_articles(
                    articles_list,
                    update_score=True,
                    callback=lambda current, total, pmid: self._notify_progress(
                        progress_callback,
                        f"Notionチェック中 {current}/{total} (PMID: {pmid})"
                    )
                )
                self._notify_progress(progress_callback, "Notionチェック完了")
            except Exception as e:
                self._notify_progress(progress_callback, f"Notionチェックエラー: {e}")

        # プロジェクトを保存
        if project:
            project.save()
            self._notify_progress(progress_callback, "プロジェクトを保存しました")

        return {
            "articles": articles_list,
            "stats": stats
        }

    def _explore_layer(
        self,
        pmids: List[str],
        research_theme: str,
        depth: int,
        visited_pmids: Set[str],
        collected_articles: Dict[str, Dict],
        max_articles: int,
        relevance_threshold: int,
        year_from: Optional[int],
        include_similar: bool,
        include_cited_by: bool,
        progress_callback: Optional[Callable],
        stats: Dict,
        project: Optional[Project],
        should_stop_callback: Optional[Callable] = None,
        max_related_per_article: int = 20
    ) -> List[str]:
        """
        1階層分の探索を実行

        Returns:
            次の階層で探索すべきPMIDのリスト
        """
        next_layer_pmids = []

        for pmid in pmids:
            # 停止チェック
            if should_stop_callback and should_stop_callback():
                self._notify_progress(progress_callback, "停止リクエストを受け付けました")
                break

            # 最大件数チェック
            if len(collected_articles) >= max_articles:
                self._notify_progress(
                    progress_callback,
                    f"最大論文数 {max_articles} に到達しました"
                )
                break

            self._notify_progress(
                progress_callback,
                f"PMID {pmid} の関連論文を取得中"
            )

            # 関連論文を取得（ソース情報も含む）
            related_pmids_with_source = []

            if include_similar:
                similar = self.pubmed.get_related_articles(pmid, "similar")
                # 制限数まで切り詰め
                related_pmids_with_source.extend([(p, "similar") for p in similar[:max_related_per_article]])

            if include_cited_by:
                cited_by = self.pubmed.get_related_articles(pmid, "cited_by")
                # 制限数まで切り詰め
                related_pmids_with_source.extend([(p, "cited_by") for p in cited_by[:max_related_per_article]])

            # 重複削除（同じPMIDでもソースが異なる場合、最初のもののみ保持）
            seen_pmids = set()
            unique_related = []
            for p, source_type in related_pmids_with_source:
                if p not in seen_pmids:
                    seen_pmids.add(p)
                    unique_related.append((p, source_type))

            related_pmids_with_source = unique_related

            # 未訪問の論文のみ処理
            new_pmids_with_source = [(p, source_type) for p, source_type in related_pmids_with_source if p not in visited_pmids]

            self._notify_progress(
                progress_callback,
                f"新規論文 {len(new_pmids_with_source)} 件を発見"
            )

            stats["total_found"] += len(new_pmids_with_source)

            # 各論文を取得・評価
            for new_pmid, source_type in new_pmids_with_source:
                # 停止チェック
                if should_stop_callback and should_stop_callback():
                    self._notify_progress(progress_callback, "停止リクエストを受け付けました")
                    break

                if len(collected_articles) >= max_articles:
                    break

                visited_pmids.add(new_pmid)

                # プロジェクトにキャッシュがあるかチェック
                if project and project.has_article(new_pmid):
                    self._notify_progress(
                        progress_callback,
                        f"PMID {new_pmid} はキャッシュから取得 ({len(collected_articles)}/{max_articles})"
                    )
                    article = project.get_article(new_pmid)

                    # スコアはキャッシュから使用するが、is_relevantは現在の閾値で再計算
                    score = article.get("relevance_score", 0)
                    article["is_relevant"] = score >= relevance_threshold

                    # ソース情報を追加（キャッシュにない場合のみ）
                    if "source_pmid" not in article:
                        article["source_pmid"] = pmid
                        article["source_type"] = source_type

                    stats["total_skipped"] += 1
                else:
                    # キャッシュにない場合は取得・評価
                    # 論文情報を取得
                    article = self.pubmed.get_article_info(new_pmid)
                    if not article:
                        continue

                    # 年フィルタ
                    if year_from and article.get("pub_year"):
                        if article["pub_year"] < year_from:
                            continue

                    # 関連性を評価
                    self._notify_progress(
                        progress_callback,
                        f"PMID {new_pmid} を評価中 ({len(collected_articles)}/{max_articles})"
                    )

                    evaluation = self.evaluator.evaluate_relevance(
                        research_theme,
                        article,
                        relevance_threshold
                    )

                    stats["total_evaluated"] += 1

                    # 論文情報を更新
                    article.update({
                        "relevance_score": evaluation["score"],
                        "is_relevant": evaluation["is_relevant"],
                        "relevance_reasoning": evaluation["reasoning"],
                        "depth": depth,
                        "source_pmid": pmid,
                        "source_type": source_type
                    })

                    # プロジェクトに保存
                    if project:
                        project.add_article(article)

                collected_articles[new_pmid] = article

                # 関連性が高い論文は次の階層で探索
                if article.get("is_relevant"):
                    stats["total_relevant"] += 1
                    next_layer_pmids.append(new_pmid)

        return next_layer_pmids

    def _notify_progress(
        self,
        callback: Optional[Callable],
        message: str
    ):
        """進捗を通知"""
        if callback:
            callback(message)
        else:
            print(message)

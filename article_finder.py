"""
論文探索のメインロジック
PubMed APIとGemini評価を組み合わせて関連論文を探索
"""

from datetime import datetime
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
        max_similar: int = 20,
        include_cited_by: bool = True,
        max_cited_by: int = 20,
        include_references: bool = False,
        max_references: int = 20,
        progress_callback: Optional[Callable] = None,
        project: Optional[Project] = None,
        should_stop_callback: Optional[Callable] = None
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
            max_similar: Similar articlesの最大取得数（1論文あたり）
            include_cited_by: Cited byを探索するか
            max_cited_by: Cited byの最大取得数（1論文あたり）
            include_references: Referencesを探索するか
            max_references: Referencesの最大取得数（1論文あたり）
            progress_callback: 進捗通知用コールバック関数
            project: プロジェクト（指定時は重複チェックとキャッシュを使用）
            should_stop_callback: 停止チェック用コールバック関数（Trueを返すと探索を停止）

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
            "depth_reached": 0,
            "session_article_count": 0  # このセッションで追加された論文数
        }

        # 検索セッションIDを生成（このセッションで追加される論文を識別）
        session_id = datetime.now().isoformat()

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

            # キャッシュから取得したことを示すフラグ
            start_article["is_newly_evaluated"] = False

            stats["total_skipped"] = 1
        else:
            # キャッシュにない場合は取得・評価
            start_article = self.pubmed.get_article_info(start_pmid)
            if not start_article:
                raise ValueError(f"Failed to fetch article: PMID {start_pmid}")

            # 起点論文を評価
            self._notify_progress(progress_callback, f"起点論文を評価中")

            try:
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
                    "source_type": "起点論文",
                    "search_session_id": session_id,  # セッションIDを記録
                    "is_newly_evaluated": True  # 新規評価されたことを示すフラグ
                })

                stats["total_evaluated"] = 1
                stats["session_article_count"] += 1  # セッションカウントを増やす

                # プロジェクトに保存（リアルタイム保存）
                if project:
                    project.add_article(start_article)
                    project.save()
                    self._notify_progress(
                        progress_callback,
                        f"✅ 起点論文評価完了・保存済み (スコア: {evaluation['score']})"
                    )

            except Exception as e:
                # 起点論文の評価エラーは致命的なのでエラーを投げる
                if project:
                    # エラーが発生しても、ここまでの進捗を保存
                    project.save()
                    self._notify_progress(
                        progress_callback,
                        f"💾 エラーが発生しましたが、進捗を保存しました"
                    )
                raise ValueError(f"起点論文の評価中にエラーが発生しました: {str(e)}")

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
                max_similar=max_similar,
                include_cited_by=include_cited_by,
                max_cited_by=max_cited_by,
                include_references=include_references,
                max_references=max_references,
                progress_callback=progress_callback,
                stats=stats,
                project=project,
                should_stop_callback=should_stop_callback,
                session_id=session_id  # セッションIDを渡す
            )

            current_layer = next_layer

        # 結果を整形
        articles_list = list(collected_articles.values())

        # 関連性スコアでソート
        articles_list.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

        # Notion連携（オプション）- 新規評価された論文のみ
        if self.notion:
            # 新規評価された論文のみを抽出
            newly_evaluated_articles = [
                a for a in articles_list
                if a.get("is_newly_evaluated", False)
            ]

            if newly_evaluated_articles:
                self._notify_progress(
                    progress_callback,
                    f"新規評価された {len(newly_evaluated_articles)} 件の論文をNotionデータベースでチェック中..."
                )
                try:
                    # プロジェクト名を取得
                    project_name = project.metadata.get('name') if project else None

                    updated_articles = self.notion.batch_check_articles(
                        newly_evaluated_articles,
                        update_score=True,
                        callback=lambda current, total, pmid: self._notify_progress(
                            progress_callback,
                            f"Notionチェック中 {current}/{total} (PMID: {pmid})"
                        ),
                        project_name=project_name,
                        research_theme=research_theme
                    )
                    self._notify_progress(progress_callback, "Notionチェック完了")

                    # 更新された論文情報をarticles_listに反映
                    pmid_to_updated = {a.get("pmid"): a for a in updated_articles}
                    for i, article in enumerate(articles_list):
                        pmid = article.get("pmid")
                        if pmid in pmid_to_updated:
                            articles_list[i] = pmid_to_updated[pmid]

                    # Notion情報をプロジェクトに反映
                    if project:
                        for article in updated_articles:
                            project.add_article(article)
                        self._notify_progress(progress_callback, "Notion情報をプロジェクトに保存しました")
                except Exception as e:
                    self._notify_progress(progress_callback, f"Notionチェックエラー: {e}")
            else:
                self._notify_progress(progress_callback, "新規評価された論文がないため、Notionチェックをスキップしました")

        # プロジェクトを保存
        if project:
            # 検索セッション情報を追加
            if stats["session_article_count"] > 0:
                project.add_search_session(session_id, stats["session_article_count"])

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
        max_similar: int,
        include_cited_by: bool,
        max_cited_by: int,
        include_references: bool,
        max_references: int,
        progress_callback: Optional[Callable],
        stats: Dict,
        project: Optional[Project],
        should_stop_callback: Optional[Callable] = None,
        session_id: str = None
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
                related_pmids_with_source.extend([(p, "similar") for p in similar[:max_similar]])
                self._notify_progress(progress_callback, f"  Similar articles: {len(similar[:max_similar])} 件取得")

            if include_cited_by:
                cited_by = self.pubmed.get_related_articles(pmid, "cited_by")
                # 制限数まで切り詰め
                related_pmids_with_source.extend([(p, "cited_by") for p in cited_by[:max_cited_by]])
                self._notify_progress(progress_callback, f"  Cited by: {len(cited_by[:max_cited_by])} 件取得")

            if include_references:
                references = self.pubmed.get_related_articles(pmid, "references")
                # 制限数まで切り詰め
                related_pmids_with_source.extend([(p, "references") for p in references[:max_references]])
                self._notify_progress(progress_callback, f"  References: {len(references[:max_references])} 件取得")

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

                    # キャッシュから取得したことを示すフラグ
                    article["is_newly_evaluated"] = False

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

                    try:
                        evaluation = self.evaluator.evaluate_relevance(
                            research_theme,
                            article,
                            relevance_threshold
                        )

                        stats["total_evaluated"] += 1
                        stats["session_article_count"] += 1  # セッションカウントを増やす

                        # 論文情報を更新
                        article.update({
                            "relevance_score": evaluation["score"],
                            "is_relevant": evaluation["is_relevant"],
                            "relevance_reasoning": evaluation["reasoning"],
                            "depth": depth,
                            "source_pmid": pmid,
                            "source_type": source_type,
                            "search_session_id": session_id,  # セッションIDを記録
                            "is_newly_evaluated": True  # 新規評価されたことを示すフラグ
                        })

                        # プロジェクトに保存（リアルタイム保存）
                        if project:
                            project.add_article(article)
                            project.save()  # 各論文評価後に即座に保存
                            self._notify_progress(
                                progress_callback,
                                f"✅ PMID {new_pmid} 評価完了・保存済み (スコア: {evaluation['score']}, 保存済み: {len(collected_articles) + 1}件)"
                            )

                    except Exception as e:
                        # 評価エラー時も論文情報は保存（スコア0として）
                        self._notify_progress(
                            progress_callback,
                            f"⚠️ PMID {new_pmid} の評価中にエラー: {str(e)}"
                        )
                        article.update({
                            "relevance_score": 0,
                            "is_relevant": False,
                            "relevance_reasoning": f"評価エラー: {str(e)}",
                            "depth": depth,
                            "source_pmid": pmid,
                            "source_type": source_type,
                            "search_session_id": session_id,  # セッションIDを記録
                            "is_newly_evaluated": True  # エラーでも評価は試みたのでTrue
                        })

                        stats["session_article_count"] += 1  # エラー時もセッションカウントを増やす

                        # エラー時も緊急保存
                        if project:
                            project.add_article(article)
                            project.save()
                            self._notify_progress(
                                progress_callback,
                                f"💾 エラーが発生しましたが、ここまでの進捗を保存しました (保存済み: {len(collected_articles) + 1}件)"
                            )

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

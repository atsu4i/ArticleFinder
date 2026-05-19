"""
論文探索のメインロジック
PubMed APIとGemini評価を組み合わせて関連論文を探索
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Callable, Optional, Set, Any
from pubmed_api import PubMedAPI
from gemini_evaluator import GeminiEvaluator
from project_manager import Project
from openalex_api import OpenAlexAPI

# 同一階層内の論文並列処理数（Gemini RPM 15 を超えないようレートリミッターと合わせて 2 並列に）
PARALLEL_WORKERS = 2


def _get_streamlit_ctx():
    """Streamlit 実行中なら現在の ScriptRunContext を返す。それ以外は None。

    Streamlit が無い環境（MCPサーバーなど）からの呼び出しでも警告ログを出さない。
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        # suppress_warning=True で MCP 等の非 Streamlit 環境でのノイズログを抑制
        try:
            return get_script_run_ctx(suppress_warning=True)
        except TypeError:
            # 古い Streamlit には suppress_warning が無いので引数なしで呼ぶ
            return get_script_run_ctx()
    except Exception:
        return None


def _make_worker_initializer(ctx):
    """ThreadPoolExecutor 用の initializer。
    Streamlit 実行時は各ワーカースレッドに ScriptRunContext を attach することで、
    ワーカースレッドからの st.session_state アクセスや UI 更新を可能にする。
    """
    if not ctx:
        return None

    def _init():
        try:
            from streamlit.runtime.scriptrunner import add_script_run_ctx
            add_script_run_ctx(threading.current_thread(), ctx)
        except Exception:
            # Streamlit が無い環境やバージョン不一致時は何もしない（フォールバック）
            pass

    return _init


class ArticleFinder:
    """論文探索を行うクラス"""

    @staticmethod
    def get_article_id(article: Dict) -> str:
        """
        論文の一意なIDを取得

        Args:
            article: 論文情報の辞書

        Returns:
            論文ID（"pmid:{pmid}" または "doi:{doi}"）
        """
        pmid = article.get("pmid")
        doi = article.get("doi")

        if pmid:
            return f"pmid:{pmid}"
        elif doi:
            return f"doi:{doi}"
        else:
            raise ValueError("Article must have either PMID or DOI")

    @staticmethod
    def add_article_id(article: Dict) -> Dict:
        """
        論文情報に一意なIDを追加

        Args:
            article: 論文情報の辞書

        Returns:
            IDが追加された論文情報
        """
        article["article_id"] = ArticleFinder.get_article_id(article)
        return article

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        notion_api_key: Optional[str] = None,
        notion_database_id: Optional[str] = None,
        openalex_email: Optional[str] = None
    ):
        """
        Args:
            gemini_api_key: Gemini API Key（省略時は環境変数から取得）
            gemini_model: 使用するGeminiモデル名（省略時はデフォルトモデル）
            notion_api_key: Notion API Key（省略時は環境変数から取得、未設定の場合Notion連携は無効）
            notion_database_id: Notion Database ID（省略時は環境変数から取得）
            openalex_email: OpenAlex Polite pool用メールアドレス（省略時は環境変数から取得）
        """
        self.pubmed = PubMedAPI()
        self.evaluator = GeminiEvaluator(gemini_api_key, gemini_model)
        self.openalex = OpenAlexAPI(openalex_email)

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
        relevance_threshold: int = 80,
        summary_threshold: int = 60,
        year_from: Optional[int] = None,
        include_similar: bool = True,
        max_similar: int = 20,
        include_cited_by: bool = True,
        max_cited_by: int = 20,
        include_references: bool = False,
        max_references: int = 20,
        pubmed_only: bool = False,
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
            relevance_threshold: 次階層へ進めるスコア閾値（0-100、is_relevant 判定）
            summary_threshold: 日本語要約を生成するスコア閾値（0-100、この値未満は要約をスキップ）
            year_from: この年以降の論文のみ（Noneの場合は制限なし）
            include_similar: Similar articlesを探索するか
            max_similar: Similar articlesの最大取得数（1論文あたり）
            include_cited_by: Cited byを探索するか
            max_cited_by: Cited byの最大取得数（1論文あたり）
            include_references: Referencesを探索するか
            max_references: Referencesの最大取得数（1論文あたり）
            pubmed_only: PubMed収録論文のみを対象にする（DOIのみの論文を除外）
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
                },
                "interrupted": bool  # 停止により中断された場合True
            }
        """
        # 起点PMIDまたはDOIを抽出
        start_pmid = self.pubmed.extract_pmid_from_url(start_pmid_or_url)
        start_doi = None
        start_identifier = None
        is_doi_start = False

        if start_pmid:
            # PMIDがある場合
            start_identifier = start_pmid
            is_doi_start = False
        else:
            # PMIDがない場合、DOIとして扱う
            start_doi = start_pmid_or_url.strip()
            start_identifier = start_doi
            is_doi_start = True

        if not start_identifier:
            raise ValueError(f"Invalid PMID or DOI: {start_pmid_or_url}")

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
        visited_ids: Set[str] = set()  # "pmid:xxx" または "doi:xxx" の形式

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
        identifier_type = "DOI" if is_doi_start else "PMID"
        self._notify_progress(progress_callback, f"起点論文を処理中 ({identifier_type}: {start_identifier})")

        # プロジェクトにキャッシュがあるかチェック
        if project and project.has_article(start_identifier):
            self._notify_progress(progress_callback, f"起点論文はキャッシュから取得")
            start_article = project.get_article(start_identifier)

            # スコアはキャッシュから使用するが、is_relevantは現在の閾値で再計算
            score = start_article.get("relevance_score", 0)
            start_article["is_relevant"] = score >= relevance_threshold

            # Article IDを追加（キャッシュにない場合のみ）
            if "article_id" not in start_article:
                article_id_prefix = "doi" if is_doi_start else "pmid"
                start_article["article_id"] = f"{article_id_prefix}:{start_identifier}"

            # ソース情報を追加（キャッシュにない場合のみ）
            if "source_pmid" not in start_article:
                start_article["source_pmid"] = None
                start_article["source_type"] = "起点論文"

            # 起点論文の日本語要約がなければ生成（summary_threshold 以上のみ）
            if not start_article.get("abstract_summary_ja"):
                start_abstract = start_article.get("abstract", "")
                start_title = start_article.get("title", "")
                if not start_abstract:
                    start_article["abstract_summary_ja"] = "アブストラクトが利用できません。"
                elif score < summary_threshold:
                    start_article["abstract_summary_ja"] = ""
                else:
                    try:
                        start_article["abstract_summary_ja"] = self.evaluator.summarize_abstract(start_abstract, start_title)
                        if project:
                            project.add_article(start_article)
                            project.save()
                    except Exception as e:
                        print(f"起点論文の要約生成エラー: {e}")
                        start_article["abstract_summary_ja"] = "要約生成エラー"

            # キャッシュから取得したことを示すフラグ
            start_article["is_newly_evaluated"] = False

            stats["total_skipped"] = 1
        else:
            # キャッシュにない場合は取得・評価
            if is_doi_start:
                # DOIの場合はOpenAlex APIから取得
                start_article = self.openalex.get_article_info_by_doi(start_identifier)
            else:
                # PMIDの場合はPubMed APIから取得
                start_article = self.pubmed.get_article_info(start_identifier)

            if not start_article:
                raise ValueError(f"Failed to fetch article: {identifier_type} {start_identifier}")

            # 起点論文を評価
            self._notify_progress(progress_callback, f"起点論文を評価中")

            try:
                evaluation = self.evaluator.evaluate_relevance(
                    research_theme,
                    start_article,
                    relevance_threshold
                )

                # 起点論文の日本語要約も生成（summary_threshold 以上のみ）
                start_abstract = start_article.get("abstract", "")
                start_title = start_article.get("title", "")
                if not start_abstract:
                    start_summary_ja = "アブストラクトが利用できません。"
                elif evaluation["score"] < summary_threshold:
                    start_summary_ja = ""
                else:
                    try:
                        start_summary_ja = self.evaluator.summarize_abstract(start_abstract, start_title)
                    except Exception as e:
                        print(f"起点論文の要約生成エラー: {e}")
                        start_summary_ja = "要約生成エラー"

                article_id_prefix = "doi" if is_doi_start else "pmid"
                start_article.update({
                    "article_id": f"{article_id_prefix}:{start_identifier}",  # 一意なIDを追加
                    "relevance_score": evaluation["score"],
                    "is_relevant": evaluation["is_relevant"],
                    "relevance_reasoning": evaluation["reasoning"],
                    "abstract_summary_ja": start_summary_ja,
                    "depth": 0,
                    "source_pmid": None,
                    "source_type": "起点論文",
                    "mentioned_by": [],  # 起点論文は誰からも参照されていない
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

        start_article_id = f"pmid:{start_pmid}"
        collected_articles[start_article_id] = start_article
        visited_ids.add(start_article_id)
        stats["total_found"] = 1
        if start_article.get("is_relevant"):
            stats["total_relevant"] = 1

        # 深さ優先で探索
        # 起点論文は評価スコアに関わらず、必ず次の階層へ進む
        current_layer = [start_pmid]

        # デバッグ情報をターミナルに出力
        print(f"\n{'='*60}")
        print(f"[DEBUG] 探索開始")
        print(f"  起点PMID: {start_pmid}")
        print(f"  max_depth: {max_depth}")
        print(f"  max_articles: {max_articles}")
        print(f"  include_similar: {include_similar}, max_similar: {max_similar}")
        print(f"  include_cited_by: {include_cited_by}, max_cited_by: {max_cited_by}")
        print(f"  include_references: {include_references}, max_references: {max_references}")
        print(f"  current_layer: {current_layer}")
        print(f"{'='*60}\n")

        for depth in range(1, max_depth + 1):
            print(f"\n[DEBUG] 探索階層 {depth}/{max_depth} 開始")
            print(f"  current_layer: {current_layer}")
            print(f"  collected_articles: {len(collected_articles)}件")

            # 停止チェック
            if should_stop_callback and should_stop_callback():
                print(f"[DEBUG] 停止リクエストを受け付けました")
                self._notify_progress(progress_callback, "停止リクエストを受け付けました")

                # 検索状態を保存
                if project:
                    search_state = {
                        "start_pmid": start_pmid,
                        "research_theme": research_theme,
                        "session_id": session_id,
                        "current_layer": current_layer,
                        "current_depth": depth,
                        "visited_ids": list(visited_ids),
                        "collected_articles": collected_articles,
                        "stats": stats,
                        "settings": {
                            "max_depth": max_depth,
                            "max_articles": max_articles,
                            "relevance_threshold": relevance_threshold,
                            "summary_threshold": summary_threshold,
                            "year_from": year_from,
                            "include_similar": include_similar,
                            "max_similar": max_similar,
                            "include_cited_by": include_cited_by,
                            "max_cited_by": max_cited_by,
                            "include_references": include_references,
                            "max_references": max_references,
                            "pubmed_only": pubmed_only
                        }
                    }
                    project.save_search_state(search_state)
                    self._notify_progress(progress_callback, "検索状態を保存しました")

                # 中断フラグを立てて終了
                return {
                    "articles": list(collected_articles.values()),
                    "stats": stats,
                    "interrupted": True
                }

                break

            if not current_layer:
                print(f"[DEBUG] current_layerが空のため終了")
                break

            if len(collected_articles) >= max_articles:
                print(f"[DEBUG] max_articles到達のため終了")
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
                visited_ids=visited_ids,
                collected_articles=collected_articles,
                max_articles=max_articles,
                relevance_threshold=relevance_threshold,
                summary_threshold=summary_threshold,
                year_from=year_from,
                include_similar=include_similar,
                max_similar=max_similar,
                include_cited_by=include_cited_by,
                max_cited_by=max_cited_by,
                include_references=include_references,
                max_references=max_references,
                pubmed_only=pubmed_only,
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

            # 検索完了時は保存された状態をクリア
            project.clear_search_state()

        return {
            "articles": articles_list,
            "stats": stats,
            "interrupted": False
        }

    def _explore_layer(
        self,
        pmids: List[str],
        research_theme: str,
        depth: int,
        visited_ids: Set[str],
        collected_articles: Dict[str, Dict],
        max_articles: int,
        relevance_threshold: int,
        summary_threshold: int,
        year_from: Optional[int],
        include_similar: bool,
        max_similar: int,
        include_cited_by: bool,
        max_cited_by: int,
        include_references: bool,
        max_references: int,
        pubmed_only: bool,
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
        print(f"\n[DEBUG] _explore_layer 開始")
        print(f"  処理するPMID数: {len(pmids)}")
        print(f"  PMIDs: {pmids}")
        print(f"  include_similar={include_similar}, max_similar={max_similar}")
        print(f"  include_cited_by={include_cited_by}, max_cited_by={max_cited_by}")
        print(f"  include_references={include_references}, max_references={max_references}")

        next_layer_pmids = []

        for i, identifier in enumerate(pmids):
            # identifierがPMIDかDOIかを判定
            is_doi_identifier = identifier.startswith("10.")

            # 親論文のarticle_idを生成（mentioned_by記録用）
            parent_article_id = f"doi:{identifier}" if is_doi_identifier else f"pmid:{identifier}"

            if is_doi_identifier:
                print(f"\n[DEBUG] 論文 {i+1}/{len(pmids)}: DOI {identifier} を処理中")
                self._notify_progress(
                    progress_callback,
                    f"DOI {identifier} の関連論文を取得中"
                )
            else:
                print(f"\n[DEBUG] 論文 {i+1}/{len(pmids)}: PMID {identifier} を処理中")
                self._notify_progress(
                    progress_callback,
                    f"PMID {identifier} の関連論文を取得中"
                )

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

            # 関連論文を取得（ソース情報も含む）
            # 関連論文のリスト: (identifier, source_type, extra_doi, is_doi_only) のタプルのリスト
            # identifier: PMID または DOI
            # extra_doi: OpenAlexから取得したDOI（PMIDありの場合のみ）
            # is_doi_only: DOIのみの論文かどうか
            related_pmids_with_source = []

            print(f"  [DEBUG] 関連論文取得開始")

            # Similar articles（PMIDの場合のみ）
            if include_similar and not is_doi_identifier:
                similar = self.pubmed.get_related_articles(identifier, "similar")
                # 制限数まで切り詰め
                related_pmids_with_source.extend([(p, "similar", None, False) for p in similar[:max_similar]])
                print(f"    Similar articles: {len(similar)} 件中 {len(similar[:max_similar])} 件取得")
                self._notify_progress(progress_callback, f"  Similar articles: {len(similar[:max_similar])} 件取得")
            elif include_similar and is_doi_identifier:
                print(f"    Similar articles: DOIのみの論文のためスキップ")

            # Cited by（PMIDまたはDOI）
            if include_cited_by:
                # OpenAlexからCited byを取得（DOIがある全ての文献）
                if is_doi_identifier:
                    cited_by = self.openalex.get_cited_by_by_doi(identifier, limit=max_cited_by)
                else:
                    cited_by = self.openalex.get_cited_by_by_pmid(identifier, limit=max_cited_by)
                # 制限数まで切り詰め
                for cite in cited_by[:max_cited_by]:
                    cite_pmid = cite.get("pmid")
                    cite_doi = cite.get("doi")

                    if cite_pmid:
                        # PMIDがある場合
                        related_pmids_with_source.append((cite_pmid, "cited_by", cite_doi, False))
                    elif cite_doi:
                        # DOIのみの場合
                        related_pmids_with_source.append((cite_doi, "cited_by", None, True))

                print(f"    Cited by: {len(cited_by)} 件中 {len(cited_by[:max_cited_by])} 件取得")
                self._notify_progress(progress_callback, f"  Cited by: {len(cited_by[:max_cited_by])} 件取得")

            # References（PMIDまたはDOI）
            if include_references:
                # OpenAlexからReferencesを取得（DOIがある全ての文献）
                if is_doi_identifier:
                    references = self.openalex.get_references_by_doi(identifier)
                else:
                    references = self.openalex.get_references_by_pmid(identifier)
                # 制限数まで切り詰め
                for ref in references[:max_references]:
                    ref_pmid = ref.get("pmid")
                    ref_doi = ref.get("doi")

                    if ref_pmid:
                        # PMIDがある場合
                        related_pmids_with_source.append((ref_pmid, "references", ref_doi, False))
                    elif ref_doi:
                        # DOIのみの場合
                        related_pmids_with_source.append((ref_doi, "references", None, True))

                pmid_count = len([r for r in references[:max_references] if r.get("pmid")])
                doi_only_count = len([r for r in references[:max_references] if not r.get("pmid") and r.get("doi")])
                print(f"    References (OpenAlex): {len(references)} 件中 {len(references[:max_references])} 件取得 (PMID: {pmid_count}, DOIのみ: {doi_only_count})")
                self._notify_progress(progress_callback, f"  References: {len(references[:max_references])} 件取得")

            print(f"  [DEBUG] 合計 {len(related_pmids_with_source)} 件の関連論文を取得")

            # 探索元論文に explored フラグを設定
            if project:
                explored_article = project.get_article_by_id(parent_article_id)
                if explored_article and not explored_article.get("explored"):
                    explored_article["explored"] = True
                    project.add_article(explored_article)
                    project.save()

            # 重複削除（同じIDでもソースが異なる場合、最初のもののみ保持）
            seen_ids = set()
            unique_related = []
            for identifier, source_type, extra_doi, is_doi_only in related_pmids_with_source:
                # IDを生成
                if is_doi_only:
                    article_id = f"doi:{identifier}"
                else:
                    article_id = f"pmid:{identifier}"

                if article_id not in seen_ids:
                    seen_ids.add(article_id)
                    unique_related.append((identifier, source_type, extra_doi, is_doi_only))

            related_pmids_with_source = unique_related

            # 未訪問の論文のみ処理
            new_pmids_with_source = []
            for identifier, source_type, extra_doi, is_doi_only in related_pmids_with_source:
                article_id = f"doi:{identifier}" if is_doi_only else f"pmid:{identifier}"
                if article_id not in visited_ids:
                    new_pmids_with_source.append((identifier, source_type, extra_doi, is_doi_only))

            print(f"  [DEBUG] 未訪問の論文: {len(new_pmids_with_source)} 件")
            if len(new_pmids_with_source) > 0:
                print(f"    最初の5件: {[id for id, _, _, _ in new_pmids_with_source[:5]]}")

            self._notify_progress(
                progress_callback,
                f"新規論文 {len(new_pmids_with_source)} 件を発見"
            )

            stats["total_found"] += len(new_pmids_with_source)

            # ----- 並列処理用にタスクを準備 -----
            # 並列実行のため、project.save() の排他制御に使うロック
            save_lock = threading.Lock()

            # 投入可能なタスクをフィルタリング（max_articles を超えないように）
            tasks: List[tuple] = []
            for identifier, source_type, openalex_doi, is_doi_only in new_pmids_with_source:
                if pubmed_only and is_doi_only:
                    print(f"  [DEBUG] PubMedのみモード: DOI {identifier} をスキップ")
                    continue
                if should_stop_callback and should_stop_callback():
                    self._notify_progress(progress_callback, "停止リクエストを受け付けました")
                    break
                # 投入予定数を含めて上限チェック
                if len(collected_articles) + len(tasks) >= max_articles:
                    break

                article_id = f"doi:{identifier}" if is_doi_only else f"pmid:{identifier}"
                visited_ids.add(article_id)
                tasks.append((identifier, source_type, openalex_doi, is_doi_only, article_id))

            # ----- 並列実行 -----
            # Streamlit 実行時はワーカースレッドに ScriptRunContext を attach して
            # UI コールバックや st.session_state アクセスを可能にする
            streamlit_ctx = _get_streamlit_ctx()
            worker_initializer = _make_worker_initializer(streamlit_ctx)

            with ThreadPoolExecutor(
                max_workers=PARALLEL_WORKERS,
                initializer=worker_initializer
            ) as executor:
                futures = {
                    executor.submit(
                        self._process_one_paper,
                        identifier=identifier,
                        source_type=source_type,
                        openalex_doi=openalex_doi,
                        is_doi_only=is_doi_only,
                        article_id=article_id,
                        parent_article_id=parent_article_id,
                        research_theme=research_theme,
                        relevance_threshold=relevance_threshold,
                        summary_threshold=summary_threshold,
                        year_from=year_from,
                        depth=depth,
                        session_id=session_id,
                        project=project,
                        save_lock=save_lock,
                        progress_callback=progress_callback,
                        should_stop_callback=should_stop_callback,
                        max_articles=max_articles,
                        collected_count_ref=lambda: len(collected_articles),
                    ): (identifier, source_type, openalex_doi, is_doi_only, article_id)
                    for identifier, source_type, openalex_doi, is_doi_only, article_id in tasks
                }

                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as e:
                        print(f"  [DEBUG] worker error: {e}")
                        continue

                    if result is None or result.get("skip"):
                        continue

                    article = result["article"]
                    article_id = result["article_id"]
                    identifier = result["identifier"]
                    is_doi_only = result["is_doi_only"]
                    is_cached = result["is_cached"]

                    # 共有状態はメインスレッドで更新
                    collected_articles[article_id] = article

                    if is_cached:
                        stats["total_skipped"] += 1
                    else:
                        stats["total_evaluated"] += 1
                        stats["session_article_count"] += 1

                    if article.get("is_relevant"):
                        stats["total_relevant"] += 1
                        next_layer_pmids.append(identifier)
                        score = article.get("relevance_score")
                        if not is_doi_only:
                            print(f"    PMID {identifier} を次の階層に追加 (スコア: {score})")
                        else:
                            print(f"    DOI {identifier} を次の階層に追加 (スコア: {score}) ※Similar articlesは除く")


        print(f"\n[DEBUG] _explore_layer 終了")
        print(f"  次の階層に追加する論文数: {len(next_layer_pmids)} 件")
        if next_layer_pmids:
            print(f"  識別子: {next_layer_pmids[:5]}...")

        return next_layer_pmids

    def _process_one_paper(
        self,
        identifier: str,
        source_type: str,
        openalex_doi: Optional[str],
        is_doi_only: bool,
        article_id: str,
        parent_article_id: str,
        research_theme: str,
        relevance_threshold: int,
        summary_threshold: int,
        year_from: Optional[int],
        depth: int,
        session_id: str,
        project: Optional[Project],
        save_lock: threading.Lock,
        progress_callback: Optional[Callable],
        should_stop_callback: Optional[Callable],
        max_articles: int,
        collected_count_ref: Callable[[], int],
    ) -> Optional[Dict[str, Any]]:
        """
        1論文を処理するワーカー（並列実行可）。

        - キャッシュ済みなら is_relevant の再計算 + 不足メタデータ補完
        - キャッシュ未登録なら fetch → 評価 → 要約 → citation 取得

        共有状態（collected_articles, visited_ids, stats, next_layer_pmids）は更新せず、
        呼び出し側がメインスレッドで集約する前提。project への保存のみ save_lock 配下で実施。

        Returns:
            None or {
                "skip": bool,
                "article": Dict,
                "article_id": str,
                "identifier": str,
                "is_doi_only": bool,
                "is_cached": bool,
            }
        """
        # 停止チェック（ワーカースレッドからの session_state アクセスは安全化済み）
        if self._safe_should_stop(should_stop_callback):
            return {"skip": True, "article_id": article_id, "identifier": identifier, "is_doi_only": is_doi_only, "is_cached": False, "article": None}

        # 軽量な max_articles チェック（厳密ではないが暴走防止）
        if collected_count_ref() >= max_articles:
            return {"skip": True, "article_id": article_id, "identifier": identifier, "is_doi_only": is_doi_only, "is_cached": False, "article": None}

        display_id = f"DOI:{identifier}" if is_doi_only else f"PMID:{identifier}"

        # 現在の累計件数（並列なので値は概算）
        progress_count = collected_count_ref() + 1

        # キャッシュチェック
        if project and project.has_article_by_id(article_id):
            self._notify_progress(
                progress_callback,
                f"{display_id} はキャッシュから取得 ({progress_count}/{max_articles})"
            )
            article = project.get_article_by_id(article_id)

            # スコアはキャッシュから使用するが、is_relevantは現在の閾値で再計算
            score = article.get("relevance_score", 0)
            article["is_relevant"] = score >= relevance_threshold

            # DOI 情報を補完
            if openalex_doi and not article.get("doi"):
                article["doi"] = openalex_doi

            # ソース情報を追加（キャッシュにない場合のみ）
            if "source_pmid" not in article:
                article["source_pmid"] = identifier
                article["source_type"] = source_type

            # mentioned_byを更新
            mentioned_by = article.get("mentioned_by", [])
            if not isinstance(mentioned_by, list):
                mentioned_by = []
            if parent_article_id not in mentioned_by:
                mentioned_by.append(parent_article_id)
                article["mentioned_by"] = mentioned_by
                if project:
                    with save_lock:
                        project.add_article(article)
                        project.save()
                    print(f"    {display_id} の mentioned_by を更新: {parent_article_id} を追加")

            # 日本語要約がない場合は生成（summary_threshold 以上）
            if "abstract_summary_ja" not in article or not article.get("abstract_summary_ja"):
                abstract = article.get("abstract", "")
                title = article.get("title", "")
                cached_score = article.get("relevance_score", 0)
                if not abstract:
                    article["abstract_summary_ja"] = "アブストラクトが利用できません。"
                elif cached_score < summary_threshold:
                    article["abstract_summary_ja"] = ""
                else:
                    try:
                        abstract_summary_ja = self.evaluator.summarize_abstract(abstract, title)
                        article["abstract_summary_ja"] = abstract_summary_ja
                        if project:
                            with save_lock:
                                project.add_article(article)
                                project.save()
                    except Exception as e:
                        print(f"要約生成エラー: {e}")
                        article["abstract_summary_ja"] = "要約生成エラー"

            # 被引用数がない場合は取得
            if "citation_count" not in article or article.get("citation_count") is None:
                citation_count = None
                try:
                    doi = article.get("doi")
                    pmid = article.get("pmid")
                    if doi:
                        citation_count = self.openalex.get_citation_count_by_doi(doi)
                    elif pmid:
                        citation_count = self.openalex.get_citation_count_by_pmid(pmid)

                    if citation_count is not None:
                        article["citation_count"] = citation_count
                        print(f"    被引用数取得(キャッシュ): {citation_count}")
                        if project:
                            with save_lock:
                                project.add_article(article)
                                project.save()
                    else:
                        article["citation_count"] = 0
                except Exception as e:
                    print(f"    被引用数取得エラー(キャッシュ): {e}")
                    article["citation_count"] = 0

            article["is_newly_evaluated"] = False
            return {
                "skip": False,
                "article": article,
                "article_id": article_id,
                "identifier": identifier,
                "is_doi_only": is_doi_only,
                "is_cached": True,
            }

        # ----- 新規論文 -----
        if is_doi_only:
            article = self.openalex.get_article_info_by_doi(identifier)
        else:
            article = self.pubmed.get_article_info(identifier)

        if not article:
            return {"skip": True, "article_id": article_id, "identifier": identifier, "is_doi_only": is_doi_only, "is_cached": False, "article": None}

        # DOI 情報を補完
        if not is_doi_only and openalex_doi and not article.get("doi"):
            article["doi"] = openalex_doi

        # 年フィルタ
        if year_from and article.get("pub_year"):
            if article["pub_year"] < year_from:
                return {"skip": True, "article_id": article_id, "identifier": identifier, "is_doi_only": is_doi_only, "is_cached": False, "article": None}

        self._notify_progress(
            progress_callback,
            f"{display_id} を評価中 ({progress_count}/{max_articles})"
        )

        try:
            evaluation = self.evaluator.evaluate_relevance(
                research_theme,
                article,
                relevance_threshold
            )

            # 要約生成（summary_threshold 以上のみ）
            abstract = article.get("abstract", "")
            title = article.get("title", "")
            if not abstract:
                abstract_summary_ja = "アブストラクトが利用できません。"
            elif evaluation["score"] < summary_threshold:
                abstract_summary_ja = ""
            else:
                abstract_summary_ja = self.evaluator.summarize_abstract(abstract, title)

            article.update({
                "article_id": article_id,
                "relevance_score": evaluation["score"],
                "is_relevant": evaluation["is_relevant"],
                "relevance_reasoning": evaluation["reasoning"],
                "abstract_summary_ja": abstract_summary_ja,
                "depth": depth,
                "source_pmid": identifier,
                "source_type": source_type,
                "mentioned_by": [parent_article_id],
                "search_session_id": session_id,
                "is_newly_evaluated": True,
            })

            # 被引用数
            try:
                doi = article.get("doi")
                pmid = article.get("pmid")
                if doi:
                    citation_count = self.openalex.get_citation_count_by_doi(doi)
                elif pmid:
                    citation_count = self.openalex.get_citation_count_by_pmid(pmid)
                else:
                    citation_count = None

                if citation_count is not None:
                    article["citation_count"] = citation_count
                    print(f"    被引用数取得: {citation_count}")
                else:
                    article["citation_count"] = 0
            except Exception as e:
                print(f"    被引用数取得エラー: {e}")
                article["citation_count"] = 0

            if project:
                with save_lock:
                    project.add_article(article)
                    project.save()
                # 保存後の正確な累計件数を取得
                saved_count = collected_count_ref() + 1
                self._notify_progress(
                    progress_callback,
                    f"✅ {display_id} 評価完了・保存済み (スコア: {evaluation['score']}, 保存済み: {saved_count}/{max_articles}件)"
                )

        except Exception as e:
            self._notify_progress(progress_callback, f"⚠️ {display_id} の評価中にエラー: {str(e)}")
            article.update({
                "article_id": article_id,
                "relevance_score": 0,
                "is_relevant": False,
                "relevance_reasoning": f"評価エラー: {str(e)}",
                "depth": depth,
                "source_pmid": identifier,
                "source_type": source_type,
                "mentioned_by": [parent_article_id],
                "search_session_id": session_id,
                "is_newly_evaluated": True,
            })
            if project:
                with save_lock:
                    project.add_article(article)
                    project.save()
                saved_count = collected_count_ref() + 1
                self._notify_progress(
                    progress_callback,
                    f"💾 エラーが発生しましたが、進捗を保存しました ({saved_count}/{max_articles}件)"
                )

        return {
            "skip": False,
            "article": article,
            "article_id": article_id,
            "identifier": identifier,
            "is_doi_only": is_doi_only,
            "is_cached": False,
        }

    def _notify_progress(
        self,
        callback: Optional[Callable],
        message: str
    ):
        """進捗を通知（ワーカースレッドからの呼び出しでも安全）。

        Streamlit の UI コールバックは非メインスレッドから呼ぶと例外を投げる
        ことがあるため、例外を握りつぶして stdout フォールバックする。
        """
        if callback:
            try:
                callback(message)
                return
            except Exception:
                # コールバック失敗時は stdout に出力（ワーカースレッドのケース）
                pass
        print(message)

    @staticmethod
    def _safe_should_stop(callback: Optional[Callable]) -> bool:
        """should_stop_callback を安全に評価する（ワーカースレッドからの呼び出しでも安全）。"""
        if not callback:
            return False
        try:
            return bool(callback())
        except Exception:
            # Streamlit の session_state などへのアクセスが失敗した場合は停止扱いにしない
            return False

"""
Notion API連携モジュール
論文データベースとの連携を管理
"""

import os
import time
import re
from datetime import datetime
from typing import Dict, Optional, List
import httpx
from dotenv import load_dotenv

# 環境変数を読み込み
load_dotenv()


class NotionAPI:
    """Notion APIを使って論文データベースと連携するクラス"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        database_id: Optional[str] = None
    ):
        """
        Args:
            api_key: Notion API Key（省略時は環境変数NOTION_API_KEYを使用）
            database_id: Notion Database ID（省略時は環境変数NOTION_DATABASE_IDを使用）
        """
        self.api_key = api_key or os.getenv("NOTION_API_KEY")
        self.database_id = database_id or os.getenv("NOTION_DATABASE_ID")

        if not self.api_key:
            raise ValueError(
                "Notion API key is required. "
                "Set NOTION_API_KEY environment variable or pass api_key parameter."
            )

        if not self.database_id:
            raise ValueError(
                "Notion Database ID is required. "
                "Set NOTION_DATABASE_ID environment variable or pass database_id parameter."
            )

        # APIのベースURLとヘッダーを設定
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

    def find_page_by_pmid(self, pmid: str) -> Optional[str]:
        """
        PMIDでNotionデータベースを検索してページIDを取得

        Args:
            pmid: PubMed ID

        Returns:
            ページID（見つからない場合はNone）
        """
        # リトライ設定（タイムアウト対策）
        max_retries = 3
        retry_delays = [30, 60, 90]  # 30秒、60秒、90秒

        for attempt in range(max_retries):
            try:
                # データベースを検索（タイムアウト60秒）
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(
                        f"{self.base_url}/databases/{self.database_id}/query",
                        headers=self.headers,
                        json={
                            "filter": {
                                "property": "PubMed",
                                "url": {
                                    "contains": pmid
                                }
                            }
                        }
                    )
                    response.raise_for_status()
                    result = response.json()

                    # 結果があればページIDを返す
                    if result.get("results"):
                        return result["results"][0]["id"]

                return None

            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                error_message = str(e)
                print(f"Notion API timeout for PMID {pmid} (attempt {attempt + 1}/{max_retries}): {error_message}")

                # 最後のリトライでも失敗した場合
                if attempt == max_retries - 1:
                    print(f"  → {max_retries}回リトライ後もタイムアウトしました")
                    return None

                # タイムアウトの場合は待機してリトライ
                wait_time = retry_delays[attempt]
                print(f"  → {wait_time}秒待機してリトライします...")
                time.sleep(wait_time)

            except Exception as e:
                print(f"Failed to search Notion database for PMID {pmid}: {e}")
                import traceback
                traceback.print_exc()
                return None

    def update_score(self, page_id: str, score: int) -> bool:
        """
        NotionページのScoreプロパティを更新

        Args:
            page_id: NotionページID
            score: スコア（0-100）

        Returns:
            成功した場合True、失敗した場合False
        """
        # リトライ設定（タイムアウト対策）
        max_retries = 3
        retry_delays = [30, 60, 90]  # 30秒、60秒、90秒

        for attempt in range(max_retries):
            try:
                # スコアを更新（タイムアウト60秒）
                with httpx.Client(timeout=60.0) as client:
                    response = client.patch(
                        f"{self.base_url}/pages/{page_id}",
                        headers=self.headers,
                        json={
                            "properties": {
                                "Score": {
                                    "number": score
                                }
                            }
                        }
                    )
                    response.raise_for_status()
                return True

            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                error_message = str(e)
                print(f"Notion API timeout for page {page_id} (attempt {attempt + 1}/{max_retries}): {error_message}")

                # 最後のリトライでも失敗した場合
                if attempt == max_retries - 1:
                    print(f"  → {max_retries}回リトライ後もタイムアウトしました")
                    return False

                # タイムアウトの場合は待機してリトライ
                wait_time = retry_delays[attempt]
                print(f"  → {wait_time}秒待機してリトライします...")
                time.sleep(wait_time)

            except Exception as e:
                print(f"Failed to update score for page {page_id}: {e}")
                import traceback
                traceback.print_exc()
                return False

    def get_page_properties(self, page_id: str) -> Optional[Dict]:
        """
        ページのプロパティを取得

        Args:
            page_id: NotionページID

        Returns:
            ページのプロパティ（取得失敗時はNone）
        """
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.get(
                    f"{self.base_url}/pages/{page_id}",
                    headers=self.headers
                )
                response.raise_for_status()
                return response.json().get("properties", {})
        except Exception as e:
            print(f"Failed to get page properties for {page_id}: {e}")
            return None

    def parse_project_scores(self, text: str) -> Dict[str, Dict]:
        """
        Project Scoresテキストを解析

        Args:
            text: "プロジェクトA (テーマ: 糖尿病): 60点 (2024-01-15)" 形式のテキスト

        Returns:
            {
                "プロジェクトA": {
                    "theme": "糖尿病",
                    "score": 60,
                    "date": "2024-01-15"
                }
            }
        """
        if not text:
            return {}

        scores = {}
        # 各行を解析
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue

            # パターン: プロジェクト名 (テーマ: xxx): スコア点 (日付)
            # または: プロジェクト名: スコア点 (日付)
            match = re.match(
                r'^(.+?)\s*(?:\(テーマ:\s*(.+?)\))?\s*:\s*(\d+)点\s*\((.+?)\)$',
                line
            )

            if match:
                project_name = match.group(1).strip()
                theme = match.group(2).strip() if match.group(2) else None
                score = int(match.group(3))
                date = match.group(4).strip()

                scores[project_name] = {
                    "theme": theme,
                    "score": score,
                    "date": date
                }

        return scores

    def format_project_scores(self, scores_dict: Dict[str, Dict]) -> str:
        """
        スコア辞書をテキストにフォーマット

        Args:
            scores_dict: parse_project_scores の逆

        Returns:
            "プロジェクトA (テーマ: 糖尿病): 60点 (2024-01-15)" 形式のテキスト
        """
        lines = []
        for project_name, info in sorted(scores_dict.items()):
            theme = info.get("theme")
            score = info.get("score", 0)
            date = info.get("date", "")

            if theme:
                line = f"{project_name} (テーマ: {theme}): {score}点 ({date})"
            else:
                line = f"{project_name}: {score}点 ({date})"

            lines.append(line)

        return '\n'.join(lines)

    def update_project_score(
        self,
        page_id: str,
        project_name: str,
        research_theme: Optional[str],
        score: int
    ) -> bool:
        """
        プロジェクトごとのスコアを更新

        Args:
            page_id: NotionページID
            project_name: プロジェクト名
            research_theme: 研究テーマ
            score: 関連性スコア

        Returns:
            成功した場合True
        """
        # リトライ設定
        max_retries = 3
        retry_delays = [30, 60, 90]

        for attempt in range(max_retries):
            try:
                # 既存のプロパティを取得
                properties = self.get_page_properties(page_id)
                if not properties:
                    return False

                # Project Scoresフィールドを取得
                project_scores_prop = properties.get("Project Scores", {})
                project_scores_text = ""

                # rich_textからテキストを抽出
                if project_scores_prop.get("type") == "rich_text":
                    rich_texts = project_scores_prop.get("rich_text", [])
                    if rich_texts:
                        project_scores_text = rich_texts[0].get("text", {}).get("content", "")

                # テキストを解析
                scores_dict = self.parse_project_scores(project_scores_text)

                # 現在のプロジェクトのスコアを更新
                scores_dict[project_name] = {
                    "theme": research_theme,
                    "score": score,
                    "date": datetime.now().strftime("%Y-%m-%d")
                }

                # テキストに再フォーマット
                new_project_scores_text = self.format_project_scores(scores_dict)

                # 最高スコアを計算
                max_score = max(info["score"] for info in scores_dict.values())

                # ページを更新
                with httpx.Client(timeout=60.0) as client:
                    response = client.patch(
                        f"{self.base_url}/pages/{page_id}",
                        headers=self.headers,
                        json={
                            "properties": {
                                "Project Scores": {
                                    "rich_text": [
                                        {
                                            "text": {
                                                "content": new_project_scores_text
                                            }
                                        }
                                    ]
                                },
                                "Score": {
                                    "number": max_score
                                }
                            }
                        }
                    )
                    response.raise_for_status()

                return True

            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                error_message = str(e)
                print(f"Notion API timeout for page {page_id} (attempt {attempt + 1}/{max_retries}): {error_message}")

                if attempt == max_retries - 1:
                    print(f"  → {max_retries}回リトライ後もタイムアウトしました")
                    return False

                wait_time = retry_delays[attempt]
                print(f"  → {wait_time}秒待機してリトライします...")
                time.sleep(wait_time)

            except Exception as e:
                print(f"Failed to update project score for page {page_id}: {e}")
                import traceback
                traceback.print_exc()
                return False

        return False

    def check_and_update_articles(
        self,
        articles: List[Dict],
        update_score: bool = True,
        project_name: Optional[str] = None,
        research_theme: Optional[str] = None
    ) -> List[Dict]:
        """
        複数の論文をチェックし、Notionに登録済みかどうかを確認
        オプションでプロジェクトごとのスコアを更新

        Args:
            articles: 論文情報のリスト
            update_score: スコアを自動更新するか
            project_name: プロジェクト名（プロジェクトごとのスコア管理用）
            research_theme: 研究テーマ（プロジェクトごとのスコア管理用）

        Returns:
            Notion情報を追加した論文リスト
        """
        results = []

        for article in articles:
            pmid = article.get("pmid")
            if not pmid:
                results.append(article)
                continue

            # Notionで検索
            page_id = self.find_page_by_pmid(pmid)

            # Notion情報を追加
            article_with_notion = article.copy()
            article_with_notion["in_notion"] = page_id is not None
            article_with_notion["notion_page_id"] = page_id

            # スコアを更新
            if page_id and update_score:
                score = article.get("relevance_score", 0)

                # プロジェクト名が指定されている場合はプロジェクトごとのスコア管理
                if project_name:
                    if self.update_project_score(page_id, project_name, research_theme, score):
                        article_with_notion["notion_score_updated"] = True
                    else:
                        article_with_notion["notion_score_updated"] = False
                else:
                    # 旧方式（互換性のため残す）
                    if self.update_score(page_id, score):
                        article_with_notion["notion_score_updated"] = True
                    else:
                        article_with_notion["notion_score_updated"] = False

            results.append(article_with_notion)

        return results

    def batch_check_articles(
        self,
        articles: List[Dict],
        update_score: bool = True,
        callback=None,
        project_name: Optional[str] = None,
        research_theme: Optional[str] = None
    ) -> List[Dict]:
        """
        複数の論文を一括チェック（進捗通知付き）

        Args:
            articles: 論文情報のリスト
            update_score: スコアを自動更新するか
            callback: 進捗通知用のコールバック関数 callback(current, total, pmid)
            project_name: プロジェクト名（プロジェクトごとのスコア管理用）
            research_theme: 研究テーマ（プロジェクトごとのスコア管理用）

        Returns:
            Notion情報を追加した論文リスト
        """
        results = []
        total = len(articles)

        for i, article in enumerate(articles, 1):
            pmid = article.get("pmid", "")

            if callback:
                callback(i, total, pmid)

            # 個別にチェック
            article_with_notion = self.check_and_update_articles(
                [article],
                update_score,
                project_name,
                research_theme
            )[0]
            results.append(article_with_notion)

        return results

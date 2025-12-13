"""
Notion API連携モジュール
論文データベースとの連携を管理
"""

import os
import time
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

    def check_and_update_articles(
        self,
        articles: List[Dict],
        update_score: bool = True
    ) -> List[Dict]:
        """
        複数の論文をチェックし、Notionに登録済みかどうかを確認
        オプションでスコアを更新

        Args:
            articles: 論文情報のリスト
            update_score: スコアを自動更新するか

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
        callback=None
    ) -> List[Dict]:
        """
        複数の論文を一括チェック（進捗通知付き）

        Args:
            articles: 論文情報のリスト
            update_score: スコアを自動更新するか
            callback: 進捗通知用のコールバック関数 callback(current, total, pmid)

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
            article_with_notion = self.check_and_update_articles([article], update_score)[0]
            results.append(article_with_notion)

        return results

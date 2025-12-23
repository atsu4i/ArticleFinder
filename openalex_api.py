"""
OpenAlex API連携モジュール
PMIDから引用文献（References）を取得
"""

import os
import time
import requests
from typing import List, Optional


class OpenAlexAPI:
    """OpenAlex APIクライアント"""

    BASE_URL = "https://api.openalex.org"
    REQUEST_DELAY = 0.1  # Polite pool: 10リクエスト/秒

    def __init__(self, email: Optional[str] = None):
        """
        Args:
            email: Polite pool用のメールアドレス（10倍高速化）
                   省略時は環境変数OPENALEX_EMAILから取得
        """
        self.email = email or os.environ.get("OPENALEX_EMAIL")
        self.last_request_time = 0

        # User-Agent設定（Polite pool用）
        self.headers = {
            "User-Agent": f"ArticleFinder/1.0 (mailto:{self.email})" if self.email else "ArticleFinder/1.0"
        }

        if self.email:
            print(f"[OpenAlex] Polite pool使用 (10リクエスト/秒): {self.email}")
        else:
            print(f"[OpenAlex] 通常プール使用 (1リクエスト/秒)")

    def _rate_limit(self):
        """レート制限を実施"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time

        if time_since_last_request < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - time_since_last_request)

        self.last_request_time = time.time()

    def _make_request(self, url: str, params: dict = None) -> Optional[dict]:
        """
        APIリクエストを実行

        Args:
            url: リクエストURL
            params: クエリパラメータ

        Returns:
            JSONレスポンス（エラー時はNone）
        """
        self._rate_limit()

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"[OpenAlex] API error: {e}")
            return None

    def get_work_by_pmid(self, pmid: str) -> Optional[dict]:
        """
        PMIDからOpenAlexのwork情報を取得

        Args:
            pmid: PubMed ID

        Returns:
            work情報（存在しない場合はNone）
        """
        url = f"{self.BASE_URL}/works/pmid:{pmid}"
        return self._make_request(url)

    def get_references_by_pmid(self, pmid: str) -> List[str]:
        """
        PMIDから引用文献（References）のPMIDリストを取得

        Args:
            pmid: PubMed ID

        Returns:
            引用文献のPMIDリスト（PubMedに登録されている論文のみ）
        """
        work = self.get_work_by_pmid(pmid)

        if not work:
            return []

        # referenced_worksを取得
        referenced_works = work.get("referenced_works", [])

        if not referenced_works:
            return []

        # OpenAlex IDからPMIDを抽出
        # referenced_worksはOpenAlex IDのリスト（例: "https://openalex.org/W2741809807"）
        pmids = []

        # バッチで取得（効率化）
        # 最大50件ずつ取得
        batch_size = 50
        for i in range(0, len(referenced_works), batch_size):
            batch = referenced_works[i:i + batch_size]

            # OpenAlex IDをパイプ区切りで結合
            # 例: W123|W456|W789
            openalex_ids = "|".join([work_id.split("/")[-1] for work_id in batch])

            # バッチで取得
            url = f"{self.BASE_URL}/works"
            params = {
                "filter": f"openalex_id:{openalex_ids}",
                "select": "ids"
            }

            response = self._make_request(url, params)

            if not response or "results" not in response:
                continue

            # PMIDを抽出
            for result in response["results"]:
                ids = result.get("ids", {})
                pmid_value = ids.get("pmid")

                if pmid_value:
                    # URLからPMIDを抽出（例: "https://pubmed.ncbi.nlm.nih.gov/12345678/" -> "12345678"）
                    if isinstance(pmid_value, str):
                        pmid_extracted = pmid_value.rstrip("/").split("/")[-1]
                        pmids.append(pmid_extracted)

        return pmids

    def get_cited_by_pmids(self, pmid: str, limit: int = 100) -> List[str]:
        """
        PMIDを引用している論文（Cited by）のPMIDリストを取得

        Args:
            pmid: PubMed ID
            limit: 最大取得数

        Returns:
            引用論文のPMIDリスト（PubMedに登録されている論文のみ）
        """
        # OpenAlex work IDを取得
        work = self.get_work_by_pmid(pmid)

        if not work:
            return []

        work_id = work.get("id", "").split("/")[-1]  # 例: "W2741809807"

        if not work_id:
            return []

        # cited_byで検索
        url = f"{self.BASE_URL}/works"
        params = {
            "filter": f"cites:{work_id}",
            "select": "ids",
            "per-page": min(limit, 200)  # OpenAlexの最大は200
        }

        response = self._make_request(url, params)

        if not response or "results" not in response:
            return []

        # PMIDを抽出
        pmids = []
        for result in response["results"]:
            ids = result.get("ids", {})
            pmid_value = ids.get("pmid")

            if pmid_value:
                # URLからPMIDを抽出
                if isinstance(pmid_value, str):
                    pmid_extracted = pmid_value.rstrip("/").split("/")[-1]
                    pmids.append(pmid_extracted)

        return pmids[:limit]

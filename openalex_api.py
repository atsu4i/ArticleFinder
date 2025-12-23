"""
OpenAlex API連携モジュール
PMIDから引用文献（References）を取得
"""

import os
import time
import requests
from typing import List, Optional, Dict


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

    def get_work_by_doi(self, doi: str) -> Optional[dict]:
        """
        DOIからOpenAlexのwork情報を取得

        Args:
            doi: DOI (例: "10.1234/abc")

        Returns:
            work情報（存在しない場合はNone）
        """
        # DOIの正規化（https://doi.org/を除去）
        doi_clean = doi.replace("https://doi.org/", "")
        url = f"{self.BASE_URL}/works/doi:{doi_clean}"
        return self._make_request(url)

    def get_article_info_by_doi(self, doi: str) -> Optional[Dict]:
        """
        DOIから論文情報を取得（PubMed APIの代替）

        Args:
            doi: DOI

        Returns:
            論文情報の辞書（タイトル、著者、年、ジャーナルなど）
        """
        work = self.get_work_by_doi(doi)

        if not work:
            return None

        # 著者情報を整形
        authors = []
        authorships = work.get("authorships", [])[:3]  # 最初の3人
        for authorship in authorships:
            author = authorship.get("author") or {}
            if author:
                display_name = author.get("display_name", "")
                if display_name:
                    authors.append(display_name)

        if len(work.get("authorships", [])) > 3:
            authors.append("et al.")

        authors_str = ", ".join(authors) if authors else ""

        # 出版年を取得
        pub_year = work.get("publication_year")

        # ジャーナル名を取得
        journal = ""
        primary_location = work.get("primary_location") or {}
        if primary_location:
            source = primary_location.get("source") or {}
            if source:
                journal = source.get("display_name", "")

        # アブストラクトを取得（OpenAlexにはない場合が多い）
        abstract = work.get("abstract", "")
        if not abstract:
            abstract = work.get("abstract_inverted_index", "")
            if abstract:
                # inverted indexから復元（簡易版）
                abstract = "[Abstract available in OpenAlex API]"

        return {
            "pmid": None,  # PMIDなし
            "doi": doi,
            "title": work.get("title", ""),
            "authors": authors_str,
            "journal": journal,
            "pub_date": str(pub_year) if pub_year else "",
            "pub_year": pub_year,
            "abstract": abstract,
            "url": f"https://doi.org/{doi}"
        }

    def get_references_by_pmid(self, pmid: str) -> List[Dict[str, Optional[str]]]:
        """
        PMIDから引用文献（References）のリストを取得

        Args:
            pmid: PubMed ID

        Returns:
            引用文献のリスト（DOIがある全ての文献）
            各要素は {"pmid": "...", "doi": "..."} の辞書
            PMIDがない場合はNone、DOIがない場合は除外
        """
        work = self.get_work_by_pmid(pmid)

        if not work:
            return []

        # referenced_worksを取得
        referenced_works = work.get("referenced_works", [])

        if not referenced_works:
            return []

        # OpenAlex IDからPMIDとDOIを抽出
        # referenced_worksはOpenAlex IDのリスト（例: "https://openalex.org/W2741809807"）
        references = []

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

            # PMIDとDOIを抽出
            for result in response["results"]:
                ids = result.get("ids") or {}
                if not ids:
                    continue

                # DOIを取得（必須）
                doi_value = ids.get("doi")
                if not doi_value:
                    # DOIがない文献はスキップ
                    continue

                # DOI URLから DOI を抽出（例: "https://doi.org/10.1234/abc" -> "10.1234/abc"）
                if isinstance(doi_value, str):
                    doi_extracted = doi_value.replace("https://doi.org/", "")
                else:
                    continue

                # PMIDを取得（オプション）
                pmid_value = ids.get("pmid")
                pmid_extracted = None

                if pmid_value and isinstance(pmid_value, str):
                    # URLからPMIDを抽出（例: "https://pubmed.ncbi.nlm.nih.gov/12345678/" -> "12345678"）
                    pmid_extracted = pmid_value.rstrip("/").split("/")[-1]

                references.append({
                    "pmid": pmid_extracted,
                    "doi": doi_extracted
                })

        return references

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
            ids = result.get("ids") or {}
            if not ids:
                continue

            pmid_value = ids.get("pmid")

            if pmid_value:
                # URLからPMIDを抽出
                if isinstance(pmid_value, str):
                    pmid_extracted = pmid_value.rstrip("/").split("/")[-1]
                    pmids.append(pmid_extracted)

        return pmids[:limit]

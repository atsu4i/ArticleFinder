"""
Altmetric API連携モジュール
Altmetric Attention Scoreなどのメトリクスを取得
"""

import requests
import time
from typing import Dict, Optional


class AltmetricAPI:
    """Altmetric APIのラッパークラス"""

    BASE_URL = "https://api.altmetric.com/v1"
    REQUEST_DELAY = 1.0  # 無料プランのレート制限を考慮して1秒間隔

    def __init__(self):
        self.last_request_time = 0

    def _rate_limit(self):
        """レート制限を適用"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - time_since_last_request)
        self.last_request_time = time.time()

    def _make_request(self, endpoint: str) -> Optional[Dict]:
        """APIリクエストを実行"""
        self._rate_limit()
        url = f"{self.BASE_URL}/{endpoint}"

        # User-Agentヘッダーを追加（APIアクセスに必要）
        headers = {
            "User-Agent": "ArticleFinder/1.0 (Educational Research Tool; mailto:research@example.com)"
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)

            # 404の場合はメトリクスが存在しない
            if response.status_code == 404:
                return None

            # 403の場合はアクセス制限（静かに失敗）
            if response.status_code == 403:
                print(f"Altmetric API access forbidden for {endpoint} (403)")
                return None

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Altmetric API request failed: {e}")
            return None

    def get_metrics_by_doi(self, doi: str) -> Optional[Dict]:
        """
        DOIからAltmetricメトリクスを取得

        Args:
            doi: DOI

        Returns:
            メトリクス情報の辞書（メトリクスが存在しない場合はNone）
            {
                "score": float,  # Altmetric Attention Score
                "readers_count": int,  # Mendeley readers
                "cited_by_tweeters_count": int,  # Twitter mentions
                "cited_by_posts_count": int,  # Blog posts
                "cited_by_fbwalls_count": int,  # Facebook posts
                "cited_by_msm_count": int,  # News outlets
                "badge_url": str,  # Badge image URL
                "details_url": str  # Altmetric details page URL
            }
        """
        if not doi:
            return None

        endpoint = f"doi/{doi}"
        data = self._make_request(endpoint)

        if not data:
            return None

        return self._extract_metrics(data)

    def get_metrics_by_pmid(self, pmid: str) -> Optional[Dict]:
        """
        PMIDからAltmetricメトリクスを取得

        Args:
            pmid: PubMed ID

        Returns:
            メトリクス情報の辞書（メトリクスが存在しない場合はNone）
        """
        if not pmid:
            return None

        endpoint = f"pmid/{pmid}"
        data = self._make_request(endpoint)

        if not data:
            return None

        return self._extract_metrics(data)

    def _extract_metrics(self, data: Dict) -> Dict:
        """APIレスポンスから必要なメトリクスを抽出"""
        return {
            "score": data.get("score", 0),
            "readers_count": data.get("readers", {}).get("count", 0),
            "cited_by_tweeters_count": data.get("cited_by_tweeters_count", 0),
            "cited_by_posts_count": data.get("cited_by_posts_count", 0),
            "cited_by_fbwalls_count": data.get("cited_by_fbwalls_count", 0),
            "cited_by_msm_count": data.get("cited_by_msm_count", 0),
            "badge_url": data.get("images", {}).get("small", ""),
            "details_url": data.get("details_url", "")
        }

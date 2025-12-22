"""
PubMed API連携モジュール
E-utilities APIを使用して論文情報を取得
"""

import requests
import time
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs


class PubMedAPI:
    """PubMed E-utilities APIのラッパークラス"""

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    REQUEST_DELAY = 0.34  # 1秒に3リクエストまで（安全のため0.34秒間隔）

    def __init__(self):
        self.last_request_time = 0

    def _rate_limit(self):
        """レート制限を適用"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - time_since_last_request)
        self.last_request_time = time.time()

    def _make_request(self, endpoint: str, params: Dict) -> Dict:
        """APIリクエストを実行"""
        self._rate_limit()
        url = f"{self.BASE_URL}{endpoint}"

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API request failed: {e}")
            return {}

    def extract_pmid_from_url(self, url_or_pmid: str) -> Optional[str]:
        """
        URLまたはPMID文字列からPMIDを抽出

        対応形式:
        - https://pubmed.ncbi.nlm.nih.gov/12345678/
        - 12345678
        """
        # 既に数字のみの場合はそのまま返す
        if url_or_pmid.strip().isdigit():
            return url_or_pmid.strip()

        # URLからPMIDを抽出
        try:
            parsed = urlparse(url_or_pmid)
            # パスから数字を抽出
            match = re.search(r'/(\d+)/?', parsed.path)
            if match:
                return match.group(1)

            # クエリパラメータから抽出
            query_params = parse_qs(parsed.query)
            if 'id' in query_params:
                return query_params['id'][0]
        except Exception as e:
            print(f"Failed to extract PMID: {e}")

        return None

    def get_article_info(self, pmid: str) -> Optional[Dict]:
        """
        論文の詳細情報を取得

        Args:
            pmid: PubMed ID

        Returns:
            論文情報の辞書（タイトル、著者、年、ジャーナル、アブストラクトなど）
        """
        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "json"
        }

        data = self._make_request("esummary.fcgi", params)

        if not data or "result" not in data:
            return None

        result = data["result"]
        if pmid not in result:
            return None

        article = result[pmid]

        # アブストラクトを取得するために別途EFetchを呼ぶ
        abstract = self._fetch_abstract(pmid)

        return {
            "pmid": pmid,
            "title": article.get("title", ""),
            "authors": self._format_authors(article.get("authors", [])),
            "journal": article.get("fulljournalname", ""),
            "pub_date": article.get("pubdate", ""),
            "pub_year": self._extract_year(article.get("pubdate", "")),
            "abstract": abstract,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        }

    def _fetch_abstract(self, pmid: str) -> str:
        """アブストラクトを取得（XML形式で確実に取得）"""
        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "xml"
        }

        self._rate_limit()
        url = f"{self.BASE_URL}efetch.fcgi"

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            xml_text = response.text

            # XMLからアブストラクトを抽出
            # <AbstractText>タグの内容を抽出
            import re

            # 複数のAbstractTextタグがある場合もあるので、すべて取得
            abstract_matches = re.findall(r'<AbstractText[^>]*>(.*?)</AbstractText>', xml_text, re.DOTALL)

            if abstract_matches:
                # すべてのアブストラクトテキストを結合
                abstract = ' '.join(abstract_matches)
                # HTMLエンティティをデコード
                abstract = abstract.replace('&lt;', '<').replace('&gt;', '>')
                abstract = abstract.replace('&amp;', '&').replace('&quot;', '"')
                # 余分な空白を削除
                abstract = ' '.join(abstract.split())
                return abstract

            # AbstractTextが見つからない場合、OtherAbstractタグも試す
            other_abstract_matches = re.findall(r'<OtherAbstract[^>]*>(.*?)</OtherAbstract>', xml_text, re.DOTALL)
            if other_abstract_matches:
                # OtherAbstract内のAbstractTextを探す
                for other_abstract in other_abstract_matches:
                    texts = re.findall(r'<AbstractText[^>]*>(.*?)</AbstractText>', other_abstract, re.DOTALL)
                    if texts:
                        abstract = ' '.join(texts)
                        abstract = abstract.replace('&lt;', '<').replace('&gt;', '>')
                        abstract = abstract.replace('&amp;', '&').replace('&quot;', '"')
                        abstract = ' '.join(abstract.split())
                        return abstract

            return ""

        except Exception as e:
            print(f"Failed to fetch abstract for PMID {pmid}: {e}")
            return ""

    def _format_authors(self, authors: List[Dict]) -> str:
        """著者リストをフォーマット"""
        if not authors:
            return ""

        author_names = [author.get("name", "") for author in authors[:3]]
        if len(authors) > 3:
            author_names.append("et al.")

        return ", ".join(author_names)

    def _extract_year(self, pub_date: str) -> Optional[int]:
        """出版日から年を抽出"""
        match = re.search(r'(\d{4})', pub_date)
        if match:
            return int(match.group(1))
        return None

    def get_related_articles(self, pmid: str, relation_type: str = "similar") -> List[str]:
        """
        関連論文のPMIDリストを取得

        Args:
            pmid: PubMed ID
            relation_type: "similar" (類似論文), "cited_by" (引用論文), "references" (引用文献)

        Returns:
            関連論文のPMIDリスト
        """
        linkname_map = {
            "similar": "pubmed_pubmed",
            "cited_by": "pubmed_pubmed_citedin",
            "references": "pubmed_pubmed_refs"
        }

        linkname = linkname_map.get(relation_type)
        if not linkname:
            print(f"Unknown relation type: {relation_type}")
            return []

        params = {
            "dbfrom": "pubmed",
            "id": pmid,
            "linkname": linkname,
            "retmode": "json"
        }

        data = self._make_request("elink.fcgi", params)

        if not data or "linksets" not in data:
            return []

        linksets = data["linksets"]
        if not linksets or not linksets[0].get("linksetdbs"):
            return []

        linksetdbs = linksets[0]["linksetdbs"]
        if not linksetdbs:
            return []

        # PMIDリストを取得
        pmids = [str(link_id) for link_id in linksetdbs[0].get("links", [])]

        return pmids

    def get_all_related_articles(self, pmid: str) -> Dict[str, List[str]]:
        """
        similar articles、cited by、referencesを取得

        Args:
            pmid: PubMed ID

        Returns:
            {
                "similar": [pmid1, pmid2, ...],
                "cited_by": [pmid3, pmid4, ...],
                "references": [pmid5, pmid6, ...]
            }
        """
        return {
            "similar": self.get_related_articles(pmid, "similar"),
            "cited_by": self.get_related_articles(pmid, "cited_by"),
            "references": self.get_related_articles(pmid, "references")
        }

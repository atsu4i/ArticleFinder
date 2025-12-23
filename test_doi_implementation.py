#!/usr/bin/env python3
"""
DOI実装のテストスクリプト
OpenAlexからDOI情報が取得できることを確認
PMIDなし文献の取得も確認
"""

import os
from openalex_api import OpenAlexAPI
from pubmed_api import PubMedAPI
from article_finder import ArticleFinder

def test_openalex_references_with_doi():
    """OpenAlexからReferencesをDOI付きで取得"""
    print("=" * 60)
    print("OpenAlex References取得テスト (DOI付き)")
    print("=" * 60)

    # OpenAlex APIを初期化
    openalex = OpenAlexAPI(os.getenv("OPENALEX_EMAIL"))

    # テスト用PMID
    test_pmid = "31243158"

    print(f"\nテストPMID: {test_pmid}")
    print("-" * 60)

    # Referencesを取得
    references = openalex.get_references_by_pmid(test_pmid)

    print(f"\n取得件数: {len(references)} 件")
    print("-" * 60)

    # 最初の5件を表示
    print("\n最初の5件:")
    for i, ref in enumerate(references[:5], 1):
        pmid = ref.get("pmid", "N/A")
        doi = ref.get("doi", "N/A")
        print(f"\n{i}. PMID: {pmid}")
        print(f"   DOI: {doi}")

    # 統計
    with_pmid = len([r for r in references if r.get("pmid")])
    without_pmid = len([r for r in references if not r.get("pmid")])

    print("\n" + "=" * 60)
    print("統計:")
    print(f"  PMIDあり: {with_pmid} 件")
    print(f"  PMIDなし: {without_pmid} 件")
    print(f"  合計: {len(references)} 件")
    print("=" * 60)

    return references


def test_pubmed_doi_extraction():
    """PubMedからDOI情報を取得"""
    print("\n" + "=" * 60)
    print("PubMed DOI取得テスト")
    print("=" * 60)

    # PubMed APIを初期化
    pubmed = PubMedAPI()

    # テスト用PMID（DOIがあることが確認されているもの）
    test_pmids = ["31243158", "34716798"]

    for pmid in test_pmids:
        print(f"\nPMID: {pmid}")
        print("-" * 60)

        article = pubmed.get_article_info(pmid)

        if article:
            doi = article.get("doi", "N/A")
            title = article.get("title", "N/A")[:80] + "..."

            print(f"タイトル: {title}")
            print(f"DOI: {doi}")
        else:
            print("論文情報の取得に失敗")

    print("\n" + "=" * 60)


def test_doi_only_article():
    """DOIのみの文献情報を取得"""
    print("\n" + "=" * 60)
    print("DOIのみの文献情報取得テスト")
    print("=" * 60)

    # OpenAlex APIを初期化
    openalex = OpenAlexAPI(os.getenv("OPENALEX_EMAIL"))

    # テスト用DOI（PMIDがない論文）
    test_doi = "10.1037/1040-3590.11.3.326"

    print(f"\nテストDOI: {test_doi}")
    print("-" * 60)

    article = openalex.get_article_info_by_doi(test_doi)

    if article:
        print(f"タイトル: {article.get('title', 'N/A')}")
        print(f"著者: {article.get('authors', 'N/A')}")
        print(f"ジャーナル: {article.get('journal', 'N/A')}")
        print(f"出版年: {article.get('pub_year', 'N/A')}")
        print(f"PMID: {article.get('pmid', 'N/A')}")
        print(f"DOI: {article.get('doi', 'N/A')}")
        print(f"URL: {article.get('url', 'N/A')}")

        # ArticleFinderのget_article_idをテスト
        article_id = ArticleFinder.get_article_id(article)
        print(f"\nArticle ID: {article_id}")

        if article_id.startswith("doi:"):
            print("✅ DOIのみの文献として正しく識別されました")
        else:
            print("❌ エラー: Article IDが正しくありません")
    else:
        print("❌ 文献情報の取得に失敗")

    print("=" * 60)


if __name__ == "__main__":
    # OpenAlexテスト
    references = test_openalex_references_with_doi()

    # PubMedテスト
    test_pubmed_doi_extraction()

    # DOIのみの文献テスト
    test_doi_only_article()

    print("\n✅ 全テスト完了")

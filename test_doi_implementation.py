#!/usr/bin/env python3
"""
DOI実装のテストスクリプト
OpenAlexからDOI情報が取得できることを確認
"""

import os
from openalex_api import OpenAlexAPI
from pubmed_api import PubMedAPI

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


if __name__ == "__main__":
    # OpenAlexテスト
    references = test_openalex_references_with_doi()

    # PubMedテスト
    test_pubmed_doi_extraction()

    print("\n✅ テスト完了")

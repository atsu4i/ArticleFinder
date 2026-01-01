"""
既存プロジェクトの論文に被引用数を追加するスクリプト

Usage:
    python add_citation_counts.py <project_name>
    例: python add_citation_counts.py Social_Robot_2
"""

import sys
from project_manager import ProjectManager
from openalex_api import OpenAlexAPI


def add_citation_counts_to_project(project_name: str):
    """
    プロジェクトの全論文に被引用数を追加

    Args:
        project_name: プロジェクト名（safe_name）
    """
    # プロジェクトマネージャーとOpenAlex APIを初期化
    pm = ProjectManager()
    openalex = OpenAlexAPI()

    print(f"\n{'='*60}")
    print(f"プロジェクト '{project_name}' の論文に被引用数を追加します")
    print(f"{'='*60}\n")

    # プロジェクトを読み込む
    try:
        project = pm.load_project(project_name)
        print(f"✅ プロジェクトを読み込みました: {project.metadata.get('name')}")
        print(f"   論文数: {len(project.articles)}件\n")
    except Exception as e:
        print(f"❌ プロジェクトの読み込みに失敗: {e}")
        return

    # 被引用数を取得
    total = len(project.articles)
    updated = 0
    skipped = 0
    failed = 0

    for i, (article_id, article) in enumerate(project.articles.items(), 1):
        pmid = article.get("pmid")
        doi = article.get("doi")
        title = article.get("title", "不明")[:60]

        # 既に被引用数がある場合はスキップ
        if "citation_count" in article and article.get("citation_count") is not None:
            print(f"[{i}/{total}] スキップ（既存）: {title}... (被引用数: {article['citation_count']})")
            skipped += 1
            continue

        print(f"[{i}/{total}] 取得中: {title}...")

        # 被引用数を取得
        citation_count = None
        try:
            if doi:
                citation_count = openalex.get_citation_count_by_doi(doi)
                print(f"          → DOI {doi}: 被引用数 {citation_count}")
            elif pmid:
                citation_count = openalex.get_citation_count_by_pmid(pmid)
                print(f"          → PMID {pmid}: 被引用数 {citation_count}")
            else:
                print(f"          → PMIDもDOIもありません")
                failed += 1
                continue

            if citation_count is not None:
                article["citation_count"] = citation_count
                project.articles[article_id] = article
                updated += 1
            else:
                print(f"          → 被引用数を取得できませんでした")
                article["citation_count"] = 0
                project.articles[article_id] = article
                failed += 1

        except Exception as e:
            print(f"          → エラー: {e}")
            article["citation_count"] = 0
            project.articles[article_id] = article
            failed += 1

    # プロジェクトを保存
    try:
        project.save()
        print(f"\n✅ プロジェクトを保存しました")
    except Exception as e:
        print(f"\n❌ プロジェクトの保存に失敗: {e}")
        return

    # 統計情報を表示
    print(f"\n{'='*60}")
    print(f"完了")
    print(f"{'='*60}")
    print(f"総論文数:          {total}件")
    print(f"更新:              {updated}件")
    print(f"スキップ（既存）:  {skipped}件")
    print(f"失敗:              {failed}件")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python add_citation_counts.py <project_name>")
        print("例: python add_citation_counts.py Social_Robot_2")
        sys.exit(1)

    project_name = sys.argv[1]
    add_citation_counts_to_project(project_name)

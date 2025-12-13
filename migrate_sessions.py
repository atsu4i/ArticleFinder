"""
既存プロジェクトのセッション情報をマイグレーションするスクリプト

実行方法:
    python migrate_sessions.py
"""

from datetime import datetime, timedelta
from pathlib import Path
from project_manager import ProjectManager
from typing import List, Dict


def migrate_project_sessions(project_manager: ProjectManager, dry_run: bool = False):
    """
    すべてのプロジェクトのセッション情報をマイグレーション

    Args:
        project_manager: ProjectManagerインスタンス
        dry_run: Trueの場合は変更を保存しない（確認用）
    """
    projects = project_manager.list_projects()

    if not projects:
        print("マイグレーション対象のプロジェクトがありません。")
        return

    print(f"\n{len(projects)}個のプロジェクトを処理します...\n")

    for project_info in projects:
        project_name = project_info.get("safe_name")
        print(f"{'='*60}")
        print(f"プロジェクト: {project_info.get('name')} ({project_name})")
        print(f"{'='*60}")

        try:
            project = project_manager.load_project(project_name)
            migrate_single_project(project, dry_run)
        except Exception as e:
            print(f"❌ エラー: {e}")
            import traceback
            traceback.print_exc()

        print()


def migrate_single_project(project, dry_run: bool = False):
    """
    単一プロジェクトのセッション情報をマイグレーション

    Args:
        project: Projectインスタンス
        dry_run: Trueの場合は変更を保存しない
    """
    articles = project.get_all_articles()

    if not articles:
        print("  論文がありません。スキップします。")
        return

    print(f"  論文数: {len(articles)}件")

    # ステップ1: 文字列形式のsearch_session_idを配列に変換
    converted_count = 0
    for article in articles:
        old_session_id = article.get("search_session_id")
        existing_sessions = article.get("search_session_ids", [])

        # 既に配列形式の場合はスキップ
        if isinstance(existing_sessions, list) and len(existing_sessions) > 0:
            continue

        # 文字列形式の古いデータを配列に変換
        if old_session_id and isinstance(old_session_id, str):
            article["search_session_ids"] = [old_session_id]
            del article["search_session_id"]
            converted_count += 1

    if converted_count > 0:
        print(f"  ✅ {converted_count}件の論文で文字列形式を配列形式に変換しました")

    # ステップ2: evaluated_atを元にセッションを推定
    articles_without_session = [
        a for a in articles
        if not a.get("search_session_ids") or len(a.get("search_session_ids", [])) == 0
    ]

    if not articles_without_session:
        print("  ✅ すべての論文にセッション情報があります")
        if not dry_run:
            # 論文情報を保存
            for article in articles:
                pmid = article.get("pmid")
                if pmid:
                    project.articles[pmid] = article
            project.save()
            print("  💾 変更を保存しました")
        return

    print(f"  ⚠️  {len(articles_without_session)}件の論文にセッション情報がありません")
    print(f"  評価日時を元にセッションを推定します...")

    # evaluated_atでソート
    articles_with_time = [
        a for a in articles_without_session
        if a.get("evaluated_at")
    ]

    if not articles_with_time:
        print("  ❌ evaluated_atがないため、セッション推定できません")
        return

    articles_with_time.sort(key=lambda x: x.get("evaluated_at", ""))

    # 5分以内の論文を同じセッションとしてグループ化
    SESSION_GAP_MINUTES = 5
    sessions: List[List[Dict]] = []
    current_session: List[Dict] = []
    last_time = None

    for article in articles_with_time:
        evaluated_at_str = article.get("evaluated_at")
        try:
            evaluated_at = datetime.fromisoformat(evaluated_at_str)

            # 最初の論文、または前の論文から5分以上経過している場合は新しいセッション
            if last_time is None or (evaluated_at - last_time) > timedelta(minutes=SESSION_GAP_MINUTES):
                if current_session:
                    sessions.append(current_session)
                current_session = [article]
            else:
                current_session.append(article)

            last_time = evaluated_at

        except Exception as e:
            print(f"    ⚠️  日時パースエラー ({evaluated_at_str}): {e}")
            continue

    # 最後のセッションを追加
    if current_session:
        sessions.append(current_session)

    print(f"  ✅ {len(sessions)}個のセッションを検出しました")

    # 各セッションにセッションIDを付与
    session_count = 0
    article_count = 0

    for session_articles in sessions:
        # セッションIDは最初の論文の評価日時
        session_id = session_articles[0].get("evaluated_at")
        session_date = datetime.fromisoformat(session_id).strftime("%Y-%m-%d %H:%M")

        print(f"    セッション {session_count + 1}: {session_date} ({len(session_articles)}件)")

        for article in session_articles:
            article["search_session_ids"] = [session_id]
            article_count += 1

        session_count += 1

    print(f"  ✅ {article_count}件の論文にセッション情報を付与しました")

    # プロジェクトのメタデータも更新
    if "search_sessions" not in project.metadata:
        project.metadata["search_sessions"] = []

    # 既存のセッション情報をクリア（再構築）
    project.metadata["search_sessions"] = []

    # すべての論文からセッション情報を集計
    session_stats: Dict[str, int] = {}
    for article in articles:
        for session_id in article.get("search_session_ids", []):
            if session_id:
                session_stats[session_id] = session_stats.get(session_id, 0) + 1

    # セッション情報を追加
    for session_id, count in sorted(session_stats.items()):
        project.metadata["search_sessions"].append({
            "session_id": session_id,
            "article_count": count,
            "timestamp": session_id
        })

    print(f"  ✅ {len(session_stats)}個のセッション情報をメタデータに追加しました")

    if not dry_run:
        # 論文情報を保存
        for article in articles:
            pmid = article.get("pmid")
            if pmid:
                project.articles[pmid] = article

        project.save()
        print("  💾 変更を保存しました")
    else:
        print("  ⚠️  DRY RUNモード: 変更は保存されませんでした")


def main():
    """メイン処理"""
    import sys

    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("\n" + "="*60)
        print("DRY RUNモード: 変更は保存されません")
        print("="*60 + "\n")
    else:
        print("\n" + "="*60)
        print("セッション情報マイグレーション")
        print("="*60)
        print("このスクリプトは既存プロジェクトの論文データを変更します。")
        print("実行前に必ずバックアップを取ってください。")
        print()
        response = input("続行しますか？ (yes/no): ").strip().lower()

        if response != "yes":
            print("マイグレーションをキャンセルしました。")
            return

        print()

    # プロジェクトマネージャーを初期化
    project_manager = ProjectManager()

    # マイグレーション実行
    migrate_project_sessions(project_manager, dry_run)

    print("\n" + "="*60)
    print("マイグレーション完了")
    print("="*60)

    if dry_run:
        print("\n変更を実際に適用するには、--dry-runオプションなしで実行してください:")
        print("  python migrate_sessions.py")


if __name__ == "__main__":
    main()

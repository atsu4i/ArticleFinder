"""
プロジェクト管理モジュール
検索プロジェクトを管理し、重複評価を防止
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class ProjectManager:
    """プロジェクト管理クラス"""

    def __init__(self, projects_dir: str = "projects"):
        """
        Args:
            projects_dir: プロジェクトを保存するディレクトリ
        """
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(exist_ok=True)

    def list_projects(self) -> List[Dict]:
        """
        プロジェクト一覧を取得

        Returns:
            プロジェクト情報のリスト
        """
        projects = []

        for project_path in self.projects_dir.iterdir():
            if not project_path.is_dir():
                continue

            metadata_path = project_path / "metadata.json"
            if not metadata_path.exists():
                continue

            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    projects.append(metadata)
            except Exception as e:
                print(f"Failed to load project metadata: {project_path.name} - {e}")

        # 更新日時でソート（新しい順）
        projects.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

        return projects

    def create_project(
        self,
        name: str,
        research_theme: str,
        settings: Optional[Dict] = None
    ) -> 'Project':
        """
        新規プロジェクトを作成

        Args:
            name: プロジェクト名
            research_theme: 研究テーマ
            settings: 検索設定

        Returns:
            Projectオブジェクト
        """
        # プロジェクト名のバリデーション
        safe_name = self._sanitize_project_name(name)
        project_path = self.projects_dir / safe_name

        if project_path.exists():
            raise ValueError(f"Project '{name}' already exists")

        project_path.mkdir(parents=True)

        # メタデータを作成
        metadata = {
            "name": name,
            "safe_name": safe_name,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "research_theme": research_theme,
            "settings": settings or {},
            "stats": {
                "total_articles": 0,
                "total_evaluated": 0,
                "total_relevant": 0
            },
            "search_sessions": []  # 検索セッション履歴
        }

        # メタデータを保存
        metadata_path = project_path / "metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        # 空の論文データベースを作成
        articles_path = project_path / "articles.json"
        with open(articles_path, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

        return Project(project_path)

    def load_project(self, name: str) -> 'Project':
        """
        既存プロジェクトを読み込み

        Args:
            name: プロジェクト名（safe_nameまたは元の名前）

        Returns:
            Projectオブジェクト
        """
        # safe_nameとして試す
        project_path = self.projects_dir / name

        if not project_path.exists():
            # 元の名前から変換して試す
            safe_name = self._sanitize_project_name(name)
            project_path = self.projects_dir / safe_name

        if not project_path.exists():
            raise ValueError(f"Project '{name}' not found")

        return Project(project_path)

    def delete_project(self, name: str):
        """
        プロジェクトを削除

        Args:
            name: プロジェクト名
        """
        project = self.load_project(name)

        # ディレクトリごと削除
        import shutil
        shutil.rmtree(project.project_path)

    def _sanitize_project_name(self, name: str) -> str:
        """
        プロジェクト名をファイルシステムに安全な名前に変換

        Args:
            name: プロジェクト名

        Returns:
            安全な名前
        """
        # 使用できない文字を置換
        safe_name = name.replace('/', '_').replace('\\', '_').replace(':', '_')
        safe_name = safe_name.replace('*', '_').replace('?', '_').replace('"', '_')
        safe_name = safe_name.replace('<', '_').replace('>', '_').replace('|', '_')

        # 空白をアンダースコアに
        safe_name = safe_name.replace(' ', '_')

        # 長さ制限
        if len(safe_name) > 100:
            safe_name = safe_name[:100]

        return safe_name


class Project:
    """プロジェクトクラス"""

    def __init__(self, project_path: Path):
        """
        Args:
            project_path: プロジェクトディレクトリのパス
        """
        self.project_path = Path(project_path)
        self.metadata_path = self.project_path / "metadata.json"
        self.articles_path = self.project_path / "articles.json"

        # メタデータを読み込み
        self._load_metadata()

        # 論文データを読み込み
        self._load_articles()

    def _load_metadata(self):
        """メタデータを読み込み"""
        with open(self.metadata_path, 'r', encoding='utf-8') as f:
            self.metadata = json.load(f)

    def _load_articles(self):
        """論文データを読み込み"""
        with open(self.articles_path, 'r', encoding='utf-8') as f:
            self.articles = json.load(f)

    def save(self):
        """プロジェクトを保存"""
        # 更新日時を更新
        self.metadata["updated_at"] = datetime.now().isoformat()

        # メタデータを保存
        with open(self.metadata_path, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

        # 論文データを保存
        with open(self.articles_path, 'w', encoding='utf-8') as f:
            json.dump(self.articles, f, ensure_ascii=False, indent=2)

    def has_article(self, pmid: str) -> bool:
        """
        論文が既に評価済みかチェック

        Args:
            pmid: PubMed ID

        Returns:
            評価済みの場合True
        """
        return pmid in self.articles

    def get_article(self, pmid: str) -> Optional[Dict]:
        """
        論文情報を取得

        Args:
            pmid: PubMed ID

        Returns:
            論文情報（存在しない場合None）
        """
        return self.articles.get(pmid)

    def add_article(self, article: Dict):
        """
        論文を追加

        Args:
            article: 論文情報（pmidを含む）
        """
        pmid = article.get("pmid")
        if not pmid:
            raise ValueError("Article must have 'pmid' field")

        # 評価日時を追加
        article["evaluated_at"] = datetime.now().isoformat()

        self.articles[pmid] = article

        # 統計情報を更新
        self._update_stats()

    def get_all_articles(self) -> List[Dict]:
        """
        全論文を取得

        Returns:
            論文情報のリスト
        """
        return list(self.articles.values())

    def get_relevant_articles(self) -> List[Dict]:
        """
        関連性ありの論文のみ取得

        Returns:
            関連論文のリスト
        """
        return [
            article for article in self.articles.values()
            if article.get("is_relevant", False)
        ]

    def delete_article(self, pmid: str) -> bool:
        """
        論文を削除

        Args:
            pmid: PubMed ID

        Returns:
            削除に成功した場合True、論文が存在しない場合False
        """
        if pmid in self.articles:
            del self.articles[pmid]
            self._update_stats()
            return True
        return False

    def _update_stats(self):
        """統計情報を更新"""
        articles_list = list(self.articles.values())

        self.metadata["stats"] = {
            "total_articles": len(articles_list),
            "total_evaluated": len(articles_list),
            "total_relevant": sum(
                1 for a in articles_list
                if a.get("is_relevant", False)
            )
        }

    def update_settings(self, settings: Dict):
        """
        検索設定を更新

        Args:
            settings: 検索設定
        """
        self.metadata["settings"] = settings

    def get_stats(self) -> Dict:
        """
        統計情報を取得

        Returns:
            統計情報
        """
        return self.metadata.get("stats", {})

    def add_search_session(self, session_id: str, article_count: int):
        """
        検索セッションを追加

        Args:
            session_id: セッションID（タイムスタンプ）
            article_count: このセッションで追加された論文数
        """
        # search_sessionsが存在しない場合は初期化（既存プロジェクトとの互換性）
        if "search_sessions" not in self.metadata:
            self.metadata["search_sessions"] = []

        # 新しいセッションを追加
        self.metadata["search_sessions"].append({
            "session_id": session_id,
            "article_count": article_count,
            "timestamp": session_id  # session_idがタイムスタンプなので同じ値を使用
        })

    def get_search_sessions(self) -> List[Dict]:
        """
        検索セッション履歴を取得

        Returns:
            検索セッションのリスト（新しい順）
        """
        sessions = self.metadata.get("search_sessions", [])
        # 新しい順にソート
        return sorted(sessions, key=lambda x: x.get("timestamp", ""), reverse=True)

    def export_to_json(self) -> str:
        """
        プロジェクト全体をJSONとしてエクスポート

        Returns:
            JSON文字列
        """
        export_data = {
            "metadata": self.metadata,
            "articles": list(self.articles.values())
        }

        return json.dumps(export_data, ensure_ascii=False, indent=2)

"""
論文検索自動化ツール - Streamlit WebGUI
"""

import streamlit as st
import json
import os
from datetime import datetime
from typing import Optional, List, Dict
from article_finder import ArticleFinder
from project_manager import ProjectManager
from gemini_evaluator import GeminiEvaluator
from pyvis.network import Network
import streamlit.components.v1 as components
import tempfile


def save_api_key_to_env(api_key: str) -> bool:
    """
    API KeyをSave to .env file

    Args:
        api_key: Gemini API Key

    Returns:
        True if successfully saved, False otherwise
    """
    try:
        env_path = os.path.join(os.path.dirname(__file__), '.env')

        # .envファイルの内容を読み込む
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # GEMINI_API_KEYの行を更新
            updated = False
            for i, line in enumerate(lines):
                if line.startswith('GEMINI_API_KEY='):
                    lines[i] = f'GEMINI_API_KEY={api_key}\n'
                    updated = True
                    break

            # 既存の行がない場合は追加
            if not updated:
                lines.append(f'GEMINI_API_KEY={api_key}\n')
        else:
            # .envファイルが存在しない場合は新規作成
            lines = [
                '# Gemini API Key\n',
                '# Get your API key from: https://makersuite.google.com/app/apikey\n',
                f'GEMINI_API_KEY={api_key}\n'
            ]

        # .envファイルに書き込む
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        return True

    except Exception as e:
        print(f"Failed to save API key to .env: {e}")
        return False


def is_valid_api_key(api_key: str) -> bool:
    """
    API Keyが有効かどうかをチェック

    Args:
        api_key: Gemini API Key

    Returns:
        True if valid, False otherwise
    """
    if not api_key:
        return False

    # デフォルト値やプレースホルダーをチェック
    invalid_values = [
        'your_api_key_here',
        'YOUR_API_KEY',
        'api_key',
        'example',
        'placeholder'
    ]

    if api_key.lower() in [v.lower() for v in invalid_values]:
        return False

    # API Keyは通常かなり長い文字列なので、短すぎる場合は無効
    if len(api_key) < 20:
        return False

    return True


def generate_network_graph(articles: List[Dict]) -> str:
    """
    論文のネットワークグラフを生成

    Args:
        articles: 論文リスト

    Returns:
        生成されたHTMLファイルのパス
    """
    # PyVisネットワークを作成
    net = Network(
        height="600px",
        width="100%",
        bgcolor="#ffffff",
        font_color="#000000",
        directed=True
    )

    # ノードとエッジのデータを準備
    article_dict = {a["article_id"]: a for a in articles}

    # 被リンク数の最大値を取得（ノードサイズ正規化用）
    max_link_count = max([len(a.get("mentioned_by", [])) for a in articles]) if articles else 1
    if max_link_count == 0:
        max_link_count = 1

    # 各論文をノードとして追加
    for article in articles:
        article_id = article["article_id"]
        title = article.get("title", "不明なタイトル")
        relevance_score = article.get("relevance_score", 0)
        mentioned_by = article.get("mentioned_by", [])
        link_count = len(mentioned_by)

        # ノードサイズ: 被リンク数に比例（最小10、最大50）
        base_size = 10
        max_size = 50
        if max_link_count > 0:
            node_size = base_size + (link_count / max_link_count) * (max_size - base_size)
        else:
            node_size = base_size

        # ノードの色: relevance_scoreでヒートマップ化
        # 赤(高スコア) → 黄 → 青(低スコア)
        if relevance_score >= 70:
            # 70-100: 赤系
            intensity = int(255 * (100 - relevance_score) / 30)
            color = f"rgb(255, {intensity}, {intensity})"
        elif relevance_score >= 40:
            # 40-69: 黄系
            intensity = int(255 * (relevance_score - 40) / 30)
            color = f"rgb(255, 255, {255 - intensity})"
        else:
            # 0-39: 青系
            intensity = int(255 * (40 - relevance_score) / 40)
            color = f"rgb({255 - intensity}, {255 - intensity}, 255)"

        # PMID/DOIを取得
        pmid = article.get("pmid", "")
        doi = article.get("doi", "")
        display_id = f"PMID:{pmid}" if pmid else f"DOI:{doi}"

        # ホバー時のラベル
        label = f"{display_id}\nScore: {relevance_score}\nLinks: {link_count}"
        hover_title = f"{title}\n{label}"

        # ノードを追加
        net.add_node(
            article_id,
            label=display_id,
            title=hover_title,
            size=node_size,
            color=color,
            font={"size": 12}
        )

    # エッジを追加（親 → 子）
    for article in articles:
        article_id = article["article_id"]
        mentioned_by = article.get("mentioned_by", [])

        # この論文を参照している親論文からエッジを引く
        for parent_id in mentioned_by:
            # 親論文がフィルタ後のリストに存在する場合のみエッジを追加
            if parent_id in article_dict:
                net.add_edge(parent_id, article_id)

    # 物理演算の設定
    net.set_options("""
    {
        "physics": {
            "enabled": true,
            "barnesHut": {
                "gravitationalConstant": -8000,
                "centralGravity": 0.3,
                "springLength": 95,
                "springConstant": 0.04
            },
            "stabilization": {
                "iterations": 150
            }
        },
        "edges": {
            "arrows": {
                "to": {
                    "enabled": true,
                    "scaleFactor": 0.5
                }
            },
            "color": {
                "color": "#848484",
                "highlight": "#000000"
            },
            "smooth": {
                "type": "continuous"
            }
        },
        "interaction": {
            "hover": true,
            "navigationButtons": true,
            "keyboard": true
        }
    }
    """)

    # 一時ファイルとして保存
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html', encoding='utf-8') as f:
        net.save_graph(f.name)
        return f.name


def main():
    st.set_page_config(
        page_title="論文検索自動化ツール",
        page_icon="📚",
        layout="wide"
    )

    st.title("📚 PubMed論文検索自動化ツール")
    st.markdown("""
    このツールは、起点となる論文から関連論文を自動的に探索し、
    Gemini AIを使ってあなたが探している論文を見つけます。

    **プロジェクト機能**: 評価済み論文をキャッシュして、重複評価を防止し、API コストを削減します。
    """)

    # プロジェクトマネージャーを初期化
    pm = ProjectManager()

    # サイドバー: 設定
    with st.sidebar:
        st.header("⚙️ 設定")

        # Gemini API Key
        st.subheader("API設定")

        # API Keyの初期値を取得
        env_api_key = os.getenv("GEMINI_API_KEY", "")

        api_key = st.text_input(
            "Gemini API Key",
            type="password",
            value=env_api_key,
            help="https://makersuite.google.com/app/apikey から取得"
        )

        # API Keyの検証
        if not api_key:
            st.error("⚠️ Gemini API Keyを入力してください")
            st.info("API Keyは [こちら](https://makersuite.google.com/app/apikey) から取得できます")
            st.stop()

        if not is_valid_api_key(api_key):
            st.error("⚠️ 無効なAPI Keyです")
            st.warning(
                "デフォルトまたはプレースホルダーのAPI Keyが設定されています。\n\n"
                "正しいAPI Keyを入力してください。\n\n"
                "API Keyは [こちら](https://makersuite.google.com/app/apikey) から取得できます"
            )
            st.stop()

        # API Keyが環境変数と異なる場合、保存ボタンを表示
        if api_key != env_api_key:
            if st.button("💾 API Keyを.envに保存", help="入力したAPI Keyを.envファイルに保存します"):
                if save_api_key_to_env(api_key):
                    st.success("✅ API Keyを.envファイルに保存しました")
                    st.info("次回起動時から、この API Key が自動的に読み込まれます")
                else:
                    st.error("❌ API Keyの保存に失敗しました")

        # Geminiモデル選択
        gemini_model = st.selectbox(
            "Geminiモデル",
            options=GeminiEvaluator.AVAILABLE_MODELS,
            index=GeminiEvaluator.AVAILABLE_MODELS.index(GeminiEvaluator.DEFAULT_MODEL),
            help="使用するGeminiモデルを選択。flash系は高速・低コスト、pro系は高精度"
        )

        st.divider()

        # Notion API設定（オプション）
        st.subheader("Notion連携（オプション）")

        use_notion = st.checkbox(
            "Notion連携を有効にする",
            value=False,
            help="Notionデータベースと連携して、論文の登録状態をチェック・スコアを更新"
        )

        notion_api_key = None
        notion_database_id = None

        if use_notion:
            notion_api_key = st.text_input(
                "Notion API Key",
                type="password",
                value=os.getenv("NOTION_API_KEY", ""),
                help="https://www.notion.so/my-integrations から取得"
            )

            notion_database_id = st.text_input(
                "Notion Database ID",
                value=os.getenv("NOTION_DATABASE_ID", ""),
                help="データベースURLから取得: https://www.notion.so/{workspace}/{database_id}?v=..."
            )

            if not notion_api_key or not notion_database_id:
                st.warning("Notion API KeyとDatabase IDの両方を入力してください")

        st.divider()

        # 京大リンク設定
        st.subheader("リンク設定")

        use_kyoto_links = st.checkbox(
            "京都大学のリンクを使用",
            value=os.getenv("USE_KYOTO_UNIVERSITY_LINKS", "false").lower() == "true",
            help="京都大学のプロキシを経由してDOIリンクにアクセスします。京大アカウントでログインしている場合、論文PDFに直接アクセスできます。"
        )

        st.divider()

        # プロジェクト選択
        st.subheader("📁 プロジェクト")

        project_mode = st.radio(
            "モード選択",
            ["新規プロジェクト作成", "既存プロジェクトに追加"],
            help="新規作成するか、既存プロジェクトに論文を追加するか選択"
        )

        project = None

        if project_mode == "新規プロジェクト作成":
            project_name = st.text_input(
                "プロジェクト名",
                placeholder="例: 糖尿病治療研究",
                help="プロジェクト名を入力"
            )
        else:
            # 既存プロジェクト一覧
            projects = pm.list_projects()

            if not projects:
                st.info("まだプロジェクトがありません。新規作成してください。")
                st.stop()

            # プロジェクト選択
            project_options = {
                f"{p['name']} ({p['stats']['total_articles']}件)": p['safe_name']
                for p in projects
            }

            selected_project_display = st.selectbox(
                "プロジェクトを選択",
                options=list(project_options.keys()),
                help="既存のプロジェクトから選択"
            )

            selected_project_name = project_options[selected_project_display]

            # プロジェクトを読み込み
            try:
                project = pm.load_project(selected_project_name)
                st.success(f"✅ プロジェクトを読み込みました")

                # 未完了の検索があるかチェック
                if project.has_search_state():
                    saved_state = project.load_search_state()
                    if saved_state:
                        saved_at = saved_state.get('saved_at', '不明')
                        st.warning(
                            f"⚠️ 前回の検索が中断されています（保存日時: {saved_at[:19]}）\n\n"
                            f"新しい検索を開始すると、評価済み論文は自動的にスキップされます。"
                        )

                # プロジェクト情報を表示
                st.info(
                    f"**探している論文:** {project.metadata.get('research_theme', 'N/A')}\n\n"
                    f"**論文数:** {project.metadata['stats']['total_articles']}件\n\n"
                    f"**更新日時:** {project.metadata.get('updated_at', 'N/A')[:10]}"
                )

                # プロジェクト名を設定（新規追加時に使用しない）
                project_name = None

            except Exception as e:
                st.error(f"プロジェクトの読み込みに失敗: {e}")
                st.stop()

        st.divider()

        # 探索設定
        st.subheader("探索設定")

        # セッション状態の初期化
        if 'config_max_depth_slider' not in st.session_state:
            st.session_state.config_max_depth_slider = 2
        if 'config_max_depth_input' not in st.session_state:
            st.session_state.config_max_depth_input = 2
        if 'config_max_articles_slider' not in st.session_state:
            st.session_state.config_max_articles_slider = 100
        if 'config_max_articles_input' not in st.session_state:
            st.session_state.config_max_articles_input = 100
        if 'config_threshold_slider' not in st.session_state:
            st.session_state.config_threshold_slider = 60
        if 'config_threshold_input' not in st.session_state:
            st.session_state.config_threshold_input = 60

        # 探索の深さ
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            st.slider(
                "探索の深さ",
                min_value=1,
                max_value=5,
                help="何階層まで関連論文を辿るか",
                key="config_max_depth_slider",
                on_change=lambda: setattr(st.session_state, 'config_max_depth_input', st.session_state.config_max_depth_slider)
            )
        with col_input:
            st.number_input(
                "深さ",
                min_value=1,
                max_value=5,
                step=1,
                label_visibility="collapsed",
                key="config_max_depth_input",
                on_change=lambda: setattr(st.session_state, 'config_max_depth_slider', st.session_state.config_max_depth_input)
            )

        max_depth = st.session_state.config_max_depth_slider

        # 最大論文数
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            st.slider(
                "最大論文数",
                min_value=10,
                max_value=1000,
                step=5,
                help="収集する論文の最大数",
                key="config_max_articles_slider",
                on_change=lambda: setattr(st.session_state, 'config_max_articles_input', st.session_state.config_max_articles_slider)
            )
        with col_input:
            st.number_input(
                "論文数",
                min_value=10,
                max_value=1000,
                step=5,
                label_visibility="collapsed",
                key="config_max_articles_input",
                on_change=lambda: setattr(st.session_state, 'config_max_articles_slider', st.session_state.config_max_articles_input)
            )

        max_articles = st.session_state.config_max_articles_slider

        # 関連性スコア閾値
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            st.slider(
                "関連性スコア閾値",
                min_value=0,
                max_value=100,
                step=5,
                help="この値以上のスコアの論文のみ次階層を探索",
                key="config_threshold_slider",
                on_change=lambda: setattr(st.session_state, 'config_threshold_input', st.session_state.config_threshold_slider)
            )
        with col_input:
            st.number_input(
                "閾値",
                min_value=0,
                max_value=100,
                step=5,
                label_visibility="collapsed",
                key="config_threshold_input",
                on_change=lambda: setattr(st.session_state, 'config_threshold_slider', st.session_state.config_threshold_input)
            )

        relevance_threshold = st.session_state.config_threshold_slider

        st.divider()

        # 関連論文取得設定
        st.subheader("関連論文取得設定")

        # Similar articles設定
        st.markdown("**Similar articles（類似論文）**")
        col1, col2 = st.columns([3, 2])
        with col1:
            include_similar = st.checkbox("Similar articlesを探索", value=True, key="include_similar")
        with col2:
            max_similar = st.number_input(
                "最大数",
                min_value=5,
                max_value=100,
                value=20,
                step=5,
                disabled=not st.session_state.get("include_similar", True),
                key="max_similar",
                help="1論文あたりの最大取得数"
            )

        # Cited by設定
        st.markdown("**Cited by（この論文を引用している論文）**")
        col1, col2 = st.columns([3, 2])
        with col1:
            include_cited_by = st.checkbox("Cited byを探索", value=True, key="include_cited_by")
        with col2:
            max_cited_by = st.number_input(
                "最大数",
                min_value=5,
                max_value=100,
                value=20,
                step=5,
                disabled=not st.session_state.get("include_cited_by", True),
                key="max_cited_by",
                help="1論文あたりの最大取得数"
            )

        # References設定
        st.markdown("**References（この論文が引用している文献）**")
        col1, col2 = st.columns([3, 2])
        with col1:
            include_references = st.checkbox("Referencesを探索", value=False, key="include_references")
        with col2:
            max_references = st.number_input(
                "最大数",
                min_value=5,
                max_value=100,
                value=20,
                step=5,
                disabled=not st.session_state.get("include_references", False),
                key="max_references",
                help="1論文あたりの最大取得数"
            )

        st.divider()

        # フィルタ設定
        st.subheader("フィルタ設定")

        use_year_filter = st.checkbox("年代フィルタを使用", value=False)
        year_from = None
        if use_year_filter:
            year_from = st.number_input(
                "この年以降の論文のみ",
                min_value=1900,
                max_value=datetime.now().year,
                value=2020,
                step=1
            )

        pubmed_only = st.checkbox(
            "PubMed収録論文のみを対象",
            value=False,
            help="有効にすると、PMIDがない論文（DOIのみの論文）を除外します"
        )

    # メインエリア
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📝 入力")

        start_pmid = st.text_input(
            "起点論文のPMIDまたはURL",
            placeholder="例: 12345678 または https://pubmed.ncbi.nlm.nih.gov/12345678/",
            help="探索を開始する論文のPubMed IDまたはURL"
        )

    with col2:
        st.subheader("🎯 探したい論文の内容")

        # 既存プロジェクトの場合はデフォルト値を設定
        default_theme = ""
        if project:
            default_theme = project.metadata.get('research_theme', '')

        research_theme = st.text_area(
            "どのような論文を探したいか、具体的に記載してください",
            value=default_theme,
            placeholder="例: 2型糖尿病患者におけるインスリン抵抗性と心血管疾患リスクの関連について研究している論文を探しています。特にメトホルミンやGLP-1受容体作動薬などの治療薬の効果を含めた研究に興味があります。",
            height=150,
            help="この内容に合致する論文をAIが評価して探します"
        )

    # 既存プロジェクトの論文一覧を表示
    if project and project.metadata['stats']['total_articles'] > 0:
        with st.expander(f"📚 プロジェクト内の論文一覧 ({project.metadata['stats']['total_articles']}件)", expanded=False):
            display_project_articles(
                project=project,
                api_key=api_key,
                gemini_model=gemini_model,
                research_theme=research_theme,
                max_depth=max_depth,
                max_articles=max_articles,
                relevance_threshold=relevance_threshold,
                year_from=year_from,
                include_similar=include_similar,
                max_similar=max_similar,
                include_cited_by=include_cited_by,
                max_cited_by=max_cited_by,
                include_references=include_references,
                max_references=max_references,
                pubmed_only=pubmed_only,
                notion_api_key=notion_api_key if use_notion else None,
                notion_database_id=notion_database_id if use_notion else None,
                use_kyoto_links=use_kyoto_links
            )

    # 実行ボタン
    st.divider()

    if st.button("🚀 論文検索を開始", type="primary", use_container_width=True):
        if not start_pmid:
            st.error("起点論文のPMIDまたはURLを入力してください")
            return

        if not research_theme:
            st.error("探したい論文の内容を入力してください")
            return

        # プロジェクトの準備
        if project_mode == "新規プロジェクト作成":
            if not project_name:
                st.error("プロジェクト名を入力してください")
                return

            # 新規プロジェクトを作成
            try:
                settings = {
                    "max_depth": max_depth,
                    "max_articles": max_articles,
                    "relevance_threshold": relevance_threshold,
                    "year_from": year_from
                }
                project = pm.create_project(project_name, research_theme, settings)
                st.success(f"✅ プロジェクト '{project_name}' を作成しました")
            except Exception as e:
                st.error(f"プロジェクトの作成に失敗: {e}")
                return

        # デバッグ情報を表示
        with st.expander("🔍 探索設定の確認", expanded=False):
            st.write("**関連論文取得設定:**")
            st.write(f"- Similar articles: {include_similar} (最大: {max_similar}件)")
            st.write(f"- Cited by: {include_cited_by} (最大: {max_cited_by}件)")
            st.write(f"- References: {include_references} (最大: {max_references}件)")
            st.write(f"- 年代フィルタ: {year_from if year_from else 'なし'}")

        # 探索実行
        run_search(
            api_key=api_key,
            gemini_model=gemini_model,
            start_pmid=start_pmid,
            research_theme=research_theme,
            max_depth=max_depth,
            max_articles=max_articles,
            relevance_threshold=relevance_threshold,
            year_from=year_from,
            include_similar=include_similar,
            max_similar=max_similar,
            include_cited_by=include_cited_by,
            max_cited_by=max_cited_by,
            include_references=include_references,
            max_references=max_references,
            pubmed_only=pubmed_only,
            project=project,
            notion_api_key=notion_api_key if use_notion else None,
            notion_database_id=notion_database_id if use_notion else None
        )

    # 検索結果がsession_stateにある場合は表示
    elif 'search_result' in st.session_state and 'current_project' in st.session_state:
        display_results(st.session_state['search_result'], st.session_state['current_project'], use_kyoto_links)


def display_project_articles(
    project,
    api_key: str,
    gemini_model: str,
    research_theme: str,
    max_depth: int,
    max_articles: int,
    relevance_threshold: int,
    year_from: Optional[int],
    include_similar: bool,
    max_similar: int,
    include_cited_by: bool,
    max_cited_by: int,
    include_references: bool,
    max_references: int,
    pubmed_only: bool,
    notion_api_key: Optional[str] = None,
    notion_database_id: Optional[str] = None,
    use_kyoto_links: bool = False
):
    """プロジェクト内の論文を表示"""
    articles = project.get_all_articles()

    # 関連性スコアでソート
    articles.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    # 統計情報
    col1, col2 = st.columns([1, 2])

    with col1:
        st.metric("総論文数", len(articles))

        # Notion登録済み数（チェック済みの場合のみ）
        if any('in_notion' in a for a in articles):
            notion_count = len([a for a in articles if a.get("in_notion", False)])
            st.metric("Notion登録済み", notion_count)

    with col2:
        # スコア分布を表示
        st.markdown("**📊 スコア分布**")

        # スコア範囲ごとに集計
        score_ranges = {
            "80-100点\n(高)": 0,
            "60-79点\n(中)": 0,
            "40-59点\n(低)": 0,
            "0-39点\n(非関連)": 0
        }

        for article in articles:
            score = article.get("relevance_score", 0)
            if score >= 80:
                score_ranges["80-100点\n(高)"] += 1
            elif score >= 60:
                score_ranges["60-79点\n(中)"] += 1
            elif score >= 40:
                score_ranges["40-59点\n(低)"] += 1
            else:
                score_ranges["0-39点\n(非関連)"] += 1

        # 棒グラフで表示
        import pandas as pd
        df = pd.DataFrame({
            "件数": list(score_ranges.values())
        }, index=list(score_ranges.keys()))

        st.bar_chart(df, horizontal=True, height=200)

    st.divider()

    # Notionチェック機能
    st.subheader("🔗 Notion連携")

    col1, col2 = st.columns([2, 1])

    with col1:
        notion_api_key_check = st.text_input(
            "Notion API Key",
            type="password",
            value=os.getenv("NOTION_API_KEY", ""),
            help="https://www.notion.so/my-integrations から取得",
            key="project_notion_api_key"
        )

        notion_database_id_check = st.text_input(
            "Notion Database ID",
            value=os.getenv("NOTION_DATABASE_ID", ""),
            help="データベースURLから取得",
            key="project_notion_database_id"
        )

    with col2:
        st.write("")  # スペーサー
        st.write("")  # スペーサー

        if st.button(
            "🔍 Notionデータベースをチェック",
            type="primary",
            use_container_width=True,
            disabled=not (notion_api_key_check and notion_database_id_check),
            help="プロジェクト内の全論文がNotionに登録されているかチェックし、スコアを更新"
        ):
            if not notion_api_key_check or not notion_database_id_check:
                st.error("Notion API KeyとDatabase IDを両方入力してください")
            else:
                # Notionチェックを実行
                try:
                    # NotionAPIを初期化
                    from notion_api import NotionAPI
                    notion = NotionAPI(notion_api_key_check, notion_database_id_check)

                    # プログレスバーを表示
                    progress_placeholder = st.empty()
                    status_placeholder = st.empty()

                    def notion_progress(current, total, pmid):
                        progress_placeholder.progress(current / total)
                        status_placeholder.info(f"Notionチェック中 {current}/{total} (PMID: {pmid})")

                    status_placeholder.info("Notionデータベースをチェック中...")

                    # 全論文をチェック
                    updated_articles = notion.batch_check_articles(
                        articles,
                        update_score=True,
                        callback=notion_progress,
                        project_name=project.metadata.get('name'),
                        research_theme=project.metadata.get('research_theme')
                    )

                    # プロジェクトを更新
                    for article in updated_articles:
                        project.add_article(article)

                    project.save()

                    # 統計情報
                    notion_registered = len([a for a in updated_articles if a.get("in_notion", False)])
                    score_updated = len([a for a in updated_articles if a.get("notion_score_updated", False)])

                    progress_placeholder.empty()
                    status_placeholder.success(
                        f"✅ Notionチェック完了！\n\n"
                        f"- 登録済み: {notion_registered}件\n"
                        f"- スコア更新: {score_updated}件"
                    )

                    # 画面を再読み込み
                    st.rerun()

                except ImportError:
                    st.error("notion-clientがインストールされていません。`pip install notion-client`を実行してください")
                except Exception as e:
                    st.error(f"Notionチェック中にエラーが発生しました: {e}")
                    import traceback
                    st.code(traceback.format_exc())

    st.divider()

    # フィルタ
    st.subheader("🔍 論文フィルタ")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        # 検索セッションフィルタ
        sessions = project.get_search_sessions()
        session_options = ["すべて"]

        if sessions:
            # セッション選択肢を作成（日時と件数を表示）
            for session in sessions:
                timestamp = session.get("timestamp", "")
                count = session.get("article_count", 0)
                # タイムスタンプを読みやすい形式に変換
                try:
                    dt = datetime.fromisoformat(timestamp)
                    display_time = dt.strftime("%Y-%m-%d %H:%M")
                    session_label = f"{display_time} ({count}件)"
                    session_options.append(session_label)
                except:
                    session_options.append(f"{timestamp} ({count}件)")

        selected_session_display = st.selectbox(
            "検索セッション",
            options=session_options,
            help="特定の検索で追加された論文のみ表示"
        )

        # 選択されたセッションIDを取得
        selected_session_id = None
        if selected_session_display != "すべて" and sessions:
            # session_optionsのインデックスから対応するセッションIDを取得
            session_index = session_options.index(selected_session_display) - 1  # "すべて"の分を引く
            if 0 <= session_index < len(sessions):
                selected_session_id = sessions[session_index].get("session_id")

    with col2:
        show_not_in_notion = st.checkbox(
            "Notion未登録のみ表示",
            value=False,
            key="project_filter_not_in_notion",
            help="Notionデータベースに未登録の論文のみ表示"
        )
        show_pubmed_only = st.checkbox(
            "PubMed掲載論文のみ",
            value=False,
            key="project_filter_pubmed_only",
            help="PMIDがある論文のみ表示（DOIのみの論文を除外）"
        )

    with col3:
        # セッション状態の初期化
        if 'filter_project_slider' not in st.session_state:
            st.session_state.filter_project_slider = 0
        if 'filter_project_input' not in st.session_state:
            st.session_state.filter_project_input = 0

        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            st.slider(
                "最小スコア",
                min_value=0,
                max_value=100,
                step=5,
                key="filter_project_slider",
                on_change=lambda: setattr(st.session_state, 'filter_project_input', st.session_state.filter_project_slider)
            )
        with col_input:
            st.number_input(
                "スコア",
                min_value=0,
                max_value=100,
                step=5,
                label_visibility="collapsed",
                key="filter_project_input",
                on_change=lambda: setattr(st.session_state, 'filter_project_slider', st.session_state.filter_project_input)
            )

        min_score_filter = st.session_state.filter_project_slider

    with col4:
        # 最小被リンク数フィルタ
        min_link_count = st.number_input(
            "最小被リンク数",
            min_value=0,
            max_value=100,
            value=0,
            step=1,
            key="project_min_link_count",
            help="引用・類似を問わず、他の論文から検出された回数の最小値"
        )

    # 論文リストをフィルタ
    filtered_articles = articles

    # セッションフィルタ（配列対応）
    if selected_session_id:
        filtered_articles = [
            a for a in filtered_articles
            if selected_session_id in a.get("search_session_ids", [])
        ]

    if show_not_in_notion:
        filtered_articles = [a for a in filtered_articles if not a.get("in_notion", False)]

    if show_pubmed_only:
        filtered_articles = [a for a in filtered_articles if a.get("pmid") is not None]

    if min_link_count > 0:
        filtered_articles = [a for a in filtered_articles if len(a.get("mentioned_by", [])) >= min_link_count]

    filtered_articles = [
        a for a in filtered_articles
        if a.get("relevance_score", 0) >= min_score_filter
    ]

    # ページネーション設定
    ITEMS_PER_PAGE = 100
    total_articles = len(filtered_articles)
    total_pages = (total_articles + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE  # 切り上げ

    # ページ番号をセッションステートで管理
    if 'project_page' not in st.session_state:
        st.session_state.project_page = 1

    # ページ番号が範囲外の場合は修正
    if st.session_state.project_page > total_pages and total_pages > 0:
        st.session_state.project_page = total_pages
    elif st.session_state.project_page < 1:
        st.session_state.project_page = 1

    st.info(f"表示件数: {len(filtered_articles)} / {len(articles)}")

    # ネットワークグラフ表示
    if filtered_articles:
        with st.expander("🕸️ ネットワークグラフを表示", expanded=False):
            st.info("ノードの大きさ = 被リンク数、ノードの色 = 関連性スコア（赤=高、青=低）")

            try:
                # グラフを生成
                graph_html_path = generate_network_graph(filtered_articles)

                # HTMLファイルを読み込んで表示
                with open(graph_html_path, 'r', encoding='utf-8') as f:
                    graph_html = f.read()

                components.html(graph_html, height=620, scrolling=True)

                # 一時ファイルを削除
                try:
                    os.unlink(graph_html_path)
                except:
                    pass

            except Exception as e:
                st.error(f"ネットワークグラフの生成に失敗しました: {e}")
                import traceback
                st.code(traceback.format_exc())

    st.divider()

    # フィルタ後のNotion連携
    if len(filtered_articles) < len(articles):
        st.subheader("🔗 フィルタ後の論文をNotionチェック")

        col1, col2 = st.columns([2, 1])

        with col1:
            st.info(f"フィルタ後の {len(filtered_articles)} 件の論文のみをチェックします")

        with col2:
            notion_api_key_filtered = os.getenv("NOTION_API_KEY", "")
            notion_database_id_filtered = os.getenv("NOTION_DATABASE_ID", "")

            if st.button(
                "🔍 フィルタ後をチェック",
                type="secondary",
                use_container_width=True,
                disabled=not (notion_api_key_filtered and notion_database_id_filtered),
                help="フィルタされた論文のみNotionデータベースをチェックし、スコアを更新",
                key="notion_check_filtered"
            ):
                if not notion_api_key_filtered or not notion_database_id_filtered:
                    st.error("Notion API KeyとDatabase IDを設定してください（上部のNotion連携セクション）")
                else:
                    # Notionチェックを実行
                    try:
                        # NotionAPIを初期化
                        from notion_api import NotionAPI
                        notion = NotionAPI(notion_api_key_filtered, notion_database_id_filtered)

                        # プログレスバーを表示
                        progress_placeholder = st.empty()
                        status_placeholder = st.empty()

                        def notion_progress(current, total, pmid):
                            progress_placeholder.progress(current / total)
                            status_placeholder.info(f"Notionチェック中 {current}/{total} (PMID: {pmid})")

                        status_placeholder.info("フィルタ後の論文をNotionデータベースでチェック中...")

                        # フィルタ後の論文のみチェック
                        updated_articles = notion.batch_check_articles(
                            filtered_articles,
                            update_score=True,
                            callback=notion_progress,
                            project_name=project.metadata.get('name'),
                            research_theme=project.metadata.get('research_theme')
                        )

                        # プロジェクトを更新
                        for article in updated_articles:
                            project.add_article(article)

                        project.save()

                        # 統計情報
                        notion_registered = len([a for a in updated_articles if a.get("in_notion", False)])
                        score_updated = len([a for a in updated_articles if a.get("notion_score_updated", False)])

                        progress_placeholder.empty()
                        status_placeholder.success(
                            f"✅ Notionチェック完了！\n\n"
                            f"- チェック対象: {len(filtered_articles)}件\n"
                            f"- 登録済み: {notion_registered}件\n"
                            f"- スコア更新: {score_updated}件"
                        )

                        # 画面を再読み込み
                        st.rerun()

                    except ImportError:
                        st.error("notion-clientがインストールされていません。`pip install notion-client`を実行してください")
                    except Exception as e:
                        st.error(f"Notionチェック中にエラーが発生しました: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        st.divider()

    st.divider()

    # データエクスポート
    st.subheader("💾 データエクスポート")

    col1, col2 = st.columns(2)

    with col1:
        # フィルタ後のデータ
        filtered_result = {
            "articles": filtered_articles,
            "metadata": project.metadata
        }
        filtered_json_str = json.dumps(filtered_result, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 フィルタ後データをダウンロード",
            data=filtered_json_str,
            file_name=f"project_{project.metadata['safe_name']}_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            key="project_download_filtered"
        )

    with col2:
        # プロジェクト全体をエクスポート
        project_json = project.export_to_json()
        st.download_button(
            label="📥 プロジェクト全体をダウンロード",
            data=project_json,
            file_name=f"project_{project.metadata['safe_name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            key="project_download_all"
        )

    st.divider()

    # 論文リスト（フィルタ後のみ表示）
    st.subheader("📄 論文リスト")

    # ページネーションコントロール
    if total_pages > 1:
        col_page1, col_page2, col_page3 = st.columns([1, 2, 1])

        with col_page1:
            if st.button("◀ 前へ", key="project_prev_page", disabled=(st.session_state.project_page == 1)):
                st.session_state.project_page -= 1
                st.rerun()

        with col_page2:
            # ページ番号選択
            page_options = list(range(1, total_pages + 1))
            selected_page = st.selectbox(
                f"ページ ({total_pages}ページ中)",
                options=page_options,
                index=st.session_state.project_page - 1,
                key="project_page_select"
            )
            if selected_page != st.session_state.project_page:
                st.session_state.project_page = selected_page
                st.rerun()

        with col_page3:
            if st.button("次へ ▶", key="project_next_page", disabled=(st.session_state.project_page == total_pages)):
                st.session_state.project_page += 1
                st.rerun()

    # 現在のページの論文を取得
    start_idx = (st.session_state.project_page - 1) * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_articles)
    current_page_articles = filtered_articles[start_idx:end_idx]

    # ページ情報を表示
    if total_pages > 1:
        st.info(f"📄 {start_idx + 1}〜{end_idx}件目を表示（全{total_articles}件中）")

    for i, article in enumerate(current_page_articles, start_idx + 1):
        with st.expander(
            f"[{i}] {article.get('title', 'No Title')} "
            f"(スコア: {article.get('relevance_score', 0)})",
            expanded=(i <= 5)  # 最初の5件は展開表示
        ):
            col1, col2 = st.columns([2, 1])

            with col1:
                pmid = article.get('pmid')
                doi = article.get('doi')
                article_id = article.get('article_id', f"pmid:{pmid}" if pmid else f"doi:{doi}" if doi else f"unknown_{i}")

                # PMID表示（ある場合のみ）
                if pmid:
                    st.markdown(f"**PMID:** [{pmid}]({article.get('url', '#')})")
                elif doi:
                    # PMIDがなくDOIのみの場合
                    st.markdown(f"**識別子:** DOIのみ")

                # DOI情報とリンク
                if doi:
                    # DOIリンク（京大 or 通常）
                    if use_kyoto_links:
                        doi_url = f"https://doi-org.kyoto-u.idm.oclc.org/{doi}"
                        st.markdown(f"**DOI:** [🔗 {doi}]({doi_url}) (京大プロキシ)")
                    else:
                        doi_url = f"https://doi.org/{doi}"
                        st.markdown(f"**DOI:** [🔗 {doi}]({doi_url})")

                    # 京都大学図書館Article Linkerへのリンク（DOIベース）
                    ku_linker_url = f"https://tt2mx4dc7s.search.serialssolutions.com/?sid=Entrez:PubMed&id=doi:{doi}"
                    st.markdown(f"**📚 京大図書館:** [Article Linker]({ku_linker_url})")
                elif pmid != 'N/A':
                    # DOIがない場合はPMIDベースのArticle Linker
                    ku_linker_url = f"https://tt2mx4dc7s.search.serialssolutions.com/?sid=Entrez:PubMed&id=pmid:{pmid}"
                    st.markdown(f"**📚 京大図書館:** [Article Linker]({ku_linker_url})")

                st.markdown(f"**著者:** {article.get('authors', 'N/A')}")
                st.markdown(f"**ジャーナル:** {article.get('journal', 'N/A')}")
                st.markdown(f"**出版年:** {article.get('pub_year', 'N/A')}")

                # 評価日時を表示
                evaluated_at = article.get('evaluated_at')
                if evaluated_at:
                    try:
                        dt = datetime.fromisoformat(evaluated_at)
                        display_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                        st.markdown(f"**評価日時:** {display_time}")
                    except:
                        st.markdown(f"**評価日時:** {evaluated_at}")

            with col2:
                score = article.get('relevance_score', 0)

                # スコアバッジ
                if score >= 80:
                    color = "green"
                elif score >= 60:
                    color = "blue"
                elif score >= 40:
                    color = "orange"
                else:
                    color = "red"

                st.markdown(f"**関連性スコア:** :{color}[{score}]")

                # Notion登録状態を表示（Notion連携を使った場合のみ）
                if 'in_notion' in article:
                    if article.get('in_notion'):
                        st.markdown(f"**Notion:** 📝 登録済み")
                        # Notionページへのリンク
                        notion_page_id = article.get('notion_page_id')
                        if notion_page_id:
                            # ページIDのハイフンを削除してURLを構築
                            clean_page_id = notion_page_id.replace('-', '')
                            notion_url = f"https://www.notion.so/{clean_page_id}"
                            st.markdown(f"　　　　 [📄 Notionページを開く]({notion_url})")
                        if article.get('notion_score_updated'):
                            st.markdown("　　　　 ✅ スコア更新済み")
                    else:
                        st.markdown(f"**Notion:** ❌ 未登録")

                # ソース情報を表示
                source_pmid = article.get('source_pmid')
                source_type = article.get('source_type', '')
                if source_pmid:
                    source_type_jp = "類似論文" if source_type == "similar" else "引用論文"
                    st.markdown(f"**発見元:** PMID {source_pmid} の{source_type_jp}")
                elif source_type == "起点論文":
                    st.markdown(f"**発見元:** {source_type}")

            # アブストラクト
            if article.get('abstract'):
                with st.container():
                    st.markdown("**アブストラクト:**")
                    st.text(article['abstract'])

            # 日本語要約
            if article.get('abstract_summary_ja'):
                st.markdown("**📝 日本語要約:**")
                st.success(article['abstract_summary_ja'])

            # 評価理由
            if article.get('relevance_reasoning'):
                st.markdown("**AI評価理由:**")
                st.info(article['relevance_reasoning'])

            # コメント・メモ機能
            st.markdown("**📝 メモ・コメント:**")
            existing_comment = article.get('comment', '')

            # コメント入力エリア
            comment = st.text_area(
                label="メモを入力",
                value=existing_comment,
                key=f"comment_{article_id}_{i}",
                height=100,
                label_visibility="collapsed",
                placeholder="この論文に関するメモやコメントを入力してください..."
            )

            # コメント保存ボタン
            if st.button(
                "💾 メモを保存",
                key=f"save_comment_{article_id}_{i}",
                type="secondary",
                help="メモをプロジェクトに保存します"
            ):
                # 論文のコメントを更新
                article['comment'] = comment
                project.articles[article_id] = article
                project.save()
                st.success("メモを保存しました")
                st.rerun()

            st.divider()

            # ボタン群
            col_btn1, col_btn2 = st.columns(2)

            with col_btn1:
                # DOIのみの論文は検索できない（PMIDが必要）
                can_search = pmid is not None
                button_help = "この論文を起点として関連論文を探索します" if can_search else "DOIのみの論文は検索の起点にできません（PMIDが必要）"

                if st.button(
                    "🔍 この論文を起点に検索",
                    key=f"search_from_{article_id}_{i}",
                    type="primary",
                    use_container_width=True,
                    disabled=not can_search,
                    help=button_help
                ):
                    # この論文を起点に検索を開始
                    st.info(f"PMID {pmid} を起点に検索を開始します...")
                    run_search(
                        api_key=api_key,
                        gemini_model=gemini_model,
                        start_pmid=pmid,
                        research_theme=research_theme,
                        max_depth=max_depth,
                        max_articles=max_articles,
                        relevance_threshold=relevance_threshold,
                        year_from=year_from,
                        include_similar=include_similar,
                        max_similar=max_similar,
                        include_cited_by=include_cited_by,
                        max_cited_by=max_cited_by,
                        include_references=include_references,
                        max_references=max_references,
                        pubmed_only=pubmed_only,
                        project=project,
                        notion_api_key=notion_api_key,
                        notion_database_id=notion_database_id
                    )

            with col_btn2:
                if st.button(
                    "🗑️ この論文を削除",
                    key=f"delete_{article_id}_{i}",
                    type="secondary",
                    use_container_width=True,
                    help="プロジェクトから削除します。次回検索時に再度発見されれば再評価されます。"
                ):
                    # article_idで削除（互換性のためpmidもサポート）
                    deleted = False
                    if article_id in project.articles:
                        del project.articles[article_id]
                        deleted = True
                    elif pmid and pmid in project.articles:
                        del project.articles[pmid]
                        deleted = True

                    if deleted:
                        project._update_stats()
                        project.save()
                        display_name = f"PMID {pmid}" if pmid else f"DOI論文"
                        st.success(f"論文 {display_name} を削除しました")
                        st.rerun()
                    else:
                        st.error("削除に失敗しました")


def run_search(
    api_key: str,
    gemini_model: str,
    start_pmid: str,
    research_theme: str,
    max_depth: int,
    max_articles: int,
    relevance_threshold: int,
    year_from: int,
    include_similar: bool,
    max_similar: int,
    include_cited_by: bool,
    max_cited_by: int,
    include_references: bool,
    max_references: int,
    pubmed_only: bool,
    project,
    notion_api_key: Optional[str] = None,
    notion_database_id: Optional[str] = None
):
    """論文検索を実行"""

    # 停止フラグを初期化
    if 'stop_search' not in st.session_state:
        st.session_state['stop_search'] = False

    # 進捗表示エリア
    progress_placeholder = st.empty()
    status_placeholder = st.empty()
    stop_button_placeholder = st.empty()

    def progress_callback(message: str):
        """進捗を表示"""
        status_placeholder.info(f"📊 {message}")

    def should_stop():
        """停止フラグをチェック"""
        return st.session_state.get('stop_search', False)

    try:
        # OpenAlexメールアドレスを環境変数から取得
        openalex_email = os.environ.get("OPENALEX_EMAIL")

        # ArticleFinderを初期化
        finder = ArticleFinder(
            gemini_api_key=api_key,
            gemini_model=gemini_model,
            notion_api_key=notion_api_key,
            notion_database_id=notion_database_id,
            openalex_email=openalex_email
        )

        # 停止ボタンを表示
        if stop_button_placeholder.button("⏸️ 評価を停止", type="secondary", use_container_width=True):
            st.session_state['stop_search'] = True
            status_placeholder.warning("⏸️ 停止リクエストを受け付けました...")

        with st.spinner("論文を探索中..."):
            # 探索実行
            result = finder.find_articles(
                start_pmid_or_url=start_pmid,
                research_theme=research_theme,
                max_depth=max_depth,
                max_articles=max_articles,
                relevance_threshold=relevance_threshold,
                year_from=year_from,
                include_similar=include_similar,
                max_similar=max_similar,
                include_cited_by=include_cited_by,
                max_cited_by=max_cited_by,
                include_references=include_references,
                max_references=max_references,
                pubmed_only=pubmed_only,
                progress_callback=progress_callback,
                project=project,
                should_stop_callback=should_stop
            )

        # 停止ボタンを非表示
        stop_button_placeholder.empty()

        # 完了メッセージ
        interrupted = result.get('interrupted', False)
        if interrupted or st.session_state.get('stop_search', False):
            status_placeholder.warning(
                "⏸️ 探索を途中で停止しました\n\n"
                "検索状態が保存されました。次回同じプロジェクトで検索すると、評価済み論文は自動的にスキップされます。"
            )
            st.session_state['stop_search'] = False
        else:
            status_placeholder.success("✅ 探索が完了しました！")

        # セッションに保存（ダウンロード用とフィルタ変更時の再表示用）
        st.session_state['search_result'] = result
        st.session_state['current_project'] = project

        # 画面を再読み込みして結果を表示（重複キーエラーを防ぐ）
        st.rerun()

    except Exception as e:
        st.error(f"エラーが発生しました: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
    finally:
        # 停止フラグをリセット
        st.session_state['stop_search'] = False


def display_results(result: dict, project=None, use_kyoto_links: bool = False):
    """検索結果を表示

    Args:
        result: 検索結果の辞書
        project: プロジェクト（オプション）
        use_kyoto_links: 京大リンクを使用するか
    """

    articles = result["articles"]
    stats = result["stats"]

    st.divider()
    st.header("📊 検索結果")

    # 統計情報
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("発見論文数", stats["total_found"])

    with col2:
        st.metric("新規評価数", stats["total_evaluated"])

    with col3:
        st.metric("キャッシュ数", stats["total_skipped"], help="プロジェクトのキャッシュから取得した論文数")

    with col4:
        st.metric("関連論文数", stats["total_relevant"])

    with col5:
        st.metric("到達階層", stats["depth_reached"])

    # コスト削減の表示
    if stats["total_skipped"] > 0:
        st.success(
            f"💰 キャッシュ機能により、{stats['total_skipped']}件の重複評価を防止しました！"
        )

    st.divider()

    # フィルタ
    st.subheader("🔍 結果フィルタ")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        show_only_relevant = st.checkbox(
            "関連論文のみ表示",
            value=False,
            key="results_filter_relevant"
        )

    with col2:
        show_only_newly_evaluated = st.checkbox(
            "新規評価のみ表示",
            value=False,
            key="results_filter_newly_evaluated",
            help="このセッションで新規に評価された論文のみ表示（キャッシュを除外）"
        )

    with col3:
        show_not_in_notion = st.checkbox(
            "Notion未登録のみ表示",
            value=False,
            key="results_filter_not_in_notion",
            help="Notionデータベースに未登録の論文のみ表示"
        )
        show_pubmed_only_results = st.checkbox(
            "PubMed掲載論文のみ",
            value=False,
            key="results_filter_pubmed_only",
            help="PMIDがある論文のみ表示（DOIのみの論文を除外）"
        )

    with col4:
        # セッション状態の初期化
        if 'filter_results_slider' not in st.session_state:
            st.session_state.filter_results_slider = 0
        if 'filter_results_input' not in st.session_state:
            st.session_state.filter_results_input = 0

        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            st.slider(
                "最小スコア",
                min_value=0,
                max_value=100,
                step=5,
                key="filter_results_slider",
                on_change=lambda: setattr(st.session_state, 'filter_results_input', st.session_state.filter_results_slider)
            )
        with col_input:
            st.number_input(
                "スコア",
                min_value=0,
                max_value=100,
                step=5,
                label_visibility="collapsed",
                key="filter_results_input",
                on_change=lambda: setattr(st.session_state, 'filter_results_slider', st.session_state.filter_results_input)
            )

        min_score_filter = st.session_state.filter_results_slider

    with col5:
        # 最小被リンク数フィルタ
        min_link_count_results = st.number_input(
            "最小被リンク数",
            min_value=0,
            max_value=100,
            value=0,
            step=1,
            key="results_min_link_count",
            help="引用・類似を問わず、他の論文から検出された回数の最小値"
        )

    # 論文リストをフィルタ
    filtered_articles = articles

    if show_only_relevant:
        filtered_articles = [a for a in filtered_articles if a.get("is_relevant", False)]

    if show_only_newly_evaluated:
        filtered_articles = [a for a in filtered_articles if a.get("is_newly_evaluated", False)]

    if show_not_in_notion:
        filtered_articles = [a for a in filtered_articles if not a.get("in_notion", False)]

    if show_pubmed_only_results:
        filtered_articles = [a for a in filtered_articles if a.get("pmid") is not None]

    if min_link_count_results > 0:
        filtered_articles = [a for a in filtered_articles if len(a.get("mentioned_by", [])) >= min_link_count_results]

    filtered_articles = [
        a for a in filtered_articles
        if a.get("relevance_score", 0) >= min_score_filter
    ]

    # ページネーション設定
    ITEMS_PER_PAGE_RESULTS = 100
    total_articles_results = len(filtered_articles)
    total_pages_results = (total_articles_results + ITEMS_PER_PAGE_RESULTS - 1) // ITEMS_PER_PAGE_RESULTS

    # ページ番号をセッションステートで管理
    if 'results_page' not in st.session_state:
        st.session_state.results_page = 1

    # ページ番号が範囲外の場合は修正
    if st.session_state.results_page > total_pages_results and total_pages_results > 0:
        st.session_state.results_page = total_pages_results
    elif st.session_state.results_page < 1:
        st.session_state.results_page = 1

    st.info(f"表示件数: {len(filtered_articles)} / {len(articles)}")

    # ネットワークグラフ表示
    if filtered_articles:
        with st.expander("🕸️ ネットワークグラフを表示", expanded=False):
            st.info("ノードの大きさ = 被リンク数、ノードの色 = 関連性スコア（赤=高、青=低）")

            try:
                # グラフを生成
                graph_html_path = generate_network_graph(filtered_articles)

                # HTMLファイルを読み込んで表示
                with open(graph_html_path, 'r', encoding='utf-8') as f:
                    graph_html = f.read()

                components.html(graph_html, height=620, scrolling=True)

                # 一時ファイルを削除
                try:
                    os.unlink(graph_html_path)
                except:
                    pass

            except Exception as e:
                st.error(f"ネットワークグラフの生成に失敗しました: {e}")
                import traceback
                st.code(traceback.format_exc())

    # 論文リストを表示
    st.subheader("📄 論文リスト")

    # ページネーションコントロール
    if total_pages_results > 1:
        col_page1, col_page2, col_page3 = st.columns([1, 2, 1])

        with col_page1:
            if st.button("◀ 前へ", key="results_prev_page", disabled=(st.session_state.results_page == 1)):
                st.session_state.results_page -= 1
                st.rerun()

        with col_page2:
            # ページ番号選択
            page_options_results = list(range(1, total_pages_results + 1))
            selected_page_results = st.selectbox(
                f"ページ ({total_pages_results}ページ中)",
                options=page_options_results,
                index=st.session_state.results_page - 1,
                key="results_page_select"
            )
            if selected_page_results != st.session_state.results_page:
                st.session_state.results_page = selected_page_results
                st.rerun()

        with col_page3:
            if st.button("次へ ▶", key="results_next_page", disabled=(st.session_state.results_page == total_pages_results)):
                st.session_state.results_page += 1
                st.rerun()

    # 現在のページの論文を取得
    start_idx_results = (st.session_state.results_page - 1) * ITEMS_PER_PAGE_RESULTS
    end_idx_results = min(start_idx_results + ITEMS_PER_PAGE_RESULTS, total_articles_results)
    current_page_articles_results = filtered_articles[start_idx_results:end_idx_results]

    # ページ情報を表示
    if total_pages_results > 1:
        st.info(f"📄 {start_idx_results + 1}〜{end_idx_results}件目を表示（全{total_articles_results}件中）")

    for i, article in enumerate(current_page_articles_results, start_idx_results + 1):
        with st.expander(
            f"[{i}] {article.get('title', 'No Title')} "
            f"(スコア: {article.get('relevance_score', 0)})",
            expanded=(i <= 5)  # 最初の5件は展開表示
        ):
            col1, col2 = st.columns([2, 1])

            with col1:
                pmid = article.get('pmid')
                doi = article.get('doi')
                article_id = article.get('article_id', f"pmid:{pmid}" if pmid else f"doi:{doi}" if doi else f"unknown_{i}")

                # PMID表示（ある場合のみ）
                if pmid:
                    st.markdown(f"**PMID:** [{pmid}]({article.get('url', '#')})")
                elif doi:
                    # PMIDがなくDOIのみの場合
                    st.markdown(f"**識別子:** DOIのみ")

                # DOI情報とリンク
                if doi:
                    # DOIリンク（京大 or 通常）
                    if use_kyoto_links:
                        doi_url = f"https://doi-org.kyoto-u.idm.oclc.org/{doi}"
                        st.markdown(f"**DOI:** [🔗 {doi}]({doi_url}) (京大プロキシ)")
                    else:
                        doi_url = f"https://doi.org/{doi}"
                        st.markdown(f"**DOI:** [🔗 {doi}]({doi_url})")

                    # 京都大学図書館Article Linkerへのリンク（DOIベース）
                    ku_linker_url = f"https://tt2mx4dc7s.search.serialssolutions.com/?sid=Entrez:PubMed&id=doi:{doi}"
                    st.markdown(f"**📚 京大図書館:** [Article Linker]({ku_linker_url})")
                elif pmid != 'N/A':
                    # DOIがない場合はPMIDベースのArticle Linker
                    ku_linker_url = f"https://tt2mx4dc7s.search.serialssolutions.com/?sid=Entrez:PubMed&id=pmid:{pmid}"
                    st.markdown(f"**📚 京大図書館:** [Article Linker]({ku_linker_url})")

                st.markdown(f"**著者:** {article.get('authors', 'N/A')}")
                st.markdown(f"**ジャーナル:** {article.get('journal', 'N/A')}")
                st.markdown(f"**出版年:** {article.get('pub_year', 'N/A')}")

                # 評価日時を表示
                evaluated_at = article.get('evaluated_at')
                if evaluated_at:
                    try:
                        dt = datetime.fromisoformat(evaluated_at)
                        display_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                        st.markdown(f"**評価日時:** {display_time}")
                    except:
                        st.markdown(f"**評価日時:** {evaluated_at}")

            with col2:
                score = article.get('relevance_score', 0)
                is_relevant = article.get('is_relevant', False)

                # スコアバッジ
                if score >= 80:
                    color = "green"
                elif score >= 60:
                    color = "blue"
                elif score >= 40:
                    color = "orange"
                else:
                    color = "red"

                st.markdown(f"**関連性スコア:** :{color}[{score}]")
                st.markdown(f"**関連あり:** {'✅ はい' if is_relevant else '❌ いいえ'}")
                st.markdown(f"**探索階層:** {article.get('depth', 0)}")

                # Notion登録状態を表示（Notion連携を使った場合のみ）
                if 'in_notion' in article:
                    if article.get('in_notion'):
                        st.markdown(f"**Notion:** 📝 登録済み")
                        # Notionページへのリンク
                        notion_page_id = article.get('notion_page_id')
                        if notion_page_id:
                            # ページIDのハイフンを削除してURLを構築
                            clean_page_id = notion_page_id.replace('-', '')
                            notion_url = f"https://www.notion.so/{clean_page_id}"
                            st.markdown(f"　　　　 [📄 Notionページを開く]({notion_url})")
                        if article.get('notion_score_updated'):
                            st.markdown("　　　　 ✅ スコア更新済み")
                    else:
                        st.markdown(f"**Notion:** ❌ 未登録")

                # ソース情報を表示
                source_pmid = article.get('source_pmid')
                source_type = article.get('source_type', '')
                if source_pmid:
                    source_type_jp = "類似論文" if source_type == "similar" else "引用論文"
                    st.markdown(f"**発見元:** PMID {source_pmid} の{source_type_jp}")
                elif source_type == "起点論文":
                    st.markdown(f"**発見元:** {source_type}")

            # アブストラクト
            if article.get('abstract'):
                with st.container():
                    st.markdown("**アブストラクト:**")
                    st.text(article['abstract'])

            # 日本語要約
            if article.get('abstract_summary_ja'):
                st.markdown("**📝 日本語要約:**")
                st.success(article['abstract_summary_ja'])

            # 評価理由
            if article.get('relevance_reasoning'):
                st.markdown("**AI評価理由:**")
                st.info(article['relevance_reasoning'])

            # コメント・メモ機能（プロジェクトがある場合のみ）
            if project:
                st.markdown("**📝 メモ・コメント:**")

                # プロジェクトから最新の論文データを取得
                project_article = project.get_article_by_id(article_id)
                existing_comment = project_article.get('comment', '') if project_article else ''

                # コメント入力エリア
                comment = st.text_area(
                    label="メモを入力",
                    value=existing_comment,
                    key=f"comment_result_{article_id}_{i}",
                    height=100,
                    label_visibility="collapsed",
                    placeholder="この論文に関するメモやコメントを入力してください..."
                )

                # コメント保存ボタン
                if st.button(
                    "💾 メモを保存",
                    key=f"save_comment_result_{article_id}_{i}",
                    type="secondary",
                    help="メモをプロジェクトに保存します"
                ):
                    if project_article:
                        # 論文のコメントを更新
                        project_article['comment'] = comment
                        project.articles[article_id] = project_article
                        project.save()
                        st.success("メモを保存しました")
                        st.rerun()
                    else:
                        st.warning("この論文はプロジェクトに保存されていません")

    st.divider()

    # JSON出力
    st.subheader("💾 データエクスポート")

    col1, col2, col3 = st.columns(3)

    with col1:
        # 全データ
        json_str = json.dumps(result, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 全データをJSON形式でダウンロード",
            data=json_str,
            file_name=f"pubmed_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )

    with col2:
        # フィルタ後のデータ
        filtered_result = {
            "articles": filtered_articles,
            "stats": stats
        }
        filtered_json_str = json.dumps(filtered_result, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 フィルタ後データをダウンロード",
            data=filtered_json_str,
            file_name=f"pubmed_search_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json"
        )

    with col3:
        # プロジェクト全体をエクスポート
        if project:
            project_json = project.export_to_json()
            st.download_button(
                label="📥 プロジェクト全体をダウンロード",
                data=project_json,
                file_name=f"project_{project.metadata['safe_name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )


if __name__ == "__main__":
    main()

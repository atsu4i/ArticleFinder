"""
論文検索自動化ツール - Streamlit WebGUI
"""

import streamlit as st
import json
import os
from datetime import datetime
from article_finder import ArticleFinder
from project_manager import ProjectManager
from gemini_evaluator import GeminiEvaluator


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

        # 探索の深さ
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            max_depth_slider = st.slider(
                "探索の深さ",
                min_value=1,
                max_value=5,
                value=2,
                help="何階層まで関連論文を辿るか",
                key="depth_slider"
            )
        with col_input:
            max_depth = st.number_input(
                "深さ",
                min_value=1,
                max_value=5,
                value=max_depth_slider,
                step=1,
                key="depth_input",
                label_visibility="collapsed"
            )

        # 最大論文数
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            max_articles_slider = st.slider(
                "最大論文数",
                min_value=10,
                max_value=1000,
                value=100,
                step=5,
                help="収集する論文の最大数",
                key="articles_slider"
            )
        with col_input:
            max_articles = st.number_input(
                "論文数",
                min_value=10,
                max_value=1000,
                value=max_articles_slider,
                step=5,
                key="articles_input",
                label_visibility="collapsed"
            )

        # 関連性スコア閾値
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            relevance_threshold_slider = st.slider(
                "関連性スコア閾値",
                min_value=0,
                max_value=100,
                value=60,
                step=5,
                help="この値以上のスコアの論文のみ次階層を探索",
                key="threshold_slider"
            )
        with col_input:
            relevance_threshold = st.number_input(
                "閾値",
                min_value=0,
                max_value=100,
                value=relevance_threshold_slider,
                step=5,
                key="threshold_input",
                label_visibility="collapsed"
            )

        st.divider()

        # 関連論文取得設定
        st.subheader("関連論文取得設定")

        # 1論文あたりの最大関連論文数
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            max_related_slider = st.slider(
                "1論文あたりの最大関連論文数",
                min_value=5,
                max_value=100,
                value=20,
                step=5,
                help="各論文から取得するSimilar articles / Cited byの最大数",
                key="max_related_slider"
            )
        with col_input:
            max_related_per_article = st.number_input(
                "最大数",
                min_value=5,
                max_value=100,
                value=max_related_slider,
                step=5,
                key="max_related_input",
                label_visibility="collapsed"
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

        include_similar = st.checkbox("Similar articles を探索", value=True)
        include_cited_by = st.checkbox("Cited by を探索", value=True)

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
            display_project_articles(project)

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
            include_cited_by=include_cited_by,
            project=project,
            max_related_per_article=max_related_per_article
        )

    # 検索結果がsession_stateにある場合は表示
    elif 'search_result' in st.session_state and 'current_project' in st.session_state:
        display_results(st.session_state['search_result'], st.session_state['current_project'])


def display_project_articles(project):
    """プロジェクト内の論文を表示"""
    articles = project.get_all_articles()

    # 関連性スコアでソート
    articles.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    # 統計情報
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("総論文数", len(articles))
    with col2:
        relevant_count = len([a for a in articles if a.get("is_relevant", False)])
        st.metric("関連論文数", relevant_count)
    with col3:
        avg_score = sum(a.get("relevance_score", 0) for a in articles) / len(articles) if articles else 0
        st.metric("平均スコア", f"{avg_score:.1f}")

    st.divider()

    # フィルタ
    st.subheader("🔍 論文フィルタ")

    col1, col2 = st.columns(2)

    with col1:
        show_only_relevant = st.checkbox(
            "関連論文のみ表示",
            value=False,
            key="project_filter_relevant"
        )

    with col2:
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            min_score_slider = st.slider(
                "最小スコア",
                min_value=0,
                max_value=100,
                value=0,
                step=5,
                key="project_filter_slider"
            )
        with col_input:
            min_score_filter = st.number_input(
                "スコア",
                min_value=0,
                max_value=100,
                value=min_score_slider,
                step=5,
                key="project_filter_input",
                label_visibility="collapsed"
            )

    # 論文リストをフィルタ
    filtered_articles = articles

    if show_only_relevant:
        filtered_articles = [a for a in filtered_articles if a.get("is_relevant", False)]

    filtered_articles = [
        a for a in filtered_articles
        if a.get("relevance_score", 0) >= min_score_filter
    ]

    st.info(f"表示件数: {len(filtered_articles)} / {len(articles)}")

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

    for i, article in enumerate(filtered_articles, 1):
        with st.expander(
            f"[{i}] {article.get('title', 'No Title')} "
            f"(スコア: {article.get('relevance_score', 0)})",
            expanded=(i <= 5)  # 最初の5件は展開表示
        ):
            col1, col2 = st.columns([2, 1])

            with col1:
                st.markdown(f"**PMID:** [{article.get('pmid', 'N/A')}]({article.get('url', '#')})")
                st.markdown(f"**著者:** {article.get('authors', 'N/A')}")
                st.markdown(f"**ジャーナル:** {article.get('journal', 'N/A')}")
                st.markdown(f"**出版年:** {article.get('pub_year', 'N/A')}")

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
                    st.text(article['abstract'][:500] + "..." if len(article['abstract']) > 500 else article['abstract'])

            # 評価理由
            if article.get('relevance_reasoning'):
                st.markdown("**AI評価理由:**")
                st.info(article['relevance_reasoning'])

            st.divider()

            # 論文削除ボタン
            pmid = article.get('pmid')

            if st.button(
                "🗑️ この論文を削除",
                key=f"delete_{pmid}",
                type="secondary",
                use_container_width=True,
                help="プロジェクトから削除します。次回検索時に再度発見されれば再評価されます。"
            ):
                if project.delete_article(pmid):
                    project.save()
                    st.success(f"論文 PMID {pmid} を削除しました")
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
    include_cited_by: bool,
    project,
    max_related_per_article: int = 20
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
        # ArticleFinderを初期化
        finder = ArticleFinder(gemini_api_key=api_key, gemini_model=gemini_model)

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
                include_cited_by=include_cited_by,
                progress_callback=progress_callback,
                project=project,
                should_stop_callback=should_stop,
                max_related_per_article=max_related_per_article
            )

        # 停止ボタンを非表示
        stop_button_placeholder.empty()

        # 完了メッセージ
        if st.session_state.get('stop_search', False):
            status_placeholder.warning("⏸️ 探索を途中で停止しました（部分的な結果を表示）")
            st.session_state['stop_search'] = False
        else:
            status_placeholder.success("✅ 探索が完了しました！")

        # 結果を表示
        display_results(result, project)

        # セッションに保存（ダウンロード用とフィルタ変更時の再表示用）
        st.session_state['search_result'] = result
        st.session_state['current_project'] = project

    except Exception as e:
        st.error(f"エラーが発生しました: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
    finally:
        # 停止フラグをリセット
        st.session_state['stop_search'] = False


def display_results(result: dict, project=None):
    """検索結果を表示"""

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

    col1, col2 = st.columns(2)

    with col1:
        show_only_relevant = st.checkbox(
            "関連論文のみ表示",
            value=False,
            key="results_filter_relevant"
        )

    with col2:
        col_slider, col_input = st.columns([3, 1])
        with col_slider:
            min_score_slider = st.slider(
                "最小スコア",
                min_value=0,
                max_value=100,
                value=0,
                step=5,
                key="results_filter_slider"
            )
        with col_input:
            min_score_filter = st.number_input(
                "スコア",
                min_value=0,
                max_value=100,
                value=min_score_slider,
                step=5,
                key="results_filter_input",
                label_visibility="collapsed"
            )

    # 論文リストをフィルタ
    filtered_articles = articles

    if show_only_relevant:
        filtered_articles = [a for a in filtered_articles if a.get("is_relevant", False)]

    filtered_articles = [
        a for a in filtered_articles
        if a.get("relevance_score", 0) >= min_score_filter
    ]

    st.info(f"表示件数: {len(filtered_articles)} / {len(articles)}")

    # 論文リストを表示
    st.subheader("📄 論文リスト")

    for i, article in enumerate(filtered_articles, 1):
        with st.expander(
            f"[{i}] {article.get('title', 'No Title')} "
            f"(スコア: {article.get('relevance_score', 0)})",
            expanded=(i <= 5)  # 最初の5件は展開表示
        ):
            col1, col2 = st.columns([2, 1])

            with col1:
                st.markdown(f"**PMID:** [{article.get('pmid', 'N/A')}]({article.get('url', '#')})")
                st.markdown(f"**著者:** {article.get('authors', 'N/A')}")
                st.markdown(f"**ジャーナル:** {article.get('journal', 'N/A')}")
                st.markdown(f"**出版年:** {article.get('pub_year', 'N/A')}")

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
                    st.text(article['abstract'][:500] + "..." if len(article['abstract']) > 500 else article['abstract'])

            # 評価理由
            if article.get('relevance_reasoning'):
                st.markdown("**AI評価理由:**")
                st.info(article['relevance_reasoning'])

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

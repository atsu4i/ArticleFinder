"""
論文検索自動化ツール - Streamlit WebGUI
"""

import streamlit as st
import json
import os
import math
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from article_finder import ArticleFinder
from project_manager import ProjectManager
from gemini_evaluator import GeminiEvaluator
from embedding_manager import EmbeddingManager
from altmetric_api import AltmetricAPI
from st_link_analysis import st_link_analysis, NodeStyle, EdgeStyle, Event
import streamlit.components.v1 as components
import plotly.express as px


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


def load_user_settings() -> Dict:
    """
    ユーザー設定を読み込む

    Returns:
        ユーザー設定の辞書
    """
    settings_path = os.path.join(os.path.dirname(__file__), 'user_settings.json')

    # デフォルト設定
    default_settings = {
        'doi_proxy_template': '',  # 空の場合は通常のDOI（https://doi.org/{doi}）
        'library_link_template': ''  # 空の場合は非表示
    }

    try:
        if os.path.exists(settings_path):
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                # デフォルト設定とマージ（新しい設定項目への対応）
                return {**default_settings, **settings}
        else:
            return default_settings
    except Exception as e:
        print(f"Failed to load user settings: {e}")
        return default_settings


def build_doi_url(doi: str, template: str = '') -> Tuple[str, str]:
    """
    DOI URLを構築

    Args:
        doi: DOI
        template: URLテンプレート（{doi}が置換される）

    Returns:
        (url, label): URLとラベル文字列のタプル
    """
    if template and '{doi}' in template:
        url = template.replace('{doi}', doi)
        label = "(機関プロキシ)"
    else:
        url = f"https://doi.org/{doi}"
        label = ""
    return url, label


def build_library_link(pmid: str, doi: str, template: str = '') -> Optional[str]:
    """
    図書館リンクURLを構築

    Args:
        pmid: PMID
        doi: DOI
        template: URLテンプレート（{pmid}や{doi}が置換される）

    Returns:
        URL文字列（テンプレートが空の場合はNone）
    """
    if not template:
        return None

    url = template
    if '{pmid}' in url and pmid:
        url = url.replace('{pmid}', pmid)
    if '{doi}' in url and doi:
        url = url.replace('{doi}', doi)

    return url


def save_user_settings(settings: Dict) -> bool:
    """
    ユーザー設定を保存

    Args:
        settings: 保存する設定の辞書

    Returns:
        True if successfully saved, False otherwise
    """
    settings_path = os.path.join(os.path.dirname(__file__), 'user_settings.json')

    try:
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Failed to save user settings: {e}")
        return False


@st.cache_data
def generate_network_graph(articles: List[Dict], highlight_id: str = "") -> Dict:
    """
    論文のネットワークグラフを生成（st-link-analysis用）

    Args:
        articles: 論文リスト

    Returns:
        st-link-analysisで使用する elements 辞書
    """
    # ノードとエッジのデータを準備
    # IDを確実に文字列型にするために辞書のキーも文字列化
    article_dict = {str(a["article_id"]): a for a in articles}

    nodes = []
    edges = []
    edge_id = 0

    # 各論文をノードとして追加
    for article in articles:
        article_id = str(article["article_id"])  # IDを文字列型に強制変換
        title = article.get("title", "不明なタイトル")
        relevance_score = article.get("relevance_score", 0)
        mentioned_by = article.get("mentioned_by", [])
        link_count = len(mentioned_by)

        # PMID/DOIを取得
        pmid = article.get("pmid", "")
        doi = article.get("doi", "")
        display_id = f"PMID:{pmid}" if pmid else f"DOI:{doi}"

        # 検索対象かどうかを判定
        is_highlighted = False
        if highlight_id:
            # PMID または DOI で一致するかチェック
            if (pmid and str(pmid) == highlight_id) or (doi and doi == highlight_id):
                is_highlighted = True

        # スコアに応じたラベルを設定（色分け用・5段階）
        if is_highlighted:
            score_label = "HIGHLIGHT"  # 強調表示
        elif relevance_score >= 81:
            score_label = "EXCELLENT"  # 81-100: 濃い赤
        elif relevance_score >= 61:
            score_label = "GOOD"  # 61-80: オレンジ
        elif relevance_score >= 41:
            score_label = "MODERATE"  # 41-60: 黄色
        elif relevance_score >= 21:
            score_label = "FAIR"  # 21-40: 薄い青
        else:
            score_label = "POOR"  # 1-20: 濃い青

        # ノードサイズを関連論文数に応じて計算（20-120の範囲）
        # link_count を使ってサイズを動的に変更
        # ハイライトの場合は大きく表示
        if is_highlighted:
            node_size = 150  # 強調表示用に大きく
        else:
            node_size = 20 + min(link_count * 10, 100)  # 最小20、最大120

        # ノードを追加（Cytoscape.js形式）
        # サイドパネルに表示する情報を最小限に
        nodes.append({
            "data": {
                "id": article_id,
                "label": score_label,
                "name": (title[:80] + "..." if len(title) > 80 else title) if title else "タイトル不明",  # タイトルを表示（80文字まで）
                "score": relevance_score,
                "links": link_count,
                "pmid": pmid if pmid else "-",
                "doi": doi if doi else "-"
            },
            "style": {
                "width": node_size,
                "height": node_size
            }
        })

    # エッジを追加（親 → 子）
    for article in articles:
        article_id = str(article["article_id"])  # IDを文字列型に強制変換
        mentioned_by = article.get("mentioned_by", [])

        # この論文を参照している親論文からエッジを引く
        for parent_id in mentioned_by:
            parent_id_str = str(parent_id)  # IDを文字列型に強制変換
            # 親論文がフィルタ後のリストに存在する場合のみエッジを追加
            if parent_id_str in article_dict:
                edges.append({
                    "data": {
                        "id": str(edge_id),
                        "source": parent_id_str,
                        "target": article_id,
                        "label": "CITES"
                    }
                })
                edge_id += 1

    return {"nodes": nodes, "edges": edges}


@st.cache_data
def generate_citation_network_graph(articles: List[Dict], highlight_id: str = "") -> Dict:
    """
    論文のネットワークグラフを生成（被引用数ベース、st-link-analysis用）

    Args:
        articles: 論文リスト

    Returns:
        st-link-analysisで使用する elements 辞書
    """
    # ノードとエッジのデータを準備
    article_dict = {str(a["article_id"]): a for a in articles}

    nodes = []
    edges = []
    edge_id = 0

    # 被引用数の平方根の最大値を取得（平方根スケーリング用）
    citation_counts = [a.get("citation_count", 0) for a in articles]
    max_citations = max(citation_counts) if citation_counts else 0
    max_sqrt_citations = math.sqrt(max_citations) if max_citations > 0 else 0

    # 各論文をノードとして追加
    for article in articles:
        article_id = str(article["article_id"])
        title = article.get("title", "不明なタイトル")
        relevance_score = article.get("relevance_score", 0)
        mentioned_by = article.get("mentioned_by", [])
        link_count = len(mentioned_by)
        citation_count = article.get("citation_count", 0)  # OpenAlexの被引用数

        # PMID/DOIを取得
        pmid = article.get("pmid", "")
        doi = article.get("doi", "")
        display_id = f"PMID:{pmid}" if pmid else f"DOI:{doi}"

        # 検索対象かどうかを判定
        is_highlighted = False
        if highlight_id:
            # PMID または DOI で一致するかチェック
            if (pmid and str(pmid) == highlight_id) or (doi and doi == highlight_id):
                is_highlighted = True

        # スコアに応じたラベルを設定（色分け用・5段階）
        if is_highlighted:
            score_label = "HIGHLIGHT"  # 強調表示
        elif relevance_score >= 81:
            score_label = "EXCELLENT"
        elif relevance_score >= 61:
            score_label = "GOOD"
        elif relevance_score >= 41:
            score_label = "MODERATE"
        elif relevance_score >= 21:
            score_label = "FAIR"
        else:
            score_label = "POOR"

        # ノードサイズを被引用数に応じて計算（平方根スケーリング: 20-120px）
        # 平方根を取ってから正規化することで、低い値でもある程度のサイズを確保
        # ハイライトの場合は大きく表示
        if is_highlighted:
            node_size = 150  # 強調表示用に大きく
        elif max_sqrt_citations > 0:
            # 平方根を取ってから0-1に正規化し、20-120pxにマッピング
            sqrt_citation = math.sqrt(citation_count)
            normalized = sqrt_citation / max_sqrt_citations
            node_size = 20 + int(normalized * 100)  # 20-120の範囲
        else:
            # 被引用数が全て0の場合
            node_size = 60  # 中間サイズ

        # ノードを追加
        nodes.append({
            "data": {
                "id": article_id,
                "label": score_label,
                "name": (title[:80] + "..." if len(title) > 80 else title) if title else "タイトル不明",
                "score": relevance_score,
                "links": link_count,
                "citations": citation_count,  # 被引用数を追加
                "pmid": pmid if pmid else "-",
                "doi": doi if doi else "-"
            },
            "style": {
                "width": node_size,
                "height": node_size
            }
        })

    # エッジを追加（親 → 子）
    for article in articles:
        article_id = str(article["article_id"])
        mentioned_by = article.get("mentioned_by", [])

        for parent_id in mentioned_by:
            parent_id_str = str(parent_id)
            if parent_id_str in article_dict:
                edges.append({
                    "data": {
                        "id": str(edge_id),
                        "source": parent_id_str,
                        "target": article_id,
                        "label": "CITES"
                    }
                })
                edge_id += 1

    return {"nodes": nodes, "edges": edges}


def generate_semantic_map(articles: List[Dict], api_key: str, project=None):
    """
    論文のセマンティック・マップ（意味的類似性マップ）を生成・表示

    Args:
        articles: 論文リスト
        api_key: Gemini API Key
        project: プロジェクトオブジェクト（保存用）
    """
    import pandas as pd

    # ベクトル化済みの論文数をカウント
    articles_with_embedding = [a for a in articles if a.get("embedding")]
    articles_without_embedding = [a for a in articles if not a.get("embedding")]

    total_articles = len(articles)
    vectorized_count = len(articles_with_embedding)

    if len(articles_without_embedding) > 0:
        # 未ベクトル化の論文がある場合
        st.warning(
            f"⚠️ 未計算の論文が {len(articles_without_embedding)} 件あります。\n\n"
            f"マップを表示するにはベクトル計算（Gemini Embedding API）が必要です。\n\n"
            f"**注意**: Embedding APIの使用には有料tierのAPIキーが必要です。"
            f"ただし、無料枠内で計算可能な場合がほとんどで、料金はかからないかごくわずかです。"
        )

        # ベクトル計算ボタンとキャッシュクリアボタンを横並びに配置
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔮 ベクトルを計算してマップを作成", type="primary", use_container_width=True):
                # ベクトル化を実行
                try:
                    embedding_manager = EmbeddingManager(api_key=api_key)

                    # プログレスバーを表示
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    def progress_callback(message, current, total):
                        if total > 0:
                            progress_bar.progress(current / total)
                        status_text.info(message)

                    # バッチでベクトル化
                    embedding_manager.embed_articles_batch(
                        articles,
                        batch_size=100,
                        progress_callback=progress_callback
                    )

                    # 2次元座標を計算
                    status_text.info("UMAP で2次元座標を計算中...")
                    embedding_manager.calculate_2d_coordinates(articles)

                    progress_bar.empty()
                    status_text.success("✅ ベクトル化完了！")

                    # プロジェクトに保存
                    if project:
                        for article in articles:
                            project.add_article(article)
                        project.save()

                    st.rerun()

                except Exception as e:
                    st.error(f"ベクトル化中にエラーが発生しました: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        with col2:
            if st.button("🗑️ キャッシュクリア", use_container_width=True, help="グラフのキャッシュをクリアしてメモリを解放します", key="clear_cache_tab3_1"):
                # クリアするセッションステートのキー
                keys_to_clear = [
                    'show_network_graph', 'network_graph_articles', 'network_graph_elements', 'last_network_graph_selection',
                    'show_citation_graph', 'citation_graph_articles', 'citation_graph_elements', 'last_citation_graph_selection',
                    'show_semantic_map', 'semantic_map_articles', 'last_semantic_map_selection',
                    'show_results_network_graph', 'results_network_graph_articles', 'results_network_graph_elements',
                    'selected_article_id'
                ]
                for key in keys_to_clear:
                    if key in st.session_state:
                        del st.session_state[key]
                st.success(f"✅ キャッシュをクリアしました")
                st.rerun()
    else:
        # 全ての論文がベクトル化済み
        st.success(f"✅ 全 {total_articles} 件の論文がベクトル化済みです")

        # セッションステートでマップ生成状態を管理
        if 'show_semantic_map' not in st.session_state:
            st.session_state.show_semantic_map = False
        if 'semantic_map_articles' not in st.session_state:
            st.session_state.semantic_map_articles = []

        # 論文検索機能
        search_id_semantic = st.text_input(
            "🔍 論文を検索（PMID または DOI）",
            value="",
            placeholder="例: 12345678 または 10.1038/...",
            key="semantic_map_search",
            help="指定した論文をマップ上で強調表示します"
        )

        # マップ生成ボタンとキャッシュクリアボタンを横並びに配置
        button_label = "🔄 マップを更新" if st.session_state.show_semantic_map else "🔮 セマンティック・マップを生成"

        col1, col2 = st.columns(2)
        with col1:
            if st.button(button_label, type="primary", use_container_width=True, key="generate_semantic_map_btn"):
                st.session_state.show_semantic_map = True
                # ボタン押下時のarticlesをスナップショットとして保存
                st.session_state.semantic_map_articles = articles.copy()
                st.session_state.semantic_map_search_id = search_id_semantic.strip()

        with col2:
            if st.button("🗑️ キャッシュクリア", use_container_width=True, help="グラフのキャッシュをクリアしてメモリを解放します", key="clear_cache_tab3_2"):
                # クリアするセッションステートのキー
                keys_to_clear = [
                    'show_network_graph', 'network_graph_articles', 'network_graph_elements', 'last_network_graph_selection',
                    'show_citation_graph', 'citation_graph_articles', 'citation_graph_elements', 'last_citation_graph_selection',
                    'show_semantic_map', 'semantic_map_articles', 'last_semantic_map_selection',
                    'show_results_network_graph', 'results_network_graph_articles', 'results_network_graph_elements',
                    'selected_article_id'
                ]
                for key in keys_to_clear:
                    if key in st.session_state:
                        del st.session_state[key]
                st.success(f"✅ キャッシュをクリアしました")
                st.rerun()

        # マップが生成済みの場合のみ表示
        if st.session_state.show_semantic_map:
            # スナップショットを使用（フィルタ変更の影響を受けない）
            map_articles = st.session_state.semantic_map_articles

            # 2次元座標がない場合は計算
            articles_with_coords = [a for a in map_articles if a.get("umap_x") is not None]
            if len(articles_with_coords) < len(map_articles):
                try:
                    embedding_manager = EmbeddingManager(api_key=api_key)
                    with st.spinner("UMAP で2次元座標を計算中..."):
                        embedding_manager.calculate_2d_coordinates(map_articles)

                    # プロジェクトに保存
                    if project:
                        for article in map_articles:
                            project.add_article(article)
                        project.save()

                    # スナップショットを更新
                    st.session_state.semantic_map_articles = map_articles
                    st.rerun()
                except Exception as e:
                    st.error(f"座標計算中にエラーが発生しました: {e}")
                    return

            # マップを描画
            articles_with_coords = [a for a in map_articles if a.get("umap_x") is not None]
            if len(articles_with_coords) >= 2:
                # Plotly 散布図用のデータフレームを作成
                df_data = []
                customdata_list = []
                for article in map_articles:
                    if article.get("umap_x") is not None and article.get("umap_y") is not None:
                        pmid = article.get("pmid", "")
                        doi = article.get("doi", "")
                        display_id = f"PMID:{pmid}" if pmid else f"DOI:{doi}"
                        full_title = article.get("title", "")
                        relevance_score = article.get("relevance_score", 0)
                        link_count = len(article.get("mentioned_by", []))
                        citation_count = article.get("citation_count", 0)
                        article_id = article.get("article_id", "")

                        df_data.append({
                            "x": article["umap_x"],
                            "y": article["umap_y"],
                            "title": full_title[:60] + "..." if len(full_title) > 60 else full_title,
                            "relevance_score": relevance_score,
                            "link_count": link_count,
                        })

                        # カスタムデータ（ホバー表示用）
                        customdata_list.append([
                            article_id,        # [0]
                            full_title,        # [1]
                            display_id,        # [2]
                            relevance_score,   # [3]
                            link_count,        # [4]
                            citation_count     # [5]
                        ])

                df = pd.DataFrame(df_data)

                # Plotly 散布図を作成
                fig = px.scatter(
                    df,
                    x="x",
                    y="y",
                    color="relevance_score",
                    size="link_count",
                    color_continuous_scale=[
                        [0.0, "rgb(100, 100, 255)"],   # 濃い青（0点）
                        [0.39, "rgb(200, 200, 255)"],  # 薄い青（39点）
                        [0.40, "rgb(255, 255, 100)"],  # 黄色（40点）
                        [0.69, "rgb(255, 255, 0)"],    # 濃い黄色（69点）
                        [0.70, "rgb(255, 150, 150)"],  # ピンク（70点）
                        [1.0, "rgb(255, 0, 0)"]        # 濃い赤（100点）
                    ],
                    range_color=[0, 100],
                    title="セマンティック・マップ（意味的類似性マップ）"
                )

                # カスタムデータとホバーテンプレートを設定
                fig.update_traces(
                    customdata=customdata_list,
                    hovertemplate="<b>%{customdata[1]}</b><br>" +
                                  "ID: %{customdata[2]}<br>" +
                                  "関連性スコア: %{customdata[3]}<br>" +
                                  "被発見数: %{customdata[4]}件<br>" +
                                  "被引用数: %{customdata[5]}件<br>" +
                                  "<extra></extra>"
                )

                # レイアウト調整
                fig.update_layout(
                    height=600,
                    xaxis_title="",
                    yaxis_title="",
                    showlegend=True,
                    hovermode='closest'
                )

                # 軸の目盛りを非表示
                fig.update_xaxes(showticklabels=False, showgrid=False)
                fig.update_yaxes(showticklabels=False, showgrid=False)

                # 検索された論文を強調表示
                if 'semantic_map_search_id' in st.session_state and st.session_state.semantic_map_search_id:
                    highlight_id = st.session_state.semantic_map_search_id
                    # 該当する論文を検索
                    for article in map_articles:
                        if article.get("umap_x") is not None and article.get("umap_y") is not None:
                            pmid = article.get("pmid", "")
                            doi = article.get("doi", "")
                            if (pmid and str(pmid) == highlight_id) or (doi and doi == highlight_id):
                                # 該当する論文を星マーカーで強調表示
                                fig.add_scatter(
                                    x=[article["umap_x"]],
                                    y=[article["umap_y"]],
                                    mode='markers',
                                    marker=dict(
                                        symbol='star',
                                        size=30,
                                        color='lime',
                                        line=dict(color='darkgreen', width=2)
                                    ),
                                    name=f'🔍 検索結果',
                                    hovertext=article.get("title", "")[:100],
                                    showlegend=True
                                )
                                break

                # クリックイベントを受け取る
                selected = st.plotly_chart(
                    fig,
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="points",
                    key="semantic_map_chart"
                )

                # 選択された論文を論文リストで表示（直接ジャンプ）
                # 無限ループを防ぐため、前回処理したIDを記録
                if 'last_semantic_map_selection' not in st.session_state:
                    st.session_state.last_semantic_map_selection = None

                if selected and "selection" in selected and "points" in selected["selection"]:
                    points = selected["selection"]["points"]
                    if len(points) > 0:
                        # 最初に選択されたポイントを取得
                        point_index = points[0]["point_index"]
                        selected_article = articles_with_coords[point_index]
                        selected_id = selected_article["article_id"]

                        # 前回と同じ選択なら処理をスキップ（無限ループ防止）
                        if st.session_state.last_semantic_map_selection != selected_id:
                            # 論文リストで該当論文を選択状態にして、自動スクロール
                            st.session_state.selected_article_id = selected_id
                            st.session_state.last_semantic_map_selection = selected_id

                            # 選択された論文が含まれるページに移動
                            # 論文リスト全体（articles）から該当論文のインデックスを探す
                            global_index = next((i for i, a in enumerate(articles) if a["article_id"] == selected_id), 0)
                            target_page = (global_index // 20) + 1  # 20件/ページ（ITEMS_PER_PAGE）
                            st.session_state.project_page = target_page

                            # on_select="rerun" により自動的に再実行されるので、明示的なst.rerun()は不要
                            # ただし、確実にジャンプするために一度だけ呼ぶ
                            st.rerun()
                    else:
                        # 選択がクリアされた場合、フラグをリセット
                        st.session_state.last_semantic_map_selection = None
                else:
                    # 選択がない場合もフラグをリセット
                    st.session_state.last_semantic_map_selection = None

                st.info(
                    "💡 **マップの見方**\n\n"
                    "- **位置が近い論文** = 内容が意味的に類似\n"
                    "- **点の色** = 関連性スコア（赤=高、黄=中、青=低）\n"
                    "- **点の大きさ** = 被リンク数（大きいほど重要なハブ論文）\n"
                    "- **ホバー** = タイトルと詳細情報を表示\n"
                    "- **クリック** = 論文リストの詳細にジャンプ"
                )
            else:
                st.info("マップを表示するには2件以上の論文が必要です")
        else:
            st.info("👆 上のボタンを押すとセマンティック・マップが生成されます。")


def main():
    st.set_page_config(
        page_title="論文検索自動化ツール",
        page_icon="📚",
        layout="wide"
    )

    st.title("📚 学術論文検索自動化ツール")
    st.markdown("""
    起点となる論文から関連論文を自動的に探索し、AIがあなたの研究テーマに合った論文を見つけます。

    ### 🚀 主な機能

    - **自動探索**: PubMed・OpenAlexから類似論文・引用論文・参考文献を再帰的に探索
    - **AI評価**: Google AI (Gemini) がアブストラクトと研究テーマの関連性を自動評価（スコア付き）
    - **プロジェクト管理**: 評価済み論文をキャッシュして重複評価を防止、API コスト削減
    - **可視化**: ネットワークグラフとセマンティックマップで論文の関係性を直感的に把握
    - **Notion連携**: 評価した論文を自動でNotionデータベースに登録
    - **メモ機能**: 論文ごとにコメントを保存して研究ノートとして活用

    💡 **使い方**: サイドバーで設定後、起点論文（PMID/URL/DOI）と研究テーマを入力して検索開始！
    """)

    # プロジェクトマネージャーを初期化
    pm = ProjectManager()

    # ユーザー設定を読み込む
    user_settings = load_user_settings()

    # サイドバー: 設定
    with st.sidebar:
        st.header("⚙️ 設定")

        # 1. プロジェクト選択（最上部）
        st.subheader("📁 プロジェクト")

        project_mode = st.radio(
            "モード選択",
            ["新規プロジェクト作成", "既存プロジェクトを開く"],
            help="新規作成するか、既存プロジェクトを開くか選択"
        )

        project = None

        if project_mode == "新規プロジェクト作成":
            project_name = st.text_input(
                "プロジェクト名",
                placeholder="例: 小児喘息の治療研究",
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
            st.session_state.config_max_depth_slider = 3
        if 'config_max_depth_input' not in st.session_state:
            st.session_state.config_max_depth_input = 3
        if 'config_max_articles_slider' not in st.session_state:
            st.session_state.config_max_articles_slider = 500
        if 'config_max_articles_input' not in st.session_state:
            st.session_state.config_max_articles_input = 500
        if 'config_threshold_slider' not in st.session_state:
            st.session_state.config_threshold_slider = 80
        if 'config_threshold_input' not in st.session_state:
            st.session_state.config_threshold_input = 80

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
                value=50,
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
                value=50,
                step=5,
                disabled=not st.session_state.get("include_cited_by", True),
                key="max_cited_by",
                help="1論文あたりの最大取得数"
            )

        # References設定
        st.markdown("**References（この論文が引用している文献）**")
        col1, col2 = st.columns([3, 2])
        with col1:
            include_references = st.checkbox("Referencesを探索", value=True, key="include_references")
        with col2:
            max_references = st.number_input(
                "最大数",
                min_value=5,
                max_value=100,
                value=50,
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

        st.divider()

        # 5. 外部連携
        st.subheader("外部連携")

        # Notion連携
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

        # 機関別リンク設定
        st.markdown("#### 機関別リンク設定")
        st.info("💡 所属機関の電子ジャーナルアクセスやArticle Linkerを利用する場合に設定してください。設定例はREADME.mdを参照。")

        doi_proxy_template = st.text_input(
            "DOIプロキシURL テンプレート",
            value=user_settings.get('doi_proxy_template', ''),
            placeholder="例: https://doi-org.kyoto-u.idm.oclc.org/{doi}",
            help="{doi} の部分にDOIが挿入されます。空欄の場合は通常のDOI（https://doi.org/{doi}）を使用します。"
        )

        library_link_template = st.text_input(
            "図書館リンクURL テンプレート",
            value=user_settings.get('library_link_template', ''),
            placeholder="例: https://xxx.search.serialssolutions.com/?sid=Entrez:PubMed&id=doi:{doi}",
            help="{doi} や {pmid} が使えます。空欄の場合は図書館リンクを表示しません。"
        )

        # 設定が変更されたら自動保存
        if (doi_proxy_template != user_settings.get('doi_proxy_template', '') or
            library_link_template != user_settings.get('library_link_template', '')):
            user_settings['doi_proxy_template'] = doi_proxy_template
            user_settings['library_link_template'] = library_link_template
            save_user_settings(user_settings)

        st.divider()

        # 6. API設定（最下部）
        st.subheader("API設定")

        # API Keyの初期値を取得
        env_api_key = os.getenv("GEMINI_API_KEY", "")

        api_key = st.text_input(
            "Google AI API Key (Gemini)",
            type="password",
            value=env_api_key,
            help="https://aistudio.google.com/app/apikey から取得"
        )

        # API Keyの検証
        if not api_key:
            st.error("⚠️ Google AI API Keyを入力してください")
            st.info("API Keyは [Google AI Studio](https://aistudio.google.com/app/apikey) から取得できます")
            st.stop()

        if not is_valid_api_key(api_key):
            st.error("⚠️ 無効なAPI Keyです")
            st.warning(
                "デフォルトまたはプレースホルダーのAPI Keyが設定されています。\n\n"
                "正しいAPI Keyを入力してください。\n\n"
                "API Keyは [Google AI Studio](https://aistudio.google.com/app/apikey) から取得できます"
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

        # 評価モデル選択
        gemini_model = st.selectbox(
            "評価モデル (Gemini)",
            options=GeminiEvaluator.AVAILABLE_MODELS,
            index=GeminiEvaluator.AVAILABLE_MODELS.index(GeminiEvaluator.DEFAULT_MODEL),
            help="論文評価に使用するGeminiモデル。flash系は高速・低コスト、pro系は高精度"
        )

    # ネットワークグラフからのクリックによる検索開始の処理
    default_start_pmid = ""
    auto_start_search = False
    if 'clicked_article_for_search' in st.session_state:
        clicked_info = st.session_state.clicked_article_for_search
        default_start_pmid = clicked_info["id"]
        auto_start_search = clicked_info.get("auto_start", False)
        st.info(f"📌 ネットワークグラフで選択した論文を起点に検索します：\n\n**{clicked_info['title'][:100]}...**")
        # セッションステートをクリア
        del st.session_state.clicked_article_for_search

    # メインエリア
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📝 入力")

        start_pmid = st.text_input(
            "起点論文のPMID / URL / DOI",
            value=default_start_pmid,
            placeholder="例: 12345678、https://pubmed.ncbi.nlm.nih.gov/12345678/、10.1038/nature12345",
            help="探索を開始する論文のPubMed ID、URL、またはDOI（DOI形式: 10.xxxx/yyyy）"
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
            placeholder="例: 小児喘息患者における吸入ステロイド薬の長期使用が成長に与える影響について研究している論文を探しています。特に低用量から中用量のステロイド使用における安全性や、代替治療法との比較研究に興味があります。",
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
                doi_proxy_template=doi_proxy_template,
                library_link_template=library_link_template
            )

    # 実行ボタン
    st.divider()

    # ボタンが押されたか、自動開始フラグが立っている場合に検索実行
    if st.button("🚀 論文検索を開始", type="primary", use_container_width=True) or auto_start_search:
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
        display_results(st.session_state['search_result'], st.session_state['current_project'],
                       doi_proxy_template, library_link_template)


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
    doi_proxy_template: str = '',
    library_link_template: str = ''
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

        # 確認済みフィルタ
        checked_filter = st.radio(
            "確認済み状態",
            options=["すべて", "確認済みのみ", "未確認のみ"],
            index=0,
            key="project_filter_checked",
            help="論文の確認済み状態でフィルタリングします"
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

    # 出版年フィルタ（2列目の行）
    col5, col6 = st.columns(2)

    with col5:
        start_year_input = st.text_input(
            "出版年（開始）",
            value="",
            placeholder="指定なし",
            key="project_filter_start_year",
            help="この年以降に出版された論文を表示（空白の場合は指定なし）"
        )
        # 入力値の検証と変換
        if start_year_input.strip():
            try:
                start_year = int(start_year_input.strip())
            except ValueError:
                st.error("開始年は数字で入力してください")
                start_year = None
        else:
            start_year = None

    with col6:
        end_year_input = st.text_input(
            "出版年（終了）",
            value="",
            placeholder="指定なし",
            key="project_filter_end_year",
            help="この年以前に出版された論文を表示（空白の場合は指定なし）"
        )
        # 入力値の検証と変換
        if end_year_input.strip():
            try:
                end_year = int(end_year_input.strip())
            except ValueError:
                st.error("終了年は数字で入力してください")
                end_year = None
        else:
            end_year = None

    # 被引用数フィルタ（3列目の行）
    col7, col8 = st.columns(2)

    with col7:
        min_citation_input = st.text_input(
            "被引用数（最小）",
            value="",
            placeholder="指定なし",
            key="project_filter_min_citation",
            help="この件数以上の被引用数を持つ論文を表示（空白の場合は指定なし）"
        )
        # 入力値の検証と変換
        if min_citation_input.strip():
            try:
                min_citation = int(min_citation_input.strip())
            except ValueError:
                st.error("最小被引用数は数字で入力してください")
                min_citation = None
        else:
            min_citation = None

    with col8:
        max_citation_input = st.text_input(
            "被引用数（最大）",
            value="",
            placeholder="指定なし",
            key="project_filter_max_citation",
            help="この件数以下の被引用数を持つ論文を表示（空白の場合は指定なし）"
        )
        # 入力値の検証と変換
        if max_citation_input.strip():
            try:
                max_citation = int(max_citation_input.strip())
            except ValueError:
                st.error("最大被引用数は数字で入力してください")
                max_citation = None
        else:
            max_citation = None

    # 発見元論文フィルタ（4列目の行）
    st.text_input(
        "発見元論文（PMID または DOI）",
        value="",
        placeholder="例: 12345678 または 10.1038/...",
        key="project_filter_source_article",
        help="指定した論文から抽出された論文のみを表示（空白の場合は指定なし）"
    )
    source_article_input = st.session_state.get("project_filter_source_article", "").strip()

    # 発見元論文のarticle_idを取得
    source_article_id = None
    if source_article_input:
        # PMIDまたはDOIで論文を検索
        for article in articles:
            pmid = article.get("pmid", "")
            doi = article.get("doi", "")
            if (pmid and str(pmid) == source_article_input) or (doi and doi == source_article_input):
                source_article_id = article.get("article_id")
                break

        # 見つからない場合は警告
        if source_article_id is None:
            st.warning(f"⚠️ 指定された論文が見つかりません: {source_article_input}")

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

    # 出版年フィルタ
    if start_year is not None or end_year is not None:
        filtered_articles = [
            a for a in filtered_articles
            if a.get("pub_year") is not None and (
                (start_year is None or a.get("pub_year") >= start_year) and
                (end_year is None or a.get("pub_year") <= end_year)
            )
        ]

    # 被引用数フィルタ
    if min_citation is not None or max_citation is not None:
        filtered_articles = [
            a for a in filtered_articles
            if a.get("citation_count") is not None and (
                (min_citation is None or a.get("citation_count") >= min_citation) and
                (max_citation is None or a.get("citation_count") <= max_citation)
            )
        ]

    # 発見元論文フィルタ
    if source_article_id is not None:
        filtered_articles = [
            a for a in filtered_articles
            if source_article_id in a.get("mentioned_by", [])
        ]

    # 確認済みフィルタ
    if checked_filter == "確認済みのみ":
        filtered_articles = [a for a in filtered_articles if a.get("checked", False)]
    elif checked_filter == "未確認のみ":
        filtered_articles = [a for a in filtered_articles if not a.get("checked", False)]

    # ページネーション設定
    ITEMS_PER_PAGE = 100
    total_articles = len(filtered_articles)
    total_pages = (total_articles + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE  # 切り上げ

    # ページ番号をセッションステートで管理
    if 'project_page' not in st.session_state:
        st.session_state.project_page = 1

    # 選択された論文が存在する場合、そのページに自動的にジャンプ
    if 'selected_article_id' in st.session_state:
        selected_id = st.session_state.selected_article_id
        for idx, article in enumerate(filtered_articles):
            if article.get("article_id") == selected_id:
                # 該当するページ番号を計算
                target_page = (idx // ITEMS_PER_PAGE) + 1
                if target_page != st.session_state.project_page:
                    st.session_state.project_page = target_page
                break

    # ページ番号が範囲外の場合は修正
    if st.session_state.project_page > total_pages and total_pages > 0:
        st.session_state.project_page = total_pages
    elif st.session_state.project_page < 1:
        st.session_state.project_page = 1

    # ページトップアンカー（statsの上に配置）
    st.markdown('<div id="article-list-top"></div>', unsafe_allow_html=True)

    st.info(f"表示件数: {len(filtered_articles)} / {len(articles)}")

    # 可視化（ネットワークグラフ & セマンティック・マップ）
    if filtered_articles:
        st.subheader("📊 論文の可視化")

        tab1, tab2, tab3 = st.tabs(["🕸️ ネットワークグラフ（被発見数）", "📊 ネットワークグラフ（被引用数）", "🔮 セマンティック・マップ"])

        with tab1:
            st.info(
                "**スコア別の表示（色で区別）：**\n"
                "🔴 81-100点（濃い赤） | 🟠 61-80点（オレンジ） | 🟡 41-60点（黄色） | 🔵 21-40点（薄い青） | 🔵 1-20点（濃い青）\n\n"
                "矢印 = 引用関係（親論文 → 子論文）\n\n"
                "**💡 ノードをダブルクリックで選択できます**"
            )

            # セッションステートでグラフ生成状態を管理
            if 'show_network_graph' not in st.session_state:
                st.session_state.show_network_graph = False
            if 'network_graph_articles' not in st.session_state:
                st.session_state.network_graph_articles = []
            if 'network_graph_elements' not in st.session_state:
                st.session_state.network_graph_elements = None

            # 論文検索機能
            search_id = st.text_input(
                "🔍 論文を検索（PMID または DOI）",
                value="",
                placeholder="例: 12345678 または 10.1038/...",
                key="network_graph_search",
                help="指定した論文をグラフ上で強調表示します"
            )

            # グラフ生成ボタンとキャッシュクリアボタンを横並びに配置
            button_label = "🔄 グラフを更新" if st.session_state.show_network_graph else "🕸️ ネットワークグラフを生成"

            col1, col2 = st.columns(2)
            with col1:
                if st.button(button_label, type="primary", use_container_width=True, key="generate_network_graph_btn"):
                    # ボタン押下時のみグラフを生成
                    with st.spinner("ネットワークグラフを生成中..."):
                        st.session_state.network_graph_articles = filtered_articles.copy()
                        st.session_state.network_graph_elements = generate_network_graph(st.session_state.network_graph_articles, highlight_id=search_id.strip())
                    st.session_state.show_network_graph = True

            with col2:
                if st.button("🗑️ キャッシュクリア", use_container_width=True, help="グラフのキャッシュをクリアしてメモリを解放します", key="clear_cache_tab1"):
                    # クリアするセッションステートのキー
                    keys_to_clear = [
                        'show_network_graph', 'network_graph_articles', 'network_graph_elements', 'last_network_graph_selection',
                        'show_citation_graph', 'citation_graph_articles', 'citation_graph_elements', 'last_citation_graph_selection',
                        'show_semantic_map', 'semantic_map_articles', 'last_semantic_map_selection',
                        'show_results_network_graph', 'results_network_graph_articles', 'results_network_graph_elements',
                        'selected_article_id'
                    ]
                    for key in keys_to_clear:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.success(f"✅ キャッシュをクリアしました")
                    st.rerun()

            # グラフが生成済みの場合のみ表示
            if st.session_state.show_network_graph and st.session_state.network_graph_elements is not None:
                try:
                    # キャッシュされた要素を使用（再生成しない）
                    elements = st.session_state.network_graph_elements

                    # NodeStyle と EdgeStyle を定義（5段階 + ハイライト）
                    # アイコンパラメータを省略して色のみで表現
                    node_styles = [
                        NodeStyle("HIGHLIGHT", "#00FF00", "name"),  # ハイライト: 明るい緑
                        NodeStyle("EXCELLENT", "#FF2D2D", "name"),  # 81-100: 濃い赤
                        NodeStyle("GOOD", "#FF8C42", "name"),  # 61-80: オレンジ
                        NodeStyle("MODERATE", "#FFD700", "name"),  # 41-60: 黄色
                        NodeStyle("FAIR", "#87CEEB", "name"),  # 21-40: 薄い青
                        NodeStyle("POOR", "#4169E1", "name"),  # 1-20: 濃い青
                    ]
                    edge_styles = [
                        EdgeStyle("CITES", directed=True, caption="label")
                    ]

                    # グラフを表示
                    # layout は辞書形式で指定する必要がある
                    # cose レイアウトのパラメータでノード間のスペースを調整
                    layout_config = {
                        "name": "cose",
                        "animationDuration": 1000,
                        "nodeRepulsion": 20000,  # ノード間の反発力（大きいほど離れる）
                        "idealEdgeLength": 150,  # 理想的なエッジの長さ
                        "nodeOverlap": 30,  # ノードの重なりを避けるための余白
                        "gravity": 40,  # 中心への引力（小さいほど広がる）
                        "numIter": 1000,  # 最適化の反復回数
                    }

                    event = st_link_analysis(
                        elements,
                        layout=layout_config,  # force-directed layout（辞書形式）
                        node_styles=node_styles,
                        edge_styles=edge_styles,
                        enable_node_actions=True,  # ノードアクションを有効化
                        key="network_graph"
                    )

                    # イベントの保存処理（最重要！）
                    # ダブルクリックで expand されると event['data']['node_ids'] にIDが入る
                    # 無限ループを防ぐため、前回処理したIDを記録
                    if 'last_network_graph_selection' not in st.session_state:
                        st.session_state.last_network_graph_selection = None

                    if event and "data" in event and "node_ids" in event["data"] and len(event["data"]["node_ids"]) > 0:
                        clicked_id = event["data"]["node_ids"][0]

                        # 前回と同じ選択なら処理をスキップ（無限ループ防止）
                        if st.session_state.last_network_graph_selection != clicked_id:
                            # Session Stateに保存して、該当論文のページに移動
                            st.session_state.selected_article_id = clicked_id
                            st.session_state.last_network_graph_selection = clicked_id

                            # 選択された論文が含まれるページに移動
                            global_index = next((i for i, a in enumerate(filtered_articles) if a["article_id"] == clicked_id), 0)
                            target_page = (global_index // 20) + 1  # 20件/ページ（ITEMS_PER_PAGE）
                            st.session_state.project_page = target_page

                            # ページを再描画して論文詳細へジャンプ
                            st.rerun()
                    else:
                        # イベントがない場合、フラグをリセット
                        st.session_state.last_network_graph_selection = None

                    # 選択されたノードを論文リストで表示（直接ジャンプ）
                    # Session Stateは既に上で更新済み
                    st.info("💡 ノードを**ダブルクリック**すると、論文リストの詳細にジャンプします")

                except Exception as e:
                    st.error(f"ネットワークグラフの生成に失敗しました: {e}")
                    import traceback
                    st.code(traceback.format_exc())
            else:
                st.info("👆 上のボタンを押すとネットワークグラフが生成されます。\n\n⚠️ **注意**: 論文数が増えると生成に時間がかかります（1000件以上で数十秒〜数分）。")

        with tab2:
            st.info(
                "**スコア別の表示（色で区別）：**\n"
                "🔴 81-100点（濃い赤） | 🟠 61-80点（オレンジ） | 🟡 41-60点（黄色） | 🔵 21-40点（薄い青） | 🔵 1-20点（濃い青）\n\n"
                "矢印 = 引用関係（親論文 → 子論文）\n\n"
                "**ノードの大きさ = OpenAlexの被引用数**（学術的影響力を表す）\n\n"
                "**💡 ノードをダブルクリックで選択できます**"
            )

            # セッションステートでグラフ生成状態を管理
            if 'show_citation_graph' not in st.session_state:
                st.session_state.show_citation_graph = False
            if 'citation_graph_articles' not in st.session_state:
                st.session_state.citation_graph_articles = []
            if 'citation_graph_elements' not in st.session_state:
                st.session_state.citation_graph_elements = None

            # 論文検索機能
            search_id_citation = st.text_input(
                "🔍 論文を検索（PMID または DOI）",
                value="",
                placeholder="例: 12345678 または 10.1038/...",
                key="citation_graph_search",
                help="指定した論文をグラフ上で強調表示します"
            )

            # グラフ生成ボタンとキャッシュクリアボタンを横並びに配置
            button_label = "🔄 グラフを更新" if st.session_state.show_citation_graph else "📊 被引用数ネットワークグラフを生成"

            col1, col2 = st.columns(2)
            with col1:
                if st.button(button_label, type="primary", use_container_width=True, key="generate_citation_graph_btn"):
                    # ボタン押下時のみグラフを生成
                    with st.spinner("被引用数ネットワークグラフを生成中..."):
                        st.session_state.citation_graph_articles = filtered_articles.copy()
                        st.session_state.citation_graph_elements = generate_citation_network_graph(st.session_state.citation_graph_articles, highlight_id=search_id_citation.strip())
                    st.session_state.show_citation_graph = True

            with col2:
                if st.button("🗑️ キャッシュクリア", use_container_width=True, help="グラフのキャッシュをクリアしてメモリを解放します", key="clear_cache_tab2"):
                    # クリアするセッションステートのキー
                    keys_to_clear = [
                        'show_network_graph', 'network_graph_articles', 'network_graph_elements', 'last_network_graph_selection',
                        'show_citation_graph', 'citation_graph_articles', 'citation_graph_elements', 'last_citation_graph_selection',
                        'show_semantic_map', 'semantic_map_articles', 'last_semantic_map_selection',
                        'show_results_network_graph', 'results_network_graph_articles', 'results_network_graph_elements',
                        'selected_article_id'
                    ]
                    for key in keys_to_clear:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.success(f"✅ キャッシュをクリアしました")
                    st.rerun()

            # グラフが生成済みの場合のみ表示
            if st.session_state.show_citation_graph and st.session_state.citation_graph_elements is not None:
                try:
                    # キャッシュされた要素を使用（再生成しない）
                    elements = st.session_state.citation_graph_elements

                    # NodeStyle と EdgeStyle を定義（5段階 + ハイライト）
                    node_styles = [
                        NodeStyle("HIGHLIGHT", "#00FF00", "name"),  # ハイライト: 明るい緑
                        NodeStyle("EXCELLENT", "#FF2D2D", "name"),  # 81-100: 濃い赤
                        NodeStyle("GOOD", "#FF8C42", "name"),  # 61-80: オレンジ
                        NodeStyle("MODERATE", "#FFD700", "name"),  # 41-60: 黄色
                        NodeStyle("FAIR", "#87CEEB", "name"),  # 21-40: 薄い青
                        NodeStyle("POOR", "#4169E1", "name"),  # 1-20: 濃い青
                    ]
                    edge_styles = [
                        EdgeStyle("CITES", directed=True, caption="label")
                    ]

                    # グラフを表示
                    layout_config = {
                        "name": "cose",
                        "animationDuration": 1000,
                        "nodeRepulsion": 20000,
                        "idealEdgeLength": 150,
                        "nodeOverlap": 30,
                        "gravity": 40,
                        "numIter": 1000,
                    }

                    event = st_link_analysis(
                        elements,
                        layout=layout_config,
                        node_styles=node_styles,
                        edge_styles=edge_styles,
                        enable_node_actions=True,
                        key="citation_network_graph"
                    )

                    # イベントの保存処理
                    if 'last_citation_graph_selection' not in st.session_state:
                        st.session_state.last_citation_graph_selection = None

                    if event and "data" in event and "node_ids" in event["data"] and len(event["data"]["node_ids"]) > 0:
                        clicked_id = event["data"]["node_ids"][0]

                        if st.session_state.last_citation_graph_selection != clicked_id:
                            st.session_state.selected_article_id = clicked_id
                            st.session_state.last_citation_graph_selection = clicked_id

                            global_index = next((i for i, a in enumerate(filtered_articles) if a["article_id"] == clicked_id), 0)
                            target_page = (global_index // 20) + 1
                            st.session_state.project_page = target_page

                            st.rerun()
                    else:
                        st.session_state.last_citation_graph_selection = None

                    st.info("💡 ノードを**ダブルクリック**すると、論文リストの詳細にジャンプします")

                except Exception as e:
                    st.error(f"被引用数ネットワークグラフの生成に失敗しました: {e}")
                    import traceback
                    st.code(traceback.format_exc())
            else:
                st.info("👆 上のボタンを押すと被引用数ネットワークグラフが生成されます。\n\n⚠️ **注意**: 論文数が増えると生成に時間がかかります（1000件以上で数十秒〜数分）。")

        with tab3:
            # セマンティック・マップを表示
            generate_semantic_map(filtered_articles, api_key, project)

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
        # 選択された論文かどうかをチェック
        is_selected = (
            'selected_article_id' in st.session_state and
            st.session_state.selected_article_id == article.get("article_id")
        )

        # 選択された論文は強調表示
        title_prefix = "📌 " if is_selected else ""

        # 選択された論文にアンカーを追加
        if is_selected:
            st.markdown('<div id="selected-article"></div>', unsafe_allow_html=True)
            # JavaScriptでスクロール
            components.html("""
                <script>
                    setTimeout(function() {
                        const element = window.parent.document.getElementById('selected-article');
                        if (element) {
                            element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        }
                    }, 100);
                </script>
            """, height=0)

        with st.expander(
            f"{title_prefix}[{i}] {article.get('title', 'No Title')} "
            f"(スコア: {article.get('relevance_score', 0)})",
            expanded=(i <= 5 or is_selected)  # 最初の5件または選択された論文は展開表示
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
                    # DOIリンク（カスタマイズ可能）
                    doi_url, doi_label = build_doi_url(doi, doi_proxy_template)
                    label_text = f" {doi_label}" if doi_label else ""
                    st.markdown(f"**DOI:** [🔗 {doi}]({doi_url}){label_text}")

                # 図書館リンク（カスタマイズ可能）
                library_url = build_library_link(pmid if pmid != 'N/A' else '', doi, library_link_template)
                if library_url:
                    st.markdown(f"**📚 図書館:** [Article Linker]({library_url})")

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

                # Altmetric Score を表示（キャッシュから）
                altmetric_data = article.get('altmetric_data')

                if altmetric_data:
                    altmetric_score = altmetric_data.get('score', 0)
                    badge_url = altmetric_data.get('badge_url', '')
                    details_url = altmetric_data.get('details_url', '')

                    st.markdown(f"**Altmetric Score:** {altmetric_score}")

                    # バッジとリンクを表示
                    if badge_url and details_url:
                        st.markdown(
                            f'<a href="{details_url}" target="_blank">'
                            f'<img src="{badge_url}" alt="Altmetric Badge" style="max-width: 100px;"></a>',
                            unsafe_allow_html=True
                        )

                    # メトリクスの詳細（折りたたみ）
                    with st.expander("📊 Altmetric詳細"):
                        st.markdown(f"**Mendeley Readers:** {altmetric_data.get('readers_count', 0)}")
                        st.markdown(f"**Twitter Mentions:** {altmetric_data.get('cited_by_tweeters_count', 0)}")
                        st.markdown(f"**Blog Posts:** {altmetric_data.get('cited_by_posts_count', 0)}")
                        st.markdown(f"**Facebook Posts:** {altmetric_data.get('cited_by_fbwalls_count', 0)}")
                        st.markdown(f"**News Outlets:** {altmetric_data.get('cited_by_msm_count', 0)}")

                    # 再読み込みボタン
                    if st.button(
                        "🔄 Altmetricを再取得",
                        key=f"reload_altmetric_{article_id}_{i}",
                        type="secondary",
                        help="最新のAltmetricメトリクスを取得します"
                    ):
                        altmetric_api = AltmetricAPI()
                        with st.spinner("Altmetricメトリクスを取得中..."):
                            try:
                                new_metrics = None
                                if doi and doi != 'N/A':
                                    new_metrics = altmetric_api.get_metrics_by_doi(doi)
                                elif pmid and pmid != 'N/A':
                                    new_metrics = altmetric_api.get_metrics_by_pmid(pmid)

                                if new_metrics:
                                    article['altmetric_score'] = new_metrics.get('score', 0)
                                    article['altmetric_data'] = new_metrics
                                    project.articles[article_id] = article
                                    project.save()
                                    st.success(f"Altmetric Scoreを更新しました: {new_metrics.get('score', 0)}")
                                    st.rerun()
                                else:
                                    st.warning("Altmetricデータが見つかりませんでした")
                            except Exception as e:
                                st.error(f"エラーが発生しました: {e}")
                elif altmetric_data is None:
                    # メトリクスがない場合は取得ボタンを表示
                    if st.button(
                        "📊 Altmetricを取得",
                        key=f"fetch_altmetric_{article_id}_{i}",
                        type="secondary",
                        help="Altmetricメトリクスを取得します"
                    ):
                        altmetric_api = AltmetricAPI()
                        with st.spinner("Altmetricメトリクスを取得中..."):
                            try:
                                new_metrics = None
                                if doi and doi != 'N/A':
                                    new_metrics = altmetric_api.get_metrics_by_doi(doi)
                                elif pmid and pmid != 'N/A':
                                    new_metrics = altmetric_api.get_metrics_by_pmid(pmid)

                                if new_metrics:
                                    article['altmetric_score'] = new_metrics.get('score', 0)
                                    article['altmetric_data'] = new_metrics
                                    project.articles[article_id] = article
                                    project.save()
                                    st.success(f"Altmetric Scoreを取得しました: {new_metrics.get('score', 0)}")
                                    st.rerun()
                                else:
                                    st.info("この論文のAltmetricデータは見つかりませんでした")
                            except Exception as e:
                                st.error(f"エラーが発生しました: {e}")

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
                    # source_typeの日本語変換
                    source_type_map = {
                        "similar": "類似論文",
                        "cited_by": "引用論文",
                        "references": "引用文献"
                    }
                    source_type_jp = source_type_map.get(source_type, "関連論文")

                    # source_pmidがDOI形式かPMID形式か判定
                    if source_pmid.startswith("10."):
                        st.markdown(f"**発見元:** DOI {source_pmid} の{source_type_jp}")
                    else:
                        st.markdown(f"**発見元:** PMID {source_pmid} の{source_type_jp}")
                elif source_type == "起点論文":
                    st.markdown(f"**発見元:** {source_type}")

                # 被発見数を表示（何件の論文から発見されたか）
                mentioned_by = article.get('mentioned_by', [])
                if isinstance(mentioned_by, list) and len(mentioned_by) > 0:
                    st.markdown(f"**被発見数:** {len(mentioned_by)}件の論文から発見")

                # 被引用数を表示（OpenAlexから取得）
                citation_count = article.get('citation_count')
                if citation_count is not None:
                    st.markdown(f"**被引用数:** {citation_count}件（OpenAlex）")

                # グラフで探すボタン
                search_id_for_graph = str(pmid) if pmid else doi if doi else None
                if search_id_for_graph:
                    if st.button(
                        "📍 グラフで探す",
                        key=f"locate_in_graph_project_{article_id}_{i}",
                        type="secondary",
                        use_container_width=True,
                        help="可視化タブでこの論文を強調表示します"
                    ):
                        # 各グラフの検索フィールドに値を設定
                        st.session_state.network_graph_search = search_id_for_graph
                        st.session_state.citation_graph_search = search_id_for_graph
                        st.session_state.semantic_map_search = search_id_for_graph
                        st.session_state.semantic_map_search_id = search_id_for_graph

                        # 既にグラフが生成されている場合は再生成
                        if st.session_state.get('show_network_graph', False):
                            st.session_state.network_graph_elements = generate_network_graph(
                                st.session_state.network_graph_articles,
                                highlight_id=search_id_for_graph
                            )
                        if st.session_state.get('show_citation_graph', False):
                            st.session_state.citation_graph_elements = generate_citation_network_graph(
                                st.session_state.citation_graph_articles,
                                highlight_id=search_id_for_graph
                            )

                        st.success(f"✅ 可視化タブでこの論文が強調表示されます。上の「📊 論文の可視化」タブをご確認ください。")
                        st.info(f"🔍 検索ID: {search_id_for_graph}")

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

            # 確認済みチェックボックス
            checked = st.checkbox(
                "✅ 確認済み",
                value=article.get('checked', False),
                key=f"checked_{article_id}_{i}",
                help="この論文を確認済みとしてマークします"
            )

            # チェック状態が変更された場合は保存
            if checked != article.get('checked', False):
                article['checked'] = checked
                project.articles[article_id] = article
                project.save()

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

            st.divider()

            # ボタン群
            col_btn1, col_btn2 = st.columns(2)

            with col_btn1:
                # PMIDまたはDOIがあれば検索可能
                can_search = pmid is not None or doi is not None
                start_identifier = pmid if pmid else doi
                button_help = "この論文を起点として関連論文を探索します" if can_search else "PMIDまたはDOIが必要です"

                if st.button(
                    "🔍 この論文を起点に検索",
                    key=f"search_from_{article_id}_{i}",
                    type="primary",
                    use_container_width=True,
                    disabled=not can_search,
                    help=button_help
                ):
                    # この論文を起点に検索を開始
                    identifier_type = "PMID" if pmid else "DOI"
                    st.info(f"{identifier_type} {start_identifier} を起点に検索を開始します...")
                    run_search(
                        api_key=api_key,
                        gemini_model=gemini_model,
                        start_pmid=start_identifier,
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

            # ページトップへ戻るボタン
            st.markdown(
                '<div style="text-align: right; margin-top: 10px;">'
                '<a href="#article-list-top" style="text-decoration: none;">'
                '<button style="background-color: #4A90E2; color: white; border: none; '
                'padding: 10px 20px; border-radius: 6px; cursor: pointer; font-size: 14px; '
                'font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">'
                '↑ ページトップへ</button></a></div>',
                unsafe_allow_html=True
            )


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


def display_results(result: dict, project=None, doi_proxy_template: str = '', library_link_template: str = ''):
    """検索結果を表示

    Args:
        result: 検索結果の辞書
        project: プロジェクト（オプション）
        doi_proxy_template: DOIプロキシURLテンプレート
        library_link_template: 図書館リンクURLテンプレート
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

        # 確認済みフィルタ（プロジェクトがある場合のみ）
        if project:
            checked_filter_results = st.radio(
                "確認済み状態",
                options=["すべて", "確認済みのみ", "未確認のみ"],
                index=0,
                key="results_filter_checked",
                help="論文の確認済み状態でフィルタリングします"
            )
        else:
            checked_filter_results = "すべて"

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

    # 出版年フィルタ（2列目の行）
    col6, col7 = st.columns(2)

    with col6:
        start_year_input_results = st.text_input(
            "出版年（開始）",
            value="",
            placeholder="指定なし",
            key="results_filter_start_year",
            help="この年以降に出版された論文を表示（空白の場合は指定なし）"
        )
        # 入力値の検証と変換
        if start_year_input_results.strip():
            try:
                start_year_results = int(start_year_input_results.strip())
            except ValueError:
                st.error("開始年は数字で入力してください")
                start_year_results = None
        else:
            start_year_results = None

    with col7:
        end_year_input_results = st.text_input(
            "出版年（終了）",
            value="",
            placeholder="指定なし",
            key="results_filter_end_year",
            help="この年以前に出版された論文を表示（空白の場合は指定なし）"
        )
        # 入力値の検証と変換
        if end_year_input_results.strip():
            try:
                end_year_results = int(end_year_input_results.strip())
            except ValueError:
                st.error("終了年は数字で入力してください")
                end_year_results = None
        else:
            end_year_results = None

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

    # 出版年フィルタ
    if start_year_results is not None or end_year_results is not None:
        filtered_articles = [
            a for a in filtered_articles
            if a.get("pub_year") is not None and (
                (start_year_results is None or a.get("pub_year") >= start_year_results) and
                (end_year_results is None or a.get("pub_year") <= end_year_results)
            )
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

    # ページトップアンカー（statsの上に配置）
    st.markdown('<div id="article-list-top-results"></div>', unsafe_allow_html=True)

    st.info(f"表示件数: {len(filtered_articles)} / {len(articles)}")

    # ネットワークグラフ表示
    if filtered_articles:
        st.subheader("📊 論文の可視化")

        st.info(
            "**スコア別の表示（色で区別）：**\n"
            "🔴 81-100点（濃い赤） | 🟠 61-80点（オレンジ） | 🟡 41-60点（黄色） | 🔵 21-40点（薄い青） | 🔵 1-20点（濃い青）\n\n"
            "矢印 = 引用関係（親論文 → 子論文）\n\n"
            "**💡 ノードをダブルクリックで選択できます**"
        )

        # セッションステートでグラフ生成状態を管理
        if 'show_results_network_graph' not in st.session_state:
            st.session_state.show_results_network_graph = False
        if 'results_network_graph_articles' not in st.session_state:
            st.session_state.results_network_graph_articles = []
        if 'results_network_graph_elements' not in st.session_state:
            st.session_state.results_network_graph_elements = None

        # グラフ生成ボタン
        button_label = "🔄 グラフを更新" if st.session_state.show_results_network_graph else "🕸️ ネットワークグラフを生成"

        if st.button(button_label, type="primary", use_container_width=True, key="generate_results_network_graph_btn"):
            # ボタン押下時のみグラフを生成
            with st.spinner("ネットワークグラフを生成中... しばらくお待ちください"):
                st.session_state.results_network_graph_articles = filtered_articles.copy()
                st.session_state.results_network_graph_elements = generate_network_graph(st.session_state.results_network_graph_articles)
            st.session_state.show_results_network_graph = True

        # グラフが生成済みの場合のみ表示
        if st.session_state.show_results_network_graph and st.session_state.results_network_graph_elements is not None:
            try:
                # キャッシュされた要素を使用（再生成しない）
                elements = st.session_state.results_network_graph_elements

                # NodeStyle と EdgeStyle を定義（5段階）
                node_styles = [
                    NodeStyle("EXCELLENT", "#FF2D2D", "name"),  # 81-100: 濃い赤
                    NodeStyle("GOOD", "#FF8C42", "name"),  # 61-80: オレンジ
                    NodeStyle("MODERATE", "#FFD700", "name"),  # 41-60: 黄色
                    NodeStyle("FAIR", "#87CEEB", "name"),  # 21-40: 薄い青
                    NodeStyle("POOR", "#4169E1", "name"),  # 1-20: 濃い青
                ]
                edge_styles = [
                    EdgeStyle("CITES", directed=True, caption="label")
                ]

                # レイアウト設定
                layout_config = {
                    "name": "cose",
                    "animationDuration": 1000,
                    "nodeRepulsion": 20000,
                    "idealEdgeLength": 150,
                    "nodeOverlap": 30,
                    "gravity": 40,
                    "numIter": 1000,
                }

                event = st_link_analysis(
                    elements,
                    layout=layout_config,
                    node_styles=node_styles,
                    edge_styles=edge_styles,
                    enable_node_actions=True,
                    key="results_network_graph"
                )

                # 選択された論文を論文リストで表示（直接ジャンプ）
                # 無限ループを防ぐため、前回処理したIDを記録
                if 'last_results_network_graph_selection' not in st.session_state:
                    st.session_state.last_results_network_graph_selection = None

                if event and "data" in event and "node_ids" in event["data"] and len(event["data"]["node_ids"]) > 0:
                    clicked_id = event["data"]["node_ids"][0]

                    # 前回と同じ選択なら処理をスキップ（無限ループ防止）
                    if st.session_state.last_results_network_graph_selection != clicked_id:
                        # Session Stateに保存（検索結果画面では selected_article_id を使用）
                        st.session_state.selected_article_id = clicked_id
                        st.session_state.last_results_network_graph_selection = clicked_id

                        # 選択された論文が含まれるページに移動
                        global_index = next((i for i, a in enumerate(filtered_articles) if a["article_id"] == clicked_id), 0)
                        target_page = (global_index // 20) + 1  # 20件/ページ
                        st.session_state.results_page = target_page

                        # ページを再描画して論文詳細へジャンプ
                        st.rerun()
                else:
                    # イベントがない場合、フラグをリセット
                    st.session_state.last_results_network_graph_selection = None

                st.info("💡 ノードを**ダブルクリック**すると、論文リストの詳細にジャンプします")

            except Exception as e:
                st.error(f"ネットワークグラフの生成に失敗しました: {e}")
                import traceback
                st.code(traceback.format_exc())
        else:
            st.info("👆 上のボタンを押すとネットワークグラフが生成されます。\n\n⚠️ **注意**: 論文数が増えると生成に時間がかかります（1000件以上で数十秒〜数分）。")

    st.divider()

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
        # 選択された論文かどうかをチェック
        is_selected = (
            'selected_article_id' in st.session_state and
            st.session_state.selected_article_id == article.get("article_id")
        )

        # 選択された論文は強調表示
        title_prefix = "📌 " if is_selected else ""

        # 選択された論文にアンカーを追加
        if is_selected:
            st.markdown('<div id="selected-article"></div>', unsafe_allow_html=True)
            # JavaScriptでスクロール
            components.html("""
                <script>
                    setTimeout(function() {
                        const element = window.parent.document.getElementById('selected-article');
                        if (element) {
                            element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        }
                    }, 100);
                </script>
            """, height=0)

        with st.expander(
            f"{title_prefix}[{i}] {article.get('title', 'No Title')} "
            f"(スコア: {article.get('relevance_score', 0)})",
            expanded=(i <= 5 or is_selected)  # 最初の5件または選択された論文は展開表示
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
                    # DOIリンク（カスタマイズ可能）
                    doi_url, doi_label = build_doi_url(doi, doi_proxy_template)
                    label_text = f" {doi_label}" if doi_label else ""
                    st.markdown(f"**DOI:** [🔗 {doi}]({doi_url}){label_text}")

                # 図書館リンク（カスタマイズ可能）
                library_url = build_library_link(pmid if pmid != 'N/A' else '', doi, library_link_template)
                if library_url:
                    st.markdown(f"**📚 図書館:** [Article Linker]({library_url})")

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

                # Altmetric Score を表示（キャッシュから）
                altmetric_data = article.get('altmetric_data')

                if altmetric_data:
                    altmetric_score = altmetric_data.get('score', 0)
                    badge_url = altmetric_data.get('badge_url', '')
                    details_url = altmetric_data.get('details_url', '')

                    st.markdown(f"**Altmetric Score:** {altmetric_score}")

                    # バッジとリンクを表示
                    if badge_url and details_url:
                        st.markdown(
                            f'<a href="{details_url}" target="_blank">'
                            f'<img src="{badge_url}" alt="Altmetric Badge" style="max-width: 100px;"></a>',
                            unsafe_allow_html=True
                        )

                    # メトリクスの詳細（折りたたみ）
                    with st.expander("📊 Altmetric詳細"):
                        st.markdown(f"**Mendeley Readers:** {altmetric_data.get('readers_count', 0)}")
                        st.markdown(f"**Twitter Mentions:** {altmetric_data.get('cited_by_tweeters_count', 0)}")
                        st.markdown(f"**Blog Posts:** {altmetric_data.get('cited_by_posts_count', 0)}")
                        st.markdown(f"**Facebook Posts:** {altmetric_data.get('cited_by_fbwalls_count', 0)}")
                        st.markdown(f"**News Outlets:** {altmetric_data.get('cited_by_msm_count', 0)}")

                    # 再読み込みボタン（プロジェクトがある場合のみ）
                    if project:
                        if st.button(
                            "🔄 Altmetricを再取得",
                            key=f"reload_altmetric_result_{article_id}_{i}",
                            type="secondary",
                            help="最新のAltmetricメトリクスを取得します"
                        ):
                            altmetric_api = AltmetricAPI()
                            with st.spinner("Altmetricメトリクスを取得中..."):
                                try:
                                    new_metrics = None
                                    if doi and doi != 'N/A':
                                        new_metrics = altmetric_api.get_metrics_by_doi(doi)
                                    elif pmid and pmid != 'N/A':
                                        new_metrics = altmetric_api.get_metrics_by_pmid(pmid)

                                    if new_metrics:
                                        # プロジェクトから最新のarticleを取得
                                        project_article = project.get_article_by_id(article_id)
                                        if project_article:
                                            project_article['altmetric_score'] = new_metrics.get('score', 0)
                                            project_article['altmetric_data'] = new_metrics
                                            project.articles[article_id] = project_article
                                            project.save()
                                            st.success(f"Altmetric Scoreを更新しました: {new_metrics.get('score', 0)}")
                                            st.rerun()
                                        else:
                                            st.warning("プロジェクトに論文が見つかりませんでした")
                                    else:
                                        st.warning("Altmetricデータが見つかりませんでした")
                                except Exception as e:
                                    st.error(f"エラーが発生しました: {e}")
                elif altmetric_data is None and project:
                    # メトリクスがない場合は取得ボタンを表示（プロジェクトがある場合のみ）
                    if st.button(
                        "📊 Altmetricを取得",
                        key=f"fetch_altmetric_result_{article_id}_{i}",
                        type="secondary",
                        help="Altmetricメトリクスを取得します"
                    ):
                        altmetric_api = AltmetricAPI()
                        with st.spinner("Altmetricメトリクスを取得中..."):
                            try:
                                new_metrics = None
                                if doi and doi != 'N/A':
                                    new_metrics = altmetric_api.get_metrics_by_doi(doi)
                                elif pmid and pmid != 'N/A':
                                    new_metrics = altmetric_api.get_metrics_by_pmid(pmid)

                                if new_metrics:
                                    # プロジェクトから最新のarticleを取得
                                    project_article = project.get_article_by_id(article_id)
                                    if project_article:
                                        project_article['altmetric_score'] = new_metrics.get('score', 0)
                                        project_article['altmetric_data'] = new_metrics
                                        project.articles[article_id] = project_article
                                        project.save()
                                        st.success(f"Altmetric Scoreを取得しました: {new_metrics.get('score', 0)}")
                                        st.rerun()
                                    else:
                                        st.warning("プロジェクトに論文が見つかりませんでした")
                                else:
                                    st.info("この論文のAltmetricデータは見つかりませんでした")
                            except Exception as e:
                                st.error(f"エラーが発生しました: {e}")

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
                    # source_typeの日本語変換
                    source_type_map = {
                        "similar": "類似論文",
                        "cited_by": "引用論文",
                        "references": "引用文献"
                    }
                    source_type_jp = source_type_map.get(source_type, "関連論文")

                    # source_pmidがDOI形式かPMID形式か判定
                    if source_pmid.startswith("10."):
                        st.markdown(f"**発見元:** DOI {source_pmid} の{source_type_jp}")
                    else:
                        st.markdown(f"**発見元:** PMID {source_pmid} の{source_type_jp}")
                elif source_type == "起点論文":
                    st.markdown(f"**発見元:** {source_type}")

                # 被発見数を表示（何件の論文から発見されたか）
                mentioned_by = article.get('mentioned_by', [])
                if isinstance(mentioned_by, list) and len(mentioned_by) > 0:
                    st.markdown(f"**被発見数:** {len(mentioned_by)}件の論文から発見")

                # 被引用数を表示（OpenAlexから取得）
                citation_count = article.get('citation_count')
                if citation_count is not None:
                    st.markdown(f"**被引用数:** {citation_count}件（OpenAlex）")

                # グラフで探すボタン
                search_id_for_graph = str(pmid) if pmid else doi if doi else None
                if search_id_for_graph:
                    if st.button(
                        "📍 グラフで探す",
                        key=f"locate_in_graph_search_{article_id}_{i}",
                        type="secondary",
                        use_container_width=True,
                        help="可視化タブでこの論文を強調表示します"
                    ):
                        # 各グラフの検索フィールドに値を設定
                        st.session_state.network_graph_search = search_id_for_graph
                        st.session_state.citation_graph_search = search_id_for_graph
                        st.session_state.semantic_map_search = search_id_for_graph
                        st.session_state.semantic_map_search_id = search_id_for_graph

                        # 既にグラフが生成されている場合は再生成
                        if st.session_state.get('show_network_graph', False):
                            st.session_state.network_graph_elements = generate_network_graph(
                                st.session_state.network_graph_articles,
                                highlight_id=search_id_for_graph
                            )
                        if st.session_state.get('show_citation_graph', False):
                            st.session_state.citation_graph_elements = generate_citation_network_graph(
                                st.session_state.citation_graph_articles,
                                highlight_id=search_id_for_graph
                            )

                        st.success(f"✅ 可視化タブでこの論文が強調表示されます。上の「📊 論文の可視化」タブをご確認ください。")
                        st.info(f"🔍 検索ID: {search_id_for_graph}")

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

            # 確認済みチェックボックス・メモ機能（プロジェクトがある場合のみ）
            if project:
                # プロジェクトから最新の論文データを取得
                project_article = project.get_article_by_id(article_id)

                if project_article:
                    # 確認済みチェックボックス
                    checked = st.checkbox(
                        "✅ 確認済み",
                        value=project_article.get('checked', False),
                        key=f"checked_result_{article_id}_{i}",
                        help="この論文を確認済みとしてマークします"
                    )

                    # チェック状態が変更された場合は保存
                    if checked != project_article.get('checked', False):
                        project_article['checked'] = checked
                        project.articles[article_id] = project_article
                        project.save()

                st.markdown("**📝 メモ・コメント:**")

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
                    else:
                        st.warning("この論文はプロジェクトに保存されていません")

            # ページトップへ戻るボタン
            st.markdown(
                '<div style="text-align: right; margin-top: 10px;">'
                '<a href="#article-list-top-results" style="text-decoration: none;">'
                '<button style="background-color: #4A90E2; color: white; border: none; '
                'padding: 10px 20px; border-radius: 6px; cursor: pointer; font-size: 14px; '
                'font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">'
                '↑ ページトップへ</button></a></div>',
                unsafe_allow_html=True
            )

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

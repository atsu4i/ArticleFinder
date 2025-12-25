"""
論文のアブストラクトをベクトル化するモジュール
Gemini Embeddings API を使用
"""

import os
import time
from typing import List, Dict, Optional, Callable
import google.generativeai as genai


class EmbeddingManager:
    """論文のアブストラクトをベクトル化するクラス"""

    def __init__(self, api_key: Optional[str] = None, model: str = "models/embedding-001"):
        """
        Args:
            api_key: Gemini API Key（省略時は環境変数GEMINI_API_KEYから取得）
            model: Embedding モデル名（デフォルト: embedding-001）
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません")

        genai.configure(api_key=self.api_key)
        self.model = model

    def embed_articles_batch(
        self,
        articles: List[Dict],
        batch_size: int = 100,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[Dict]:
        """
        論文リストのアブストラクトをバッチでベクトル化

        Args:
            articles: 論文情報のリスト
            batch_size: バッチサイズ（デフォルト: 100）
            progress_callback: 進捗コールバック関数 (message, current, total)

        Returns:
            embedding フィールドが追加された論文リスト
        """
        # 未ベクトル化の論文のみ抽出
        articles_to_embed = [
            article for article in articles
            if not article.get("embedding")
        ]

        if not articles_to_embed:
            if progress_callback:
                progress_callback("全ての論文が既にベクトル化済みです", 0, 0)
            return articles

        total_articles = len(articles_to_embed)
        total_batches = (total_articles + batch_size - 1) // batch_size

        if progress_callback:
            progress_callback(f"{total_articles}件の論文をベクトル化します", 0, total_batches)

        # バッチ処理
        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, total_articles)
            batch = articles_to_embed[start_idx:end_idx]

            if progress_callback:
                progress_callback(
                    f"Batch {batch_idx + 1}/{total_batches} を処理中...",
                    batch_idx + 1,
                    total_batches
                )

            # バッチ内の全テキストを準備
            texts = []
            for article in batch:
                # アブストラクトを取得、なければタイトルを使用
                # None対策: get()で取得した値がNoneの場合も空文字列として扱う
                abstract = (article.get("abstract") or "").strip()
                title = (article.get("title") or "").strip()

                if abstract:
                    texts.append(abstract)
                elif title:
                    texts.append(title)
                else:
                    # タイトルもない場合はダミーテキスト
                    texts.append("No content available")

            # Gemini Embeddings API 呼び出し
            try:
                result = genai.embed_content(
                    model=self.model,
                    content=texts,
                    task_type="CLUSTERING"
                )

                # 結果を各論文に保存
                embeddings = result.get("embedding", [])

                # embeddings が単一ベクトルの場合（1件のみ）と、複数ベクトルの場合で処理を分岐
                if len(batch) == 1:
                    # 1件のみの場合、embedding は単一のリスト
                    if isinstance(embeddings, list) and len(embeddings) > 0:
                        batch[0]["embedding"] = embeddings
                else:
                    # 複数件の場合、embedding はリストのリスト
                    for i, article in enumerate(batch):
                        if i < len(embeddings):
                            article["embedding"] = embeddings[i]

            except Exception as e:
                print(f"[ERROR] Batch {batch_idx + 1} のベクトル化に失敗: {e}")
                # エラー時は空のベクトルを設定
                for article in batch:
                    article["embedding"] = []

            # レート制限対策（念のため少し待つ）
            if batch_idx < total_batches - 1:
                time.sleep(0.5)

        if progress_callback:
            progress_callback(f"ベクトル化完了: {total_articles}件", total_batches, total_batches)

        return articles

    def calculate_2d_coordinates(
        self,
        articles: List[Dict],
        n_neighbors: int = 15,
        min_dist: float = 0.1,
        random_state: int = 42
    ) -> List[Dict]:
        """
        ベクトルを UMAP で 2次元座標に変換

        Args:
            articles: embedding を持つ論文リスト
            n_neighbors: UMAP の n_neighbors パラメータ
            min_dist: UMAP の min_dist パラメータ
            random_state: 乱数シード

        Returns:
            x, y 座標が追加された論文リスト
        """
        import numpy as np
        from umap import UMAP

        # embedding を持つ論文のみ抽出
        articles_with_embedding = [
            article for article in articles
            if article.get("embedding") and len(article.get("embedding", [])) > 0
        ]

        if len(articles_with_embedding) < 2:
            # 2件未満の場合は UMAP を適用できない
            return articles

        # ベクトルを numpy 配列に変換
        embeddings_array = np.array([
            article["embedding"] for article in articles_with_embedding
        ])

        # UMAP で 2次元に圧縮
        umap_model = UMAP(
            n_components=2,
            n_neighbors=min(n_neighbors, len(articles_with_embedding) - 1),
            min_dist=min_dist,
            random_state=random_state,
            metric='cosine'
        )
        coords_2d = umap_model.fit_transform(embeddings_array)

        # 座標を各論文に保存
        for i, article in enumerate(articles_with_embedding):
            article["umap_x"] = float(coords_2d[i, 0])
            article["umap_y"] = float(coords_2d[i, 1])

        return articles

"""
Gemini APIを使用した論文関連性評価モジュール
"""

import os
import re
import time
from typing import Dict, Optional
from google import genai
from google.genai import types
from dotenv import load_dotenv

# 環境変数を読み込み
load_dotenv()


class GeminiEvaluator:
    """Gemini APIを使って論文の関連性を評価するクラス"""

    # 利用可能なGeminiモデル（無料枠あり）
    # https://ai.google.dev/gemini-api/docs/pricing?hl=ja
    AVAILABLE_MODELS = [
        "gemma-4-26b-a4b-it",
        "gemma-4-31b-it",
        "gemini-2.5-flash-preview-09-2025",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]

    DEFAULT_MODEL = "gemma-4-26b-a4b-it"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        """
        Args:
            api_key: Gemini API Key（省略時は環境変数GEMINI_API_KEYを使用）
            model_name: 使用するGeminiモデル名（省略時はDEFAULT_MODELを使用）
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "Gemini API key is required. "
                "Set GEMINI_API_KEY environment variable or pass api_key parameter."
            )

        # モデル名の設定
        self.model_name = model_name or self.DEFAULT_MODEL

        # Google GenAI SDK のクライアントを生成
        self.client = genai.Client(api_key=self.api_key)

    def evaluate_relevance(
        self,
        research_theme: str,
        article_info: Dict,
        threshold: int = 60
    ) -> Dict:
        """
        論文の関連性を評価

        Args:
            research_theme: ユーザーの研究テーマ（詳細な説明）
            article_info: 論文情報（title, abstract, pub_yearなど）
            threshold: 関連性の閾値（0-100）

        Returns:
            {
                "pmid": str,
                "score": int,  # 0-100
                "is_relevant": bool,  # score >= threshold
                "reasoning": str  # 評価理由
            }
        """
        title = article_info.get("title", "")
        abstract = article_info.get("abstract", "")
        pmid = article_info.get("pmid", "")

        # タイトルもアブストラクトも空の場合はスコア0
        if not abstract and not title:
            return {
                "pmid": pmid,
                "score": 0,
                "is_relevant": False,
                "reasoning": "タイトルとアブストラクトが取得できませんでした。"
            }

        # アブストラクトが空の場合はタイトルのみで評価
        if not abstract:
            abstract = f"(アブストラクトは利用できません。タイトルのみで評価してください: {title})"

        # Geminiに評価を依頼（リトライ付き）
        prompt = self._create_evaluation_prompt(research_theme, title, abstract)

        # リトライ設定（TPM制限を考慮した待機時間）
        max_retries = 3
        retry_delays = [60, 120, 180]  # 1分、2分、3分

        for attempt in range(max_retries):
            try:
                response = self._generate_content(prompt)
                score, reasoning = self._parse_response(response.text)

                return {
                    "pmid": pmid,
                    "score": score,
                    "is_relevant": score >= threshold,
                    "reasoning": reasoning
                }

            except Exception as e:
                error_message = str(e)
                print(f"Gemini API error for PMID {pmid} (attempt {attempt + 1}/{max_retries}): {error_message}")

                # 最後のリトライでも失敗した場合
                if attempt == max_retries - 1:
                    return {
                        "pmid": pmid,
                        "score": 0,
                        "is_relevant": False,
                        "reasoning": f"評価中にエラーが発生しました（{max_retries}回リトライ後）: {error_message}"
                    }

                # TPM制限エラーまたはタイムアウトの場合は待機してリトライ
                if "quota" in error_message.lower() or "limit" in error_message.lower() or "timeout" in error_message.lower():
                    wait_time = retry_delays[attempt]
                    print(f"  → {wait_time}秒待機してリトライします...")
                    time.sleep(wait_time)
                else:
                    # その他のエラーは即座にリトライ（短い待機のみ）
                    time.sleep(5)

        # この行には到達しないはずだが、念のため
        return {
            "pmid": pmid,
            "score": 0,
            "is_relevant": False,
            "reasoning": "評価中に予期しないエラーが発生しました"
        }

    def _create_evaluation_prompt(
        self,
        research_theme: str,
        title: str,
        abstract: str
    ) -> str:
        """評価用プロンプトを作成"""
        prompt = f"""You are a medical research expert. Evaluate how well the article matches the user's research topic.

User research topic:
{research_theme}

Article title:
{title}

Abstract:
{abstract}

Scoring guide:
- Score from 0 to 100
- 100: complete match and highly important
- 70-99: strong match and useful
- 40-69: partial match
- 1-39: weak match
- 0: unrelated

Return exactly this format, with the reason written in Japanese:
スコア: [0-100の数値]
理由: [評価の根拠を1-2文で簡潔に説明]"""

        return prompt

    def _parse_response(self, response_text: str) -> tuple[int, str]:
        """
        Geminiのレスポンスからスコアと理由を抽出

        Returns:
            (score, reasoning)
        """
        # スコアを抽出
        score_match = re.search(r'スコア[:\s]*(\d+)', response_text)
        if score_match:
            score = int(score_match.group(1))
            # スコアを0-100に制限
            score = max(0, min(100, score))
        else:
            # スコアが見つからない場合は50とする
            score = 50

        # 理由を抽出
        reasoning_match = re.search(r'理由[:\s]*(.+?)(?:\n\n|\Z)', response_text, re.DOTALL)
        if reasoning_match:
            reasoning = reasoning_match.group(1).strip()
        else:
            reasoning = "評価理由を取得できませんでした。"

        return score, reasoning

    def batch_evaluate(
        self,
        research_theme: str,
        articles: list[Dict],
        threshold: int = 60,
        callback=None
    ) -> list[Dict]:
        """
        複数の論文を一括評価

        Args:
            research_theme: 研究テーマ
            articles: 論文情報のリスト
            threshold: 関連性の閾値
            callback: 進捗通知用のコールバック関数 callback(current, total, pmid)

        Returns:
            評価結果のリスト
        """
        results = []
        total = len(articles)

        for i, article in enumerate(articles, 1):
            pmid = article.get("pmid", "")

            if callback:
                callback(i, total, pmid)

            result = self.evaluate_relevance(research_theme, article, threshold)
            results.append({
                **article,
                "relevance_score": result["score"],
                "is_relevant": result["is_relevant"],
                "relevance_reasoning": result["reasoning"]
            })

        return results

    def summarize_abstract(self, abstract: str, title: str = "") -> str:
        """
        アブストラクトを日本語で要約

        Args:
            abstract: 論文のアブストラクト（英語）
            title: 論文のタイトル（オプション）

        Returns:
            日本語の要約文
        """
        if not abstract:
            return "アブストラクトが利用できません。"

        # プロンプトを作成
        prompt = f"""Summarize the following paper abstract in Japanese.
Include the key points: objective, methods, results, and conclusion.
Write about 3-4 concise Japanese sentences.

Title: {title if title else "なし"}

Abstract:
{abstract}

Return only the Japanese summary."""

        # リトライ設定
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                response = self._generate_content(prompt)
                summary = response.text.strip()
                return summary
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"要約生成エラー（リトライ {attempt + 1}/{max_retries}）: {e}")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 指数バックオフ
                else:
                    print(f"要約生成に失敗しました: {e}")
                    return f"要約生成エラー: {str(e)}"

        return "要約を生成できませんでした。"

    def _generate_content(self, prompt: str):
        """現在のモデルでテキスト生成を実行する。"""
        config = None
        if self.model_name.startswith("gemma-4-"):
            # この用途では深い推論は不要。Gemma 4 の思考を最小化して応答を速くする。
            config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="MINIMAL")
            )

        return self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config
        )

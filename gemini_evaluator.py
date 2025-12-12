"""
Gemini APIを使用した論文関連性評価モジュール
"""

import os
import re
from typing import Dict, Optional
import google.generativeai as genai
from dotenv import load_dotenv

# 環境変数を読み込み
load_dotenv()


class GeminiEvaluator:
    """Gemini APIを使って論文の関連性を評価するクラス"""

    # 利用可能なGeminiモデル（無料枠あり）
    # https://ai.google.dev/gemini-api/docs/pricing?hl=ja
    AVAILABLE_MODELS = [
        "gemma-3-27b-it",
        "gemini-2.5-flash-preview-09-2025",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]

    DEFAULT_MODEL = "gemma-3-27b-it"

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

        # Gemini APIを設定
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)

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

        # Geminiに評価を依頼
        prompt = self._create_evaluation_prompt(research_theme, title, abstract)

        try:
            response = self.model.generate_content(prompt)
            score, reasoning = self._parse_response(response.text)

            return {
                "pmid": pmid,
                "score": score,
                "is_relevant": score >= threshold,
                "reasoning": reasoning
            }

        except Exception as e:
            print(f"Gemini API error for PMID {pmid}: {e}")
            # エラー時はスコア0を返す
            return {
                "pmid": pmid,
                "score": 0,
                "is_relevant": False,
                "reasoning": f"評価中にエラーが発生しました: {str(e)}"
            }

    def _create_evaluation_prompt(
        self,
        research_theme: str,
        title: str,
        abstract: str
    ) -> str:
        """評価用プロンプトを作成"""
        prompt = f"""あなたは医学研究の専門家です。以下の論文が、ユーザーが探している論文の内容とどの程度合致しているかを評価してください。

【ユーザーが探している論文】
{research_theme}

【評価対象の論文】
タイトル: {title}

アブストラクト:
{abstract}

【評価基準】
- ユーザーが探している内容との合致度を0-100のスコアで評価してください
- 100: ユーザーが探している内容に完全に合致し、非常に重要な論文
- 70-99: ユーザーが探している内容に強く合致し、参考になる論文
- 40-69: ユーザーが探している内容に部分的に合致する論文
- 1-39: ユーザーが探している内容との合致度が低い論文
- 0: ユーザーが探している内容とは無関係な論文

【出力形式】
以下の形式で評価結果を出力してください：

スコア: [0-100の数値]
理由: [評価の根拠を1-2文で簡潔に説明]

評価を開始してください。"""

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

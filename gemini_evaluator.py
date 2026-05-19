"""
Gemini APIを使用した論文関連性評価モジュール
"""

import os
import re
import time
import threading
from typing import Dict, Optional
from google import genai
from google.genai import types
from dotenv import load_dotenv

# 環境変数を読み込み
load_dotenv()


class _GeminiRateLimiter:
    """Gemini API 呼び出しの最小間隔を強制するシンプルなレートリミッター（thread-safe）。"""

    def __init__(self, min_interval_seconds: float):
        self.min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._last_request_time = 0.0

    def acquire(self):
        """次のリクエストを送ってよくなるまでブロックする。"""
        with self._lock:
            now = time.time()
            wait = self.min_interval - (now - self._last_request_time)
            if wait > 0:
                time.sleep(wait)
            self._last_request_time = time.time()


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

    # リトライ戦略（エラー種別ごと）
    MAX_ATTEMPTS = 4  # 初回 + リトライ3回
    RETRY_DELAYS = {
        "quota":   [60, 120, 180],  # 429 / TPM 超過 — 長めに待つ
        "server":  [2, 8, 25],      # 500/INTERNAL/503/UNAVAILABLE — 短く始めて指数的に
        "default": [5, 5, 5],       # 分類できないエラー
    }

    # Gemini API リクエスト間隔の下限（秒）— RPM 15 = 4秒に1回。安全マージンで 4.5 秒
    RATE_LIMIT_MIN_INTERVAL = 4.5

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

        # 並列呼び出し時の RPM 制限を守るレートリミッター
        self._rate_limiter = _GeminiRateLimiter(self.RATE_LIMIT_MIN_INTERVAL)

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

        max_attempts = self.MAX_ATTEMPTS

        for attempt in range(max_attempts):
            try:
                response = self._generate_content(prompt)
                text = self._extract_text(response)

                # 空応答 or 日本語が含まれていない場合はリトライ
                empty = not text
                non_japanese = bool(text) and not self._contains_japanese(text)
                if empty or non_japanese:
                    reason = "応答が空" if empty else "日本語が含まれていない"
                    print(f"Gemini response invalid for PMID {pmid} (attempt {attempt + 1}/{max_attempts}): {reason}. head: {text[:80]!r}")
                    if attempt < max_attempts - 1:
                        time.sleep(2)
                        continue
                    return {
                        "pmid": pmid,
                        "score": 0,
                        "is_relevant": False,
                        "reasoning": f"評価に失敗しました（{reason}、{max_attempts}回リトライ後）。"
                    }

                score, reasoning = self._parse_response(text)

                return {
                    "pmid": pmid,
                    "score": score,
                    "is_relevant": score >= threshold,
                    "reasoning": reasoning
                }

            except Exception as e:
                error_message = str(e)
                print(f"Gemini API error for PMID {pmid} (attempt {attempt + 1}/{max_attempts}): {error_message}")

                # 最後のリトライでも失敗した場合
                if attempt == max_attempts - 1:
                    return {
                        "pmid": pmid,
                        "score": 0,
                        "is_relevant": False,
                        "reasoning": f"評価中にエラーが発生しました（{max_attempts}回リトライ後）: {error_message}"
                    }

                wait_time = self._get_retry_delay(error_message, attempt)
                print(f"  → {wait_time}秒待機してリトライします...")
                time.sleep(wait_time)

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
        prompt = f"""あなたは医学研究の専門家です。以下の論文が、ユーザーの研究テーマとどの程度合致しているかを評価してください。

研究テーマ:
{research_theme}

論文タイトル:
{title}

アブストラクト:
{abstract}

評価基準（0〜100点で採点）:
- 100点: 完全に合致し非常に重要
- 70〜99点: 強く合致し有用
- 40〜69点: 部分的に合致
- 1〜39点: 合致度が低い
- 0点: 無関係

出力は必ず以下の形式で、日本語のみで書いてください。前置きや英語の説明は不要です。
スコア: [0-100の数値]
理由: [評価の根拠を日本語で1〜2文]"""

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

        # プロンプトを作成（指示は日本語で記述して出力言語をブレさせない）
        prompt = f"""以下の論文のアブストラクトを日本語で要約してください。
目的・方法・結果・結論を含め、3〜4文の簡潔な日本語で書いてください。
出力は日本語の要約のみとし、英語や前置き、補足は書かないでください。

タイトル: {title if title else "なし"}

アブストラクト:
{abstract}

日本語要約:"""

        max_attempts = self.MAX_ATTEMPTS

        for attempt in range(max_attempts):
            try:
                response = self._generate_content(prompt)
                summary = self._extract_text(response)

                # 空応答 or 日本語が含まれていない場合はリトライ
                if not summary:
                    print(f"要約が空応答（リトライ {attempt + 1}/{max_attempts}）")
                elif not self._contains_japanese(summary):
                    print(f"要約に日本語が含まれていない（リトライ {attempt + 1}/{max_attempts}）: {summary[:80]!r}")
                else:
                    return summary

                if attempt < max_attempts - 1:
                    time.sleep(2)
                else:
                    return "要約生成に失敗しました（応答が空、または日本語ではありません）。"

            except Exception as e:
                error_message = str(e)
                if attempt < max_attempts - 1:
                    wait_time = self._get_retry_delay(error_message, attempt)
                    print(f"要約生成エラー（リトライ {attempt + 1}/{max_attempts}）: {error_message} → {wait_time}秒待機")
                    time.sleep(wait_time)
                else:
                    print(f"要約生成に失敗しました: {error_message}")
                    return f"要約生成エラー: {error_message}"

        return "要約を生成できませんでした。"

    def _generate_content(self, prompt: str):
        """現在のモデルでテキスト生成を実行する。並列化時は内部でレート制限される。"""
        config = None
        if self.model_name.startswith("gemma-4-"):
            # この用途では深い推論は不要。Gemma 4 の思考を最小化して応答を速くする。
            config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="MINIMAL")
            )

        # RPM 制限を守るため、呼び出し開始間隔を最低 RATE_LIMIT_MIN_INTERVAL 秒に保つ
        self._rate_limiter.acquire()

        return self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config
        )

    @staticmethod
    def _extract_text(response) -> str:
        """response から text を安全に取り出す。空/Noneなら空文字を返す。"""
        text = getattr(response, "text", None)
        return text.strip() if isinstance(text, str) else ""

    @staticmethod
    def _contains_japanese(text: str) -> bool:
        """ひらがな/カタカナが含まれるかを判定（日本語出力検証用）。"""
        return bool(re.search(r'[぀-ゟ゠-ヿ]', text))

    @staticmethod
    def _classify_error(error_message: str) -> str:
        """エラーメッセージを 'quota' / 'server' / 'default' に分類する。"""
        msg = error_message.lower()
        if any(k in msg for k in ("quota", "tokens per minute", "rate limit", "resource_exhausted", "429")):
            return "quota"
        if any(k in msg for k in ("500", "internal", "503", "unavailable", "timeout", "504")):
            return "server"
        return "default"

    def _get_retry_delay(self, error_message: str, attempt: int) -> int:
        """エラー種別と試行回数からリトライ待機時間を決める。"""
        kind = self._classify_error(error_message)
        delays = self.RETRY_DELAYS.get(kind, self.RETRY_DELAYS["default"])
        return delays[min(attempt, len(delays) - 1)]

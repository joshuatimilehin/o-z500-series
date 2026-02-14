from __future__ import annotations

import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


class SentimentAnalyzer:
    def __init__(self) -> None:
        self.vader = SentimentIntensityAnalyzer()

    def score_text(self, text: str) -> float:
        if not text:
            return 0.0
        return float(self.vader.polarity_scores(text).get("compound", 0.0))

    def label_score(self, score: float, pos: float = 0.05, neg: float = -0.05) -> str:
        if score >= pos:
            return "positive"
        if score <= neg:
            return "negative"
        return "neutral"

    def analyze_dataframe(self, df_news: pd.DataFrame) -> pd.DataFrame:
        if df_news.empty:
            out = df_news.copy()
            out["text"] = []
            out["sentiment_score"] = []
            out["sentiment_label"] = []
            return out

        out = df_news.copy()
        out["text"] = (out["title"].fillna("") + " " + out["summary"].fillna("")).str.strip()
        out["sentiment_score"] = out["text"].apply(self.score_text)
        out["sentiment_label"] = out["sentiment_score"].apply(self.label_score)
        return out

from __future__ import annotations

import numpy as np
import pandas as pd


class SentimentFeatureIntegrator:
    def __init__(self, windows_minutes: list[int] | None = None) -> None:
        self.windows_minutes = windows_minutes or [15, 30, 60, 120]

    def _prep_news(self, df_sentiment: pd.DataFrame) -> pd.DataFrame:
        if df_sentiment.empty:
            return pd.DataFrame(columns=["published_at", "sentiment_score", "is_positive", "is_negative"])

        df = df_sentiment.copy()
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
        df = df.dropna(subset=["published_at"])
        df["is_positive"] = (df["sentiment_score"] > 0.05).astype(float)
        df["is_negative"] = (df["sentiment_score"] < -0.05).astype(float)
        return df[["published_at", "sentiment_score", "is_positive", "is_negative"]].sort_values("published_at")

    def integrate(self, df_price: pd.DataFrame, df_sentiment: pd.DataFrame) -> pd.DataFrame:
        out = df_price.copy()
        if out.index.tz is None:
            out.index = out.index.tz_localize("UTC")

        news = self._prep_news(df_sentiment)
        if news.empty:
            for w in self.windows_minutes:
                out[f"news_count_{w}m"] = 0.0
                out[f"sentiment_mean_{w}m"] = 0.0
                out[f"sentiment_std_{w}m"] = 0.0
                out[f"pos_ratio_{w}m"] = 0.0
                out[f"neg_ratio_{w}m"] = 0.0
            out["sentiment_momentum"] = 0.0
            out = out.replace([np.inf, -np.inf], np.nan).dropna().copy()
            return out

        for w in self.windows_minutes:
            window = f"{w}min"

            count = (
                news.set_index("published_at")["sentiment_score"]
                .rolling(window)
                .count()
                .reindex(out.index, method="ffill")
                .fillna(0.0)
            )
            s_mean = (
                news.set_index("published_at")["sentiment_score"]
                .rolling(window)
                .mean()
                .reindex(out.index, method="ffill")
                .fillna(0.0)
            )
            s_std = (
                news.set_index("published_at")["sentiment_score"]
                .rolling(window)
                .std()
                .reindex(out.index, method="ffill")
                .fillna(0.0)
            )
            pos_ratio = (
                news.set_index("published_at")["is_positive"]
                .rolling(window)
                .mean()
                .reindex(out.index, method="ffill")
                .fillna(0.0)
            )
            neg_ratio = (
                news.set_index("published_at")["is_negative"]
                .rolling(window)
                .mean()
                .reindex(out.index, method="ffill")
                .fillna(0.0)
            )

            out[f"news_count_{w}m"] = count.values
            out[f"sentiment_mean_{w}m"] = s_mean.values
            out[f"sentiment_std_{w}m"] = s_std.values
            out[f"pos_ratio_{w}m"] = pos_ratio.values
            out[f"neg_ratio_{w}m"] = neg_ratio.values

        out["sentiment_momentum"] = out["sentiment_mean_30m"] - out["sentiment_mean_120m"]
        out = out.replace([np.inf, -np.inf], np.nan).dropna().copy()
        return out

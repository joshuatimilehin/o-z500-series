from __future__ import annotations

import numpy as np
import pandas as pd


class ShockDetector:
    def __init__(self, surprisal_threshold: float = 1.1, entropy_drop_threshold: float = -0.03) -> None:
        self.surprisal_threshold = surprisal_threshold
        self.entropy_drop_threshold = entropy_drop_threshold

    def _ensure_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        if "ret_1" not in out.columns:
            out["ret_1"] = out["close"].pct_change().fillna(0.0)

        if "surprisal_ret" not in out.columns:
            mu = out["ret_1"].rolling(30).mean()
            sigma = out["ret_1"].rolling(30).std().replace(0, np.nan)
            z = ((out["ret_1"] - mu) / sigma).abs().fillna(0.0)
            out["surprisal_ret"] = np.log1p(z)

        if "sign_entropy_30" not in out.columns:
            up_prob = (out["ret_1"] > 0).astype(float).rolling(30).mean().clip(1e-8, 1 - 1e-8)
            out["sign_entropy_30"] = -(up_prob * np.log2(up_prob) + (1 - up_prob) * np.log2(1 - up_prob))
            out["sign_entropy_30"] = out["sign_entropy_30"].fillna(0.0)

        if "news_count_30m" not in out.columns:
            out["news_count_30m"] = 0.0
        if "sentiment_mean_30m" not in out.columns:
            out["sentiment_mean_30m"] = 0.0
        if "arb_count_30m" not in out.columns:
            out["arb_count_30m"] = 0.0

        return out

    def label_shocks(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self._ensure_columns(df)

        out["entropy_delta_5"] = out["sign_entropy_30"].diff(5).fillna(0.0)

        out["shock_flag"] = (
            (out["surprisal_ret"] >= self.surprisal_threshold)
            | (out["entropy_delta_5"] <= self.entropy_drop_threshold)
            | (out["arb_count_30m"] >= 1)
        ).astype(int)

        shock_type = np.full(len(out), "none", dtype=object)

        news_pos = (out["news_count_30m"] >= 1) & (out["sentiment_mean_30m"] > 0.15)
        news_neg = (out["news_count_30m"] >= 1) & (out["sentiment_mean_30m"] < -0.15)
        liquidity = (out["arb_count_30m"] >= 1)
        technical = (out["surprisal_ret"] >= self.surprisal_threshold) & (~news_pos) & (~news_neg) & (~liquidity)

        shock_type[news_pos.values] = "news_positive"
        shock_type[news_neg.values] = "news_negative"
        shock_type[liquidity.values] = "liquidity_spike"
        shock_type[technical.values] = "technical_breakout"

        out["shock_type"] = shock_type
        out.loc[out["shock_flag"] == 0, "shock_type"] = "none"

        return out

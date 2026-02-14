from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd
import ta


class FeatureEngineer:
    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df.copy()
        self._feature_cols: list[str] = []

    def create_all_features(self) -> pd.DataFrame:
        df = self.df.copy()

        df["ret_1"] = df["close"].pct_change()
        df["ret_3"] = df["close"].pct_change(3)
        df["ret_6"] = df["close"].pct_change(6)

        for w in [5, 10, 20, 50]:
            df[f"sma_{w}"] = df["close"].rolling(w).mean()
            df[f"ema_{w}"] = df["close"].ewm(span=w, adjust=False).mean()

        df["rsi_14"] = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()

        macd = ta.trend.MACD(close=df["close"])
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_diff"] = macd.macd_diff()

        bb = ta.volatility.BollingerBands(close=df["close"], window=20, window_dev=2)
        df["bb_h"] = bb.bollinger_hband()
        df["bb_l"] = bb.bollinger_lband()
        df["bb_m"] = bb.bollinger_mavg()
        df["bb_w"] = bb.bollinger_wband()

        atr = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14)
        df["atr_14"] = atr.average_true_range()

        df["vol_chg"] = df["volume"].pct_change()
        df["range_pct"] = (df["high"] - df["low"]) / df["close"]
        df["body_pct"] = (df["close"] - df["open"]).abs() / df["close"]

        idx_local = df.index.tz_convert(None) if getattr(df.index, "tz", None) is not None else df.index
        df["hour"] = idx_local.hour
        df["dow"] = idx_local.dayofweek

        # Keep only numeric columns and drop rows with NA from rolling indicators.
        df = df.replace([np.inf, -np.inf], np.nan).dropna().copy()

        self._feature_cols = [
            c for c in df.columns
            if c not in {"target"} and pd.api.types.is_numeric_dtype(df[c])
        ]

        self.df = df
        return df

    def get_feature_columns(self) -> List[str]:
        return list(self._feature_cols)

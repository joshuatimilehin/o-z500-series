from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_classif


class SignalTheoryFeatureEngineer:
    def __init__(self, windows: list[int] | None = None, top_k_mi: int = 12) -> None:
        self.windows = windows or [15, 30, 60, 120]
        self.top_k_mi = top_k_mi
        self.selected_mi_features: list[str] = []

    def _rolling_hist_entropy(self, series: pd.Series, window: int, bins: int = 8) -> pd.Series:
        def entropy_fn(x: np.ndarray) -> float:
            if len(x) < 4:
                return 0.0
            hist, _ = np.histogram(x, bins=bins)
            p = hist / max(hist.sum(), 1)
            p = p[p > 0]
            if len(p) == 0:
                return 0.0
            return float(-(p * np.log2(p)).sum())

        return series.rolling(window).apply(lambda x: entropy_fn(np.asarray(x, dtype=float)), raw=False)

    def _binary_entropy(self, up_prob: pd.Series, eps: float = 1e-8) -> pd.Series:
        p = up_prob.clip(eps, 1 - eps)
        return -(p * np.log2(p) + (1 - p) * np.log2(1 - p))

    def _safe_zscore(self, series: pd.Series) -> pd.Series:
        std = series.std()
        if std is None or std == 0 or np.isnan(std):
            return pd.Series(np.zeros(len(series)), index=series.index, dtype=float)
        return (series - series.mean()) / std

    def _add_entropy_and_surprisal(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        ret = out["ret_1"] if "ret_1" in out.columns else out["close"].pct_change()
        out["ret_1_work"] = ret.fillna(0.0)

        for w in self.windows:
            up_prob = (out["ret_1_work"] > 0).astype(float).rolling(w).mean()
            out[f"sign_entropy_{w}"] = self._binary_entropy(up_prob).fillna(0.0)
            out[f"return_entropy_{w}"] = self._rolling_hist_entropy(out["ret_1_work"], w).fillna(0.0)

        out["ret_mu_30"] = out["ret_1_work"].rolling(30).mean()
        out["ret_sigma_30"] = out["ret_1_work"].rolling(30).std().replace(0, np.nan)
        z = ((out["ret_1_work"] - out["ret_mu_30"]) / out["ret_sigma_30"]).abs().fillna(0.0)
        out["surprisal_ret"] = np.log1p(z)

        out["signal_strength_30"] = out["ret_1_work"].rolling(30).mean().abs().fillna(0.0)
        out["noise_level_30"] = out["ret_1_work"].rolling(30).std().fillna(0.0)
        out["snr_proxy_30"] = out["signal_strength_30"] / (out["noise_level_30"] + 1e-8)
        out["channel_capacity_proxy"] = np.log1p(out["snr_proxy_30"].clip(lower=0.0))
        out["communication_efficiency"] = out["channel_capacity_proxy"] * (1 - out["sign_entropy_30"].clip(0, 1))

        return out

    def _add_mi_composite(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "target" not in out.columns:
            return out

        numeric_cols = [c for c in out.columns if c != "target" and pd.api.types.is_numeric_dtype(out[c])]
        if len(numeric_cols) < 5:
            out["mi_weighted_composite"] = 0.0
            out["mi_topk_mean"] = 0.0
            out["mi_topk_std"] = 0.0
            self.selected_mi_features = []
            return out

        x = out[numeric_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        y = out["target"].astype(int)

        mi = mutual_info_classif(x, y, random_state=42)
        mi_series = pd.Series(mi, index=numeric_cols).sort_values(ascending=False)

        top = mi_series.head(min(self.top_k_mi, len(mi_series)))
        if top.sum() <= 0:
            top = mi_series.head(min(6, len(mi_series)))

        selected = list(top.index)
        self.selected_mi_features = selected

        weights = top / max(top.sum(), 1e-8)

        zcols: list[pd.Series] = []
        for c in selected:
            zcols.append(self._safe_zscore(out[c]).rename(c))
        zdf = pd.concat(zcols, axis=1) if zcols else pd.DataFrame(index=out.index)

        if len(zdf.columns) == 0:
            out["mi_weighted_composite"] = 0.0
            out["mi_topk_mean"] = 0.0
            out["mi_topk_std"] = 0.0
            return out

        weighted = pd.Series(np.zeros(len(out)), index=out.index, dtype=float)
        for c in zdf.columns:
            weighted += zdf[c] * float(weights.get(c, 0.0))

        out["mi_weighted_composite"] = weighted
        out["mi_topk_mean"] = zdf.mean(axis=1)
        out["mi_topk_std"] = zdf.std(axis=1).fillna(0.0)
        return out

    def integrate(self, df_base: pd.DataFrame) -> pd.DataFrame:
        out = df_base.copy()
        out = self._add_entropy_and_surprisal(out)
        out = self._add_mi_composite(out)
        out = out.replace([np.inf, -np.inf], np.nan).dropna().copy()
        return out

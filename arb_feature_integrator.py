from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


class ArbFeatureIntegrator:
    def __init__(self, windows_minutes: list[int] | None = None) -> None:
        self.windows_minutes = windows_minutes or [15, 30, 60, 120]

    def load_events(self, path: str = "data/arb_events.jsonl") -> pd.DataFrame:
        p = Path(path)
        if not p.exists():
            return pd.DataFrame(columns=["timestamp", "gross_edge", "net_edge", "best_pair_size"])

        rows: list[dict] = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue

        if not rows:
            return pd.DataFrame(columns=["timestamp", "gross_edge", "net_edge", "best_pair_size"])

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        for col in ["gross_edge", "net_edge", "best_pair_size"]:
            if col not in df.columns:
                df[col] = 0.0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        return df[["timestamp", "gross_edge", "net_edge", "best_pair_size"]]

    def integrate(self, df_price: pd.DataFrame, df_arb_events: pd.DataFrame) -> pd.DataFrame:
        out = df_price.copy()
        if out.index.tz is None:
            out.index = out.index.tz_localize("UTC")

        if df_arb_events.empty:
            for w in self.windows_minutes:
                out[f"arb_count_{w}m"] = 0.0
                out[f"arb_net_edge_mean_{w}m"] = 0.0
                out[f"arb_gross_edge_max_{w}m"] = 0.0
                out[f"arb_size_sum_{w}m"] = 0.0
            out["arb_spike_30m"] = 0.0
            out = out.replace([np.inf, -np.inf], np.nan).dropna().copy()
            return out

        events = df_arb_events.set_index("timestamp").sort_index()

        for w in self.windows_minutes:
            window = f"{w}min"

            cnt = events["net_edge"].rolling(window).count().reindex(out.index, method="ffill").fillna(0.0)
            net_mean = events["net_edge"].rolling(window).mean().reindex(out.index, method="ffill").fillna(0.0)
            gross_max = events["gross_edge"].rolling(window).max().reindex(out.index, method="ffill").fillna(0.0)
            size_sum = events["best_pair_size"].rolling(window).sum().reindex(out.index, method="ffill").fillna(0.0)

            out[f"arb_count_{w}m"] = cnt.values
            out[f"arb_net_edge_mean_{w}m"] = net_mean.values
            out[f"arb_gross_edge_max_{w}m"] = gross_max.values
            out[f"arb_size_sum_{w}m"] = size_sum.values

        out["arb_spike_30m"] = (out["arb_count_30m"] >= 3).astype(float)
        out = out.replace([np.inf, -np.inf], np.nan).dropna().copy()
        return out

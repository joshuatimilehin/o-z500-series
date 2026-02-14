from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class PolicyConfig:
    fee_rate_side: float = 0.02
    slippage_side: float = 0.002
    min_ev_side: float = 0.01
    min_edge_pair: float = 0.01


class ExecutionPolicy:
    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def _safe_col(self, df: pd.DataFrame, col: str) -> pd.Series:
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce")
        return pd.Series([np.nan] * len(df), index=df.index, dtype=float)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        p_yes = self._safe_col(out, "fair_p_yes")
        ask_yes = self._safe_col(out, "ask_yes")
        ask_no = self._safe_col(out, "ask_no")

        side_cost = self.config.fee_rate_side + self.config.slippage_side
        pair_cost = 2 * side_cost

        ev_yes = p_yes - ask_yes - side_cost
        ev_no = (1.0 - p_yes) - ask_no - side_cost
        edge_pair = 1.0 - (ask_yes + ask_no) - pair_cost

        out["ev_yes"] = ev_yes
        out["ev_no"] = ev_no
        out["edge_pair"] = edge_pair

        actions: list[str] = []
        chosen_ev: list[float] = []

        for i in range(len(out)):
            ey = ev_yes.iloc[i]
            en = ev_no.iloc[i]
            ep = edge_pair.iloc[i]

            if not np.isnan(ep) and ep >= self.config.min_edge_pair:
                actions.append("buy_both")
                chosen_ev.append(float(ep))
                continue

            if not np.isnan(ey) and ey >= self.config.min_ev_side and (np.isnan(en) or ey >= en):
                actions.append("buy_yes")
                chosen_ev.append(float(ey))
                continue

            if not np.isnan(en) and en >= self.config.min_ev_side:
                actions.append("buy_no")
                chosen_ev.append(float(en))
                continue

            actions.append("no_trade")
            chosen_ev.append(0.0)

        out["action"] = actions
        out["chosen_ev"] = chosen_ev
        return out


def summarize(signals: pd.DataFrame) -> dict:
    action_counts = signals["action"].value_counts().to_dict() if "action" in signals.columns else {}
    traded = signals[signals["action"] != "no_trade"] if "action" in signals.columns else pd.DataFrame()

    summary = {
        "rows": int(len(signals)),
        "action_counts": action_counts,
        "trade_rows": int(len(traded)),
        "avg_chosen_ev": float(traded["chosen_ev"].mean()) if len(traded) else 0.0,
        "sum_chosen_ev": float(traded["chosen_ev"].sum()) if len(traded) else 0.0,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate EV-based execution actions from fair-value predictions")
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--signals-out", default="results/execution_policy_signals.csv")
    parser.add_argument("--summary-out", default="results/execution_policy_summary.json")
    parser.add_argument("--fee-rate-side", type=float, default=0.02)
    parser.add_argument("--slippage-side", type=float, default=0.002)
    parser.add_argument("--min-ev-side", type=float, default=0.01)
    parser.add_argument("--min-edge-pair", type=float, default=0.01)
    args = parser.parse_args()

    df = pd.read_csv(args.predictions)
    policy = ExecutionPolicy(
        PolicyConfig(
            fee_rate_side=args.fee_rate_side,
            slippage_side=args.slippage_side,
            min_ev_side=args.min_ev_side,
            min_edge_pair=args.min_edge_pair,
        )
    )
    signals = policy.apply(df)

    Path(args.signals_out).parent.mkdir(parents=True, exist_ok=True)
    signals.to_csv(args.signals_out, index=False)

    summary = summarize(signals)
    summary["signals_out"] = args.signals_out
    summary["predictions"] = args.predictions

    Path(args.summary_out).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.summary_out).open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

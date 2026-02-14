from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from shock_detector import ShockDetector


def load_dataset(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)

    for ts_col in ["feature_time_utc", "timestamp", "Unnamed: 0"]:
        if ts_col in df.columns:
            idx = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
            if idx.notna().sum() > 0:
                df = df.loc[idx.notna()].copy()
                df.index = idx[idx.notna()]
                break

    return df


def load_models() -> dict[str, dict]:
    model_dir = Path("models")
    out: dict[str, dict] = {}
    for p in model_dir.glob("shock_model_*.pkl"):
        payload = joblib.load(p)
        out[payload["shock_type"]] = payload
    return out


def run_event_trader(
    df: pd.DataFrame,
    confidence_threshold: float,
    position_size: float,
    max_trades_per_day: int,
    surprisal_threshold: float,
    entropy_drop_threshold: float,
) -> dict:
    detector = ShockDetector(
        surprisal_threshold=surprisal_threshold,
        entropy_drop_threshold=entropy_drop_threshold,
    )
    labeled = detector.label_shocks(df).replace([np.inf, -np.inf], np.nan).dropna(subset=["target"]).copy()

    models = load_models()
    if not models:
        raise RuntimeError("No trained shock models found in models/shock_model_*.pkl")

    start_eval = int(len(labeled) * 0.8)
    eval_df = labeled.iloc[start_eval:].copy()

    equity = 1000.0
    initial_capital = equity
    trades = 0
    wins = 0
    daily_counts: dict[str, int] = {}

    for ts, row in eval_df.iterrows():
        stype = row.get("shock_type", "none")
        if stype == "none" or stype not in models:
            continue

        day_key = str(ts.date())
        daily_counts.setdefault(day_key, 0)
        if daily_counts[day_key] >= max_trades_per_day:
            continue

        payload = models[stype]
        feats = payload["features"]
        model = payload["model"]

        missing = [c for c in feats if c not in eval_df.columns]
        if missing:
            continue

        x_row = pd.DataFrame([row[feats].astype(float).values], columns=feats)
        proba = model.predict_proba(x_row)[0]
        pred = int(np.argmax(proba))
        conf = float(np.max(proba))

        if conf < confidence_threshold:
            continue

        trades += 1
        daily_counts[day_key] += 1

        actual = int(row["target"])
        correct = int(pred == actual)
        wins += correct

        stake = equity * position_size
        ret = 0.02 if correct else -0.02
        equity += stake * ret

    results = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "trades": int(trades),
        "win_rate": float(wins / trades) if trades else 0.0,
        "total_return": float((equity - initial_capital) / initial_capital),
        "ending_capital": float(equity),
        "confidence_threshold": confidence_threshold,
        "position_size": position_size,
        "max_trades_per_day": max_trades_per_day,
        "detector_thresholds": {
            "surprisal_threshold": surprisal_threshold,
            "entropy_drop_threshold": entropy_drop_threshold,
        },
        "eval_rows": int(len(eval_df)),
        "model_count": len(models),
    }

    out = Path("results/event_trader_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Event-driven paper trader with shock-specific models")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--confidence-threshold", type=float, default=0.60)
    parser.add_argument("--position-size", type=float, default=0.05)
    parser.add_argument("--max-trades-per-day", type=int, default=20)
    parser.add_argument("--surprisal-threshold", type=float, default=1.1)
    parser.add_argument("--entropy-drop-threshold", type=float, default=-0.03)
    args = parser.parse_args()

    df = load_dataset(args.dataset)
    results = run_event_trader(
        df,
        confidence_threshold=args.confidence_threshold,
        position_size=args.position_size,
        max_trades_per_day=args.max_trades_per_day,
        surprisal_threshold=args.surprisal_threshold,
        entropy_drop_threshold=args.entropy_drop_threshold,
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

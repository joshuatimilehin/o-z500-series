from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from backtester import Backtester
from model_trainer import BTCPredictor


def _load_dataset(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)

    # Keep the first timestamp-like column as index if available.
    for ts_col in ["timestamp", "feature_time_utc", "Unnamed: 0"]:
        if ts_col in df.columns:
            try:
                idx = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
                if idx.notna().sum() > 0:
                    df = df.loc[idx.notna()].copy()
                    df.index = idx[idx.notna()]
                    break
            except Exception:
                pass

    return df


def walk_forward_eval(df: pd.DataFrame, train_size: int, test_size: int, step_size: int) -> dict:
    if "target" not in df.columns:
        raise ValueError("Dataset must include target column.")

    numeric_cols = [c for c in df.columns if c != "target" and pd.api.types.is_numeric_dtype(df[c])]
    data = df[numeric_cols + ["target"]].replace([np.inf, -np.inf], np.nan).dropna().copy()

    n = len(data)
    if n < train_size + test_size:
        raise ValueError(f"Not enough rows ({n}) for train_size={train_size}, test_size={test_size}")

    folds = []
    start = 0
    fold_id = 0

    while start + train_size + test_size <= n:
        fold_id += 1
        train = data.iloc[start : start + train_size]
        test = data.iloc[start + train_size : start + train_size + test_size]

        predictor = BTCPredictor()
        X_train = train.drop(columns=["target"])
        y_train = train["target"].astype(int)
        X_test = test.drop(columns=["target"])
        y_test = test["target"].astype(int)

        predictor.train(X_train, y_train)
        metrics = predictor.evaluate(X_test, y_test)

        y_pred = predictor.predict(X_test)
        y_prob = predictor.predict_proba(X_test)

        bt = Backtester(initial_capital=1000, position_size=0.02, confidence_threshold=0.6)
        test_for_bt = test.copy()
        bt_res = bt.run_backtest(test_for_bt, y_pred, y_prob)

        folds.append(
            {
                "fold": fold_id,
                "train_start": str(train.index.min()),
                "train_end": str(train.index.max()),
                "test_start": str(test.index.min()),
                "test_end": str(test.index.max()),
                "metrics": metrics,
                "backtest": bt_res,
            }
        )

        start += step_size

    acc = [f["metrics"]["accuracy"] for f in folds]
    wr = [f["backtest"]["win_rate"] for f in folds]
    ret = [f["backtest"]["total_return"] for f in folds]

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows_used": int(len(data)),
        "fold_count": len(folds),
        "train_size": train_size,
        "test_size": test_size,
        "step_size": step_size,
        "accuracy_mean": float(np.mean(acc)) if acc else 0.0,
        "accuracy_std": float(np.std(acc)) if acc else 0.0,
        "win_rate_mean": float(np.mean(wr)) if wr else 0.0,
        "return_mean": float(np.mean(ret)) if ret else 0.0,
        "folds": folds,
    }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward validation for phase datasets")
    parser.add_argument("--dataset", required=True, help="Path to dataset csv/parquet")
    parser.add_argument("--train-size", type=int, default=1200)
    parser.add_argument("--test-size", type=int, default=200)
    parser.add_argument("--step-size", type=int, default=100)
    parser.add_argument("--output", default="results/walk_forward_summary.json")
    args = parser.parse_args()

    df = _load_dataset(args.dataset)
    summary = walk_forward_eval(df, args.train_size, args.test_size, args.step_size)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Walk-forward complete")
    print(json.dumps({
        "fold_count": summary["fold_count"],
        "accuracy_mean": summary["accuracy_mean"],
        "win_rate_mean": summary["win_rate_mean"],
        "return_mean": summary["return_mean"],
        "output": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()

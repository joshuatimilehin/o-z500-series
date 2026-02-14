from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from xgboost import XGBClassifier

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


def train_shock_models(
    df: pd.DataFrame,
    min_samples: int = 150,
    surprisal_threshold: float = 1.1,
    entropy_drop_threshold: float = -0.03,
) -> dict:
    detector = ShockDetector(
        surprisal_threshold=surprisal_threshold,
        entropy_drop_threshold=entropy_drop_threshold,
    )
    labeled = detector.label_shocks(df)
    labeled = labeled.replace([np.inf, -np.inf], np.nan).dropna(subset=["target"]).copy()

    results: dict[str, dict] = {}
    model_dir = Path("models")
    model_dir.mkdir(parents=True, exist_ok=True)

    shock_types = [s for s in sorted(labeled["shock_type"].unique()) if s != "none"]

    for stype in shock_types:
        subset = labeled[labeled["shock_type"] == stype].copy()
        if len(subset) < min_samples:
            results[stype] = {"status": "skipped", "reason": f"insufficient_samples:{len(subset)}"}
            continue

        feature_cols = [c for c in subset.columns if c not in {"target", "shock_flag", "shock_type"} and pd.api.types.is_numeric_dtype(subset[c])]
        subset = subset[feature_cols + ["target"]].replace([np.inf, -np.inf], np.nan).dropna().copy()
        if len(subset) < min_samples:
            results[stype] = {"status": "skipped", "reason": f"insufficient_clean_samples:{len(subset)}"}
            continue

        split_idx = int(len(subset) * 0.8)
        train = subset.iloc[:split_idx]
        test = subset.iloc[split_idx:]
        if len(test) < 20:
            results[stype] = {"status": "skipped", "reason": f"test_too_small:{len(test)}"}
            continue

        x_train, y_train = train.drop(columns=["target"]), train["target"].astype(int)
        x_test, y_test = test.drop(columns=["target"]), test["target"].astype(int)

        model = XGBClassifier(
            n_estimators=250,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )
        model.fit(x_train, y_train)

        y_pred = model.predict(x_test)
        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
            "samples": int(len(subset)),
            "train_samples": int(len(train)),
            "test_samples": int(len(test)),
            "features": len(feature_cols),
        }

        model_path = model_dir / f"shock_model_{stype}.pkl"
        joblib.dump({"model": model, "features": feature_cols, "shock_type": stype}, model_path)

        results[stype] = {
            "status": "trained",
            "model_path": str(model_path),
            "metrics": metrics,
        }

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "detector_thresholds": {
            "surprisal_threshold": surprisal_threshold,
            "entropy_drop_threshold": entropy_drop_threshold,
        },
        "shock_type_counts": labeled["shock_type"].value_counts().to_dict(),
        "results": results,
    }

    out = Path("results/shock_model_metrics.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Train shock-specific models")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--min-samples", type=int, default=150)
    parser.add_argument("--surprisal-threshold", type=float, default=1.1)
    parser.add_argument("--entropy-drop-threshold", type=float, default=-0.03)
    args = parser.parse_args()

    df = load_dataset(args.dataset)
    summary = train_shock_models(
        df,
        min_samples=args.min_samples,
        surprisal_threshold=args.surprisal_threshold,
        entropy_drop_threshold=args.entropy_drop_threshold,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

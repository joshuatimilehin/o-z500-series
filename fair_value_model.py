from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
from xgboost import XGBClassifier


@dataclass
class FairValueConfig:
    test_size: float = 0.2
    random_state: int = 42


class FairValueModel:
    def __init__(self, config: FairValueConfig | None = None) -> None:
        self.config = config or FairValueConfig()
        self.base_model = XGBClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=self.config.random_state,
            n_jobs=-1,
        )
        self.model: CalibratedClassifierCV | None = None
        self.features: list[str] = []

    def _feature_columns(self, df: pd.DataFrame) -> list[str]:
        preferred = [
            "bid_yes", "ask_yes", "spread_yes",
            "bid_no", "ask_no", "spread_no",
            "mid_yes", "mid_no",
            "book_sum_ask", "book_sum_bid",
            "liquidity", "volume24h", "time_to_end_min",
            "reference_btc_price", "strike_price",
        ]
        cols = [c for c in preferred if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
        if not cols:
            cols = [c for c in df.columns if c != "target" and pd.api.types.is_numeric_dtype(df[c])]
        return cols

    def prepare(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
        if "target" not in df.columns:
            raise ValueError("Input must include target column")

        data = df.copy().replace([np.inf, -np.inf], np.nan)
        data = data[data["target"].notna()].copy()

        if len(data) < 120:
            raise ValueError(f"Not enough labeled rows to train fair value model: {len(data)}")

        raw_features = self._feature_columns(data)
        # Keep features with at least minimal coverage on historical data.
        features = [c for c in raw_features if data[c].notna().mean() >= 0.05]
        if not features:
            raise ValueError("No usable feature columns after sparsity filtering.")

        x = data[features].copy()
        # Median-impute sparse book fields; fallback zero.
        for c in x.columns:
            med = x[c].median()
            x[c] = x[c].fillna(0.0 if np.isnan(med) else float(med))

        y = data["target"].astype(int)
        self.features = list(x.columns)

        split_idx = int(len(data) * (1 - self.config.test_size))
        x_train, x_test = x.iloc[:split_idx], x.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
        return x_train, y_train, x_test, y_test

    def train(self, x_train: pd.DataFrame, y_train: pd.Series) -> None:
        self.base_model.fit(x_train, y_train)
        try:
            self.model = CalibratedClassifierCV(self.base_model, method="sigmoid", cv="prefit")
            self.model.fit(x_train, y_train)
        except Exception:
            # Fallback: keep uncalibrated model if calibration backend fails.
            self.model = self.base_model

    def evaluate(self, x_test: pd.DataFrame, y_test: pd.Series) -> dict:
        if self.model is None:
            raise RuntimeError("Model not trained")

        p = self.model.predict_proba(x_test)[:, 1]
        y_pred = (p >= 0.5).astype(int)

        out = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
            "brier": float(brier_score_loss(y_test, p)),
            "rows_test": int(len(y_test)),
        }
        try:
            out["auc"] = float(roc_auc_score(y_test, p))
        except Exception:
            out["auc"] = None
        return out

    def predict_fair_prob(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.model is None:
            raise RuntimeError("Model not trained")

        out = df.copy()
        x = out[self.features].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        p_yes = self.model.predict_proba(x)[:, 1]
        out["fair_p_yes"] = p_yes
        out["fair_p_no"] = 1.0 - p_yes

        if "ask_yes" in out.columns:
            out["value_gap_yes"] = out["fair_p_yes"] - out["ask_yes"].fillna(0.0)
        else:
            out["value_gap_yes"] = np.nan

        if "ask_no" in out.columns:
            out["value_gap_no"] = out["fair_p_no"] - out["ask_no"].fillna(0.0)
        else:
            out["value_gap_no"] = np.nan

        return out

    def save(self, path: str) -> None:
        if self.model is None:
            raise RuntimeError("Model not trained")
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self.model, "features": self.features}, p)


def load_truth_dataset(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)

    try:
        df = pd.read_csv(p)
    except EmptyDataError:
        return pd.DataFrame()

    if df.empty:
        return df

    if "resolved_yes" in df.columns:
        target = df["resolved_yes"]
    else:
        target = pd.Series([np.nan] * len(df))

    if "derived_yes" in df.columns:
        target = target.fillna(df["derived_yes"])

    df["target"] = target
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Train fair-value probability model for BTC window markets")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model-out", default="models/fair_value_model.pkl")
    parser.add_argument("--pred-out", default="results/fair_value_predictions.csv")
    parser.add_argument("--summary-out", default="results/fair_value_summary.json")
    args = parser.parse_args()

    df = load_truth_dataset(args.dataset)
    if df.empty:
        raise ValueError(f"Dataset is empty: {args.dataset}")

    fvm = FairValueModel()

    x_train, y_train, x_test, y_test = fvm.prepare(df)
    fvm.train(x_train, y_train)
    metrics = fvm.evaluate(x_test, y_test)

    pred = fvm.predict_fair_prob(df)

    Path(args.pred_out).parent.mkdir(parents=True, exist_ok=True)
    pred.to_csv(args.pred_out, index=False)
    fvm.save(args.model_out)

    summary = {
        "dataset": args.dataset,
        "model_out": args.model_out,
        "pred_out": args.pred_out,
        "rows_total": int(len(df)),
        "rows_labeled": int(df["target"].notna().sum()),
        "features": fvm.features,
        "metrics": metrics,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    Path(args.summary_out).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.summary_out).open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

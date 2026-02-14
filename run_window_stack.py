from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from execution_policy import ExecutionPolicy, PolicyConfig, summarize
from fair_value_model import FairValueModel, load_truth_dataset
from window_truth_builder import BuilderConfig, WindowTruthBuilder, save_outputs


def _write_summary(payload: dict) -> None:
    summary_path = Path("results/window_stack_summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full BTC-window stack: truth build -> fair value model -> execution policy")
    parser.add_argument("--max-markets", type=int, default=4000)
    parser.add_argument("--max-candidates", type=int, default=250, help="Max selected markets to enrich with books/prices")
    parser.add_argument("--min-liquidity", type=float, default=1000.0)
    parser.add_argument("--active-only", action="store_true")
    parser.add_argument("--closed-only", action="store_true")
    parser.add_argument(
        "--fallback-mode",
        default="auto",
        choices=["none", "btc_timebounded", "crypto_timebounded", "auto"],
        help="Fallback universe if strict BTC-window rows are scarce.",
    )
    parser.add_argument(
        "--fallback-min-rows",
        type=int,
        default=120,
        help="Minimum rows to avoid fallback; otherwise fallback mode is used.",
    )
    parser.add_argument("--fee-rate-side", type=float, default=0.02)
    parser.add_argument("--slippage-side", type=float, default=0.002)
    parser.add_argument("--min-ev-side", type=float, default=0.01)
    parser.add_argument("--min-edge-pair", type=float, default=0.01)
    args = parser.parse_args()

    include_active = True
    include_closed = True
    if args.active_only:
        include_closed = False
    if args.closed_only:
        include_active = False

    cfg = BuilderConfig(
        max_markets=args.max_markets,
        max_candidates=args.max_candidates,
        min_liquidity=args.min_liquidity,
        include_active=include_active,
        include_closed=include_closed,
        btc_only=True,
        fallback_mode=args.fallback_mode,
        fallback_min_rows=args.fallback_min_rows,
    )

    builder = WindowTruthBuilder(cfg)
    truth_df = builder.build()
    truth_summary = save_outputs(truth_df, prefix="window_truth")

    out = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "truth_summary": truth_summary,
    }

    if len(truth_df) == 0:
        out["status"] = "no_btc_window_markets_found"
        out["message"] = (
            "No candidates found for current universe and fallback settings. "
            "Try --closed-only and/or --fallback-mode crypto_timebounded."
        )
        _write_summary(out)
        print(json.dumps(out, indent=2))
        return

    dataset_path = truth_summary["csv"]
    df = load_truth_dataset(dataset_path)

    if df.empty:
        out["status"] = "empty_truth_dataset"
        out["message"] = "Window truth dataset file is empty after load."
        _write_summary(out)
        print(json.dumps(out, indent=2))
        return

    labeled_rows = int(df["target"].notna().sum()) if "target" in df.columns else 0
    if labeled_rows < 120:
        out["status"] = "insufficient_labeled_data"
        out["message"] = "Need at least 120 labeled rows for robust fair value training."
        out["labeled_rows"] = labeled_rows
        _write_summary(out)
        print(json.dumps(out, indent=2))
        return

    model = FairValueModel()
    x_train, y_train, x_test, y_test = model.prepare(df)
    model.train(x_train, y_train)
    metrics = model.evaluate(x_test, y_test)
    pred_df = model.predict_fair_prob(df)

    pred_path = Path("results/fair_value_predictions.csv")
    pred_path.parent.mkdir(parents=True, exist_ok=True)
    pred_df.to_csv(pred_path, index=False)

    model_path = Path("models/fair_value_model.pkl")
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(model_path))

    policy = ExecutionPolicy(
        PolicyConfig(
            fee_rate_side=args.fee_rate_side,
            slippage_side=args.slippage_side,
            min_ev_side=args.min_ev_side,
            min_edge_pair=args.min_edge_pair,
        )
    )
    sig_df = policy.apply(pred_df)
    sig_path = Path("results/execution_policy_signals.csv")
    sig_df.to_csv(sig_path, index=False)
    exec_summary = summarize(sig_df)

    out.update(
        {
            "status": "ok",
            "fair_value_metrics": metrics,
            "model_path": str(model_path),
            "predictions_path": str(pred_path),
            "execution_signals_path": str(sig_path),
            "execution_summary": exec_summary,
        }
    )

    _write_summary(out)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

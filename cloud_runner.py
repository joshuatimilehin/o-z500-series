from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from google.cloud import storage
except ImportError:  # pragma: no cover
    storage = None

DEFAULT_PULL_FILES = [
    "data/arb_events.jsonl",
]

DEFAULT_PUSH_FILES = [
    "data/arb_events.jsonl",
    "results/window_stack_summary.json",
    "results/phase3_summary.json",
    "results/backtest_results_phase3.json",
    "results/fair_value_predictions.csv",
    "results/execution_policy_signals.csv",
    "results/cloud_runner_last_manifest.json",
]


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _split_csv(value: str | None, fallback: list[str]) -> list[str]:
    if value is None:
        return fallback
    stripped = value.strip()
    if not stripped:
        return []
    return [item.strip() for item in stripped.split(",") if item.strip()]


class GcsMirror:
    def __init__(self, bucket_name: str, prefix: str) -> None:
        self.bucket_name = bucket_name.strip()
        self.prefix = _normalize_path(prefix).rstrip("/")
        self.enabled = bool(self.bucket_name)

        if not self.enabled:
            self.bucket = None
            return

        if storage is None:
            raise RuntimeError(
                "google-cloud-storage is not installed. Install it or unset GCS_BUCKET."
            )

        client = storage.Client()
        self.bucket = client.bucket(self.bucket_name)

    def _remote_key(self, local_path: str) -> str:
        key = _normalize_path(local_path)
        if self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def pull_if_exists(self, local_paths: list[str]) -> None:
        if not self.enabled:
            return

        for local_path in local_paths:
            remote_key = self._remote_key(local_path)
            blob = self.bucket.blob(remote_key)
            if not blob.exists():
                continue

            dst = Path(local_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(dst))
            print(f"Pulled gs://{self.bucket_name}/{remote_key} -> {local_path}")

    def push_if_exists(self, local_paths: list[str]) -> None:
        if not self.enabled:
            return

        for local_path in local_paths:
            src = Path(local_path)
            if not src.exists():
                continue

            remote_key = self._remote_key(local_path)
            blob = self.bucket.blob(remote_key)
            blob.upload_from_filename(str(src))
            print(f"Pushed {local_path} -> gs://{self.bucket_name}/{remote_key}")


def _run_subprocess(cmd: list[str]) -> None:
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _ensure_dirs() -> None:
    for folder in ("data", "models", "results"):
        Path(folder).mkdir(parents=True, exist_ok=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cloud wrapper for Polybot jobs")
    parser.add_argument("--gcs-bucket", default=os.getenv("GCS_BUCKET", ""))
    parser.add_argument("--gcs-prefix", default=os.getenv("GCS_PREFIX", "polybot"))
    parser.add_argument(
        "--pull-files",
        default=None,
        help="Comma-separated local files to pull from GCS before run. Empty disables pull.",
    )
    parser.add_argument(
        "--push-files",
        default=None,
        help="Comma-separated local files to push to GCS after run. Empty disables push.",
    )

    sub = parser.add_subparsers(dest="mode", required=True)

    arb = sub.add_parser("arb-scan-once", help="Run one arb scan and exit")
    arb.add_argument("--market-limit", type=int, default=120)
    arb.add_argument("--min-liquidity", type=float, default=1000.0)
    arb.add_argument("--min-gross-edge", type=float, default=0.005)
    arb.add_argument("--fee-buffer", type=float, default=0.001)
    arb.add_argument("--slippage-buffer", type=float, default=0.001)
    arb.add_argument("--timeout-sec", type=int, default=15)
    arb.add_argument("--output", default="data/arb_events.jsonl")

    window = sub.add_parser("window-stack", help="Run run_window_stack.py")
    window.add_argument("--max-markets", type=int, default=4000)
    window.add_argument("--max-candidates", type=int, default=250)
    window.add_argument("--min-liquidity", type=float, default=1000.0)
    window.add_argument("--active-only", action="store_true")
    window.add_argument("--closed-only", action="store_true")
    window.add_argument(
        "--fallback-mode",
        default="auto",
        choices=["none", "btc_timebounded", "crypto_timebounded", "auto"],
    )
    window.add_argument("--fallback-min-rows", type=int, default=120)
    window.add_argument("--fee-rate-side", type=float, default=0.02)
    window.add_argument("--slippage-side", type=float, default=0.002)
    window.add_argument("--min-ev-side", type=float, default=0.01)
    window.add_argument("--min-edge-pair", type=float, default=0.01)

    sub.add_parser("phase3", help="Run main_pipeline_phase3.py")

    return parser


def _build_mode_command(args: argparse.Namespace) -> list[str]:
    if args.mode == "arb-scan-once":
        return [
            sys.executable,
            "arb_scanner.py",
            "--once",
            "--market-limit",
            str(args.market_limit),
            "--min-liquidity",
            str(args.min_liquidity),
            "--min-gross-edge",
            str(args.min_gross_edge),
            "--fee-buffer",
            str(args.fee_buffer),
            "--slippage-buffer",
            str(args.slippage_buffer),
            "--timeout-sec",
            str(args.timeout_sec),
            "--output",
            args.output,
        ]

    if args.mode == "window-stack":
        cmd = [
            sys.executable,
            "run_window_stack.py",
            "--max-markets",
            str(args.max_markets),
            "--max-candidates",
            str(args.max_candidates),
            "--min-liquidity",
            str(args.min_liquidity),
            "--fallback-mode",
            str(args.fallback_mode),
            "--fallback-min-rows",
            str(args.fallback_min_rows),
            "--fee-rate-side",
            str(args.fee_rate_side),
            "--slippage-side",
            str(args.slippage_side),
            "--min-ev-side",
            str(args.min_ev_side),
            "--min-edge-pair",
            str(args.min_edge_pair),
        ]
        if args.active_only:
            cmd.append("--active-only")
        if args.closed_only:
            cmd.append("--closed-only")
        return cmd

    if args.mode == "phase3":
        return [sys.executable, "main_pipeline_phase3.py"]

    raise ValueError(f"Unsupported mode: {args.mode}")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    _ensure_dirs()

    started_at = datetime.now(timezone.utc)
    pull_files = _split_csv(args.pull_files, DEFAULT_PULL_FILES)
    push_files = _split_csv(args.push_files, DEFAULT_PUSH_FILES)

    mirror = GcsMirror(args.gcs_bucket, args.gcs_prefix)

    status = "ok"
    error_message = ""

    try:
        mirror.pull_if_exists(pull_files)
        cmd = _build_mode_command(args)
        _run_subprocess(cmd)
    except Exception as exc:
        status = "error"
        error_message = str(exc)
        raise
    finally:
        finished_at = datetime.now(timezone.utc)
        manifest = {
            "generated_at_utc": finished_at.isoformat(),
            "status": status,
            "mode": args.mode,
            "error": error_message,
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "gcs_bucket": args.gcs_bucket,
            "gcs_prefix": args.gcs_prefix,
            "pull_files": pull_files,
            "push_files": push_files,
        }

        manifest_path = Path("results/cloud_runner_last_manifest.json")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        try:
            mirror.push_if_exists(push_files)
        except Exception as sync_exc:  # pragma: no cover
            print(f"GCS push warning: {sync_exc}")


if __name__ == "__main__":
    main()

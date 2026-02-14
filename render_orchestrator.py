from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(message: str) -> None:
    print(f"[{utc_now()}] {message}", flush=True)


def env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        log(f"Invalid int for {name}={raw!r}; using default {default}")
        return default
    return max(minimum, value)


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log(f"Invalid float for {name}={raw!r}; using default {default}")
        return default


def _move_dir_contents(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        target = dst / item.name
        if target.exists():
            continue
        shutil.move(str(item), str(target))


def ensure_persistent_links(persist_root: str) -> None:
    base = Path(persist_root)
    base.mkdir(parents=True, exist_ok=True)

    for name in ("data", "models", "results"):
        local_path = Path(name)
        persistent_path = base / name
        persistent_path.mkdir(parents=True, exist_ok=True)

        if local_path.is_symlink():
            try:
                if local_path.resolve() == persistent_path.resolve():
                    continue
            except Exception:
                pass
            local_path.unlink()

        if local_path.exists() and not local_path.is_symlink():
            if local_path.is_dir():
                _move_dir_contents(local_path, persistent_path)
                shutil.rmtree(local_path)
            else:
                backup = persistent_path / f"{local_path.name}.bak"
                shutil.move(str(local_path), str(backup))

        try:
            local_path.symlink_to(persistent_path, target_is_directory=True)
        except OSError as exc:
            # If symlinks are unavailable in some environments, fall back to local dirs.
            log(f"Symlink setup skipped for {name}: {exc}")
            local_path.mkdir(parents=True, exist_ok=True)


def ensure_local_dirs() -> None:
    for name in ("data", "models", "results"):
        Path(name).mkdir(parents=True, exist_ok=True)


@dataclass
class Job:
    name: str
    interval_sec: int
    command: list[str]
    next_run_monotonic: float


def run_job(job: Job) -> None:
    log(f"{job.name}: starting")
    log(f"{job.name}: command={' '.join(job.command)}")
    start = time.monotonic()
    completed = subprocess.run(job.command, check=False)
    elapsed = time.monotonic() - start
    if completed.returncode == 0:
        log(f"{job.name}: done in {elapsed:.1f}s")
    else:
        log(f"{job.name}: failed with exit code {completed.returncode} after {elapsed:.1f}s")


def build_jobs(now_mono: float) -> list[Job]:
    python = sys.executable

    arb_interval = env_int("ARB_INTERVAL_SEC", 120, minimum=0)
    window_interval = env_int("WINDOW_INTERVAL_SEC", 900, minimum=0)
    phase3_interval = env_int("PHASE3_INTERVAL_SEC", 0, minimum=0)

    arb_job = Job(
        name="arb_scan_once",
        interval_sec=arb_interval,
        command=[
            python,
            "arb_scanner.py",
            "--once",
            "--market-limit",
            str(env_int("ARB_MARKET_LIMIT", 120, minimum=1)),
            "--min-liquidity",
            str(env_float("ARB_MIN_LIQUIDITY", 1000.0)),
            "--min-gross-edge",
            str(env_float("ARB_MIN_GROSS_EDGE", 0.005)),
            "--fee-buffer",
            str(env_float("ARB_FEE_BUFFER", 0.001)),
            "--slippage-buffer",
            str(env_float("ARB_SLIPPAGE_BUFFER", 0.001)),
            "--timeout-sec",
            str(env_int("ARB_TIMEOUT_SEC", 15, minimum=1)),
            "--output",
            os.getenv("ARB_OUTPUT", "data/arb_events.jsonl"),
            "--quiet",
        ],
        next_run_monotonic=now_mono,
    )

    window_job = Job(
        name="window_stack",
        interval_sec=window_interval,
        command=[
            python,
            "run_window_stack.py",
            "--max-markets",
            str(env_int("WINDOW_MAX_MARKETS", 4000, minimum=1)),
            "--max-candidates",
            str(env_int("WINDOW_MAX_CANDIDATES", 250, minimum=1)),
            "--min-liquidity",
            str(env_float("WINDOW_MIN_LIQUIDITY", 1000.0)),
            "--fallback-mode",
            os.getenv("WINDOW_FALLBACK_MODE", "auto"),
            "--fallback-min-rows",
            str(env_int("WINDOW_FALLBACK_MIN_ROWS", 120, minimum=1)),
            "--fee-rate-side",
            str(env_float("WINDOW_FEE_RATE_SIDE", 0.02)),
            "--slippage-side",
            str(env_float("WINDOW_SLIPPAGE_SIDE", 0.002)),
            "--min-ev-side",
            str(env_float("WINDOW_MIN_EV_SIDE", 0.01)),
            "--min-edge-pair",
            str(env_float("WINDOW_MIN_EDGE_PAIR", 0.01)),
        ],
        next_run_monotonic=now_mono,
    )

    phase3_job = Job(
        name="phase3_pipeline",
        interval_sec=phase3_interval,
        command=[python, "main_pipeline_phase3.py"],
        next_run_monotonic=now_mono,
    )

    jobs = []
    if arb_job.interval_sec > 0:
        jobs.append(arb_job)
    if window_job.interval_sec > 0:
        jobs.append(window_job)
    if phase3_job.interval_sec > 0:
        jobs.append(phase3_job)

    return jobs


def main() -> None:
    persist_root = os.getenv("POLYBOT_PERSIST_ROOT", "").strip()
    if persist_root:
        log(f"Persistent mode enabled. Root={persist_root}")
        ensure_persistent_links(persist_root)
    else:
        log("Persistent mode disabled. Using local container filesystem.")
        ensure_local_dirs()

    now_mono = time.monotonic()
    jobs = build_jobs(now_mono)
    if not jobs:
        raise RuntimeError("No jobs enabled. Set ARB_INTERVAL_SEC and/or WINDOW_INTERVAL_SEC > 0.")

    heartbeat_sec = env_int("ORCH_HEARTBEAT_SEC", 60, minimum=5)
    sleep_sec = env_float("ORCH_LOOP_SLEEP_SEC", 2.0)
    next_heartbeat = now_mono + heartbeat_sec

    log("Render orchestrator started")
    for job in jobs:
        log(f"Enabled job: {job.name} every {job.interval_sec}s")

    while True:
        now_mono = time.monotonic()
        ran_any = False

        for job in jobs:
            if now_mono < job.next_run_monotonic:
                continue

            run_job(job)
            ran_any = True

            if job.interval_sec <= 0:
                job.next_run_monotonic = float("inf")
            else:
                while job.next_run_monotonic <= now_mono:
                    job.next_run_monotonic += job.interval_sec

        now_mono = time.monotonic()
        if now_mono >= next_heartbeat:
            next_due = min(job.next_run_monotonic for job in jobs)
            secs_left = max(0, int(next_due - now_mono))
            log(f"Heartbeat: next job due in ~{secs_left}s")
            next_heartbeat = now_mono + heartbeat_sec

        if not ran_any:
            time.sleep(max(0.5, sleep_sec))


if __name__ == "__main__":
    main()

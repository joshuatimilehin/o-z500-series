# Product Readiness Checklist

## Goal
Move from research pipeline to production-grade product with controlled risk.

## 1. Data Readiness
- [ ] Build at least 30-90 days of datasets with UTC timestamps.
- [ ] Keep raw source snapshots (`price`, `news`, `arb events`) per run.
- [ ] Enforce no-leakage policy: only use signals available at or before feature time.
- [ ] Add dataset schema checks (required columns + dtypes + null thresholds).

## 2. Model Readiness
- [ ] Run walk-forward evaluation (not a single split only).
- [ ] Define promotion thresholds (accuracy, win rate, return, drawdown).
- [ ] Track model drift (feature importance and performance over time).
- [ ] Version models with metadata (training window, feature set, metrics).

## 3. Signal Readiness
- [ ] Keep arb scanner running continuously to accumulate event density.
- [ ] Validate that arb/sentiment/signal-theory features provide stable lift.
- [ ] Add regime tagging (session/time-of-day/high-vol events).
- [ ] Build alerting for key trigger events (Discord/Telegram/SMS).

## 4. Execution Readiness
- [ ] Start with paper execution harness (fill simulation + slippage).
- [ ] Add kill switch and daily loss limits.
- [ ] Add max concurrent positions and per-market exposure caps.
- [ ] Log every decision: signal -> order intent -> fill/outcome.

## 5. Ops Readiness
- [ ] Run services under process manager (`pm2`, `systemd`, or scheduler).
- [ ] Centralize logs and errors (file + rotating logs).
- [ ] Add uptime checks and failure alerts.
- [ ] Define restart/recovery procedures after API/network outages.

## 6. Compliance & Security Readiness
- [ ] Store credentials in environment variables / secret manager.
- [ ] Remove secrets from code and docs.
- [ ] Limit API key permissions to minimum required.
- [ ] Keep audit trail of trades and model versions.

## 7. Go/No-Go Gates
- [ ] Gate A: Data quality stable for 2+ weeks.
- [ ] Gate B: Walk-forward results above target thresholds.
- [ ] Gate C: Paper execution profitable after costs.
- [ ] Gate D: Risk controls validated during stress scenarios.
- [ ] Gate E: Final sign-off from strategy + engineering owners.

## Suggested Next Run Order
1. `python build_dataset.py --days 30`
2. `python walk_forward_eval.py --dataset data/dataset_<run_id>.csv --train-size 1800 --test-size 300 --step-size 150`
3. Review `results/walk_forward_summary.json`
4. Decide promotion to paper execution.

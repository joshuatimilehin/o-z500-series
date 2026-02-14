# Render Deployment (No GCP Required)

This path deploys the bot to Render as a single background worker.
It does not require AWS or GCP accounts.

## What runs in Render

- `render_orchestrator.py` runs in one worker service.
- Jobs are scheduled inside that worker process:
  - Arb scan once every `ARB_INTERVAL_SEC` (default 120s)
  - Window stack every `WINDOW_INTERVAL_SEC` (default 900s)
  - Optional Phase 3 retrain every `PHASE3_INTERVAL_SEC` (default disabled)
- A persistent disk is mounted at `/app/runtime` and linked to:
  - `data/`
  - `models/`
  - `results/`

## Files added

- `render.yaml` (Render Blueprint)
- `render_orchestrator.py` (in-process scheduler)

## Deploy steps

1. Push this repo to GitHub.
2. In Render dashboard, create a new Blueprint.
3. Point it to this repo and `render.yaml`.
4. Approve service creation.
5. In worker environment vars, set `CRYPTOPANIC_API_KEY` if you use CryptoPanic.
6. Deploy.

## Tune scheduling

Set these env vars in Render:

- `ARB_INTERVAL_SEC` (default `120`)
- `WINDOW_INTERVAL_SEC` (default `900`)
- `PHASE3_INTERVAL_SEC` (default `0`, disabled)
- `ARB_MIN_GROSS_EDGE` (default `0.005`)
- `ARB_MIN_LIQUIDITY` (default `1000`)
- `WINDOW_FALLBACK_MODE` (default `auto`)
- `WINDOW_FALLBACK_MIN_ROWS` (default `120`)

## Logs and outputs

- View live logs in Render worker logs.
- Output files persist on the attached disk.
- Key files:
  - `data/arb_events.jsonl`
  - `results/window_stack_summary.json`
  - `results/fair_value_predictions.csv`
  - `results/execution_policy_signals.csv`

## Pause / resume

- Pause worker: Render dashboard -> service -> Suspend.
- Resume worker: dashboard -> Resume.

## Notes

- This avoids cloud object storage setup but is tied to one Render worker instance.
- If worker is redeployed, data remains because of the persistent disk.
- If you later want multi-service scale, we can add external object storage and split jobs.

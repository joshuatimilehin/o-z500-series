# PHASE 2: News Sentiment Integration + Arb Spike Signal

## What Was Added

The project now includes a full Phase 2 pipeline that combines technical indicators, crypto news sentiment, and live Polymarket arbitrage-spike features.

New files:
- `news_scraper.py`
- `sentiment_analyzer.py`
- `sentiment_feature_integrator.py`
- `arb_scanner.py`
- `arb_feature_integrator.py`
- `main_pipeline_phase2.py`

## Pipeline Flow

1. Collect 7 days of BTC 1-minute candles and resample to 5-minute.
2. Create technical features.
3. Collect crypto news (CoinDesk, Cointelegraph, Decrypt RSS; optional CryptoPanic API).
4. Score sentiment per article using VADER.
5. Scan live Polymarket books for cross-outcome arbitrage opportunities.
6. Aggregate sentiment features and arb-spike features into rolling windows.
7. Train model and run backtest.
8. Save all outputs to `data/`, `models/`, and `results/`.

## Required Environment

- Python `3.12.x` (recommended)
- Active virtual environment

## Install Dependencies

```powershell
pip install -r requirements.txt
```

## Run Commands

Phase 1 (technical-only):
```powershell
python main_pipeline.py
```

Phase 2 (technical + sentiment + arb features):
```powershell
python main_pipeline_phase2.py
```

Standalone arb scanner loop (quiet defaults):
```powershell
python arb_scanner.py --interval-sec 30 --min-gross-edge 0.005 --output data/arb_events.jsonl
```

Verbose scanner loop (print every cycle):
```powershell
python arb_scanner.py --verbose --interval-sec 30 --min-gross-edge 0.005 --output data/arb_events.jsonl
```

One-shot arb check:
```powershell
python arb_scanner.py --once
```

## Files Produced by Phase 2

- `data/news_raw_phase2.csv`
- `data/news_sentiment_phase2.csv`
- `data/arb_events.jsonl`
- `data/btc_5min_featured_phase2.csv`
- `models/btc_predictor_phase2.pkl`
- `results/backtest_results_phase2.json`
- `results/phase2_summary.json`

## Notes

- If `CRYPTOPANIC_API_KEY` is set in the environment, CryptoPanic data is included.
- Without the key, pipeline still runs from RSS sources.
- Arb features are derived from detected opportunity frequency/strength and can be improved by keeping scanner running continuously.
- Quiet mode is on by default; heartbeat prints every 20 cycles when no opportunities are found.

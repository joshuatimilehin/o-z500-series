from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt
import pandas as pd

from arb_feature_integrator import ArbFeatureIntegrator
from arb_scanner import PolymarketArbScanner, append_events
from data_collector import BybitDataCollector
from feature_engineer import FeatureEngineer
from news_scraper import NewsScraper
from sentiment_analyzer import SentimentAnalyzer
from sentiment_feature_integrator import SentimentFeatureIntegrator
from signal_theory_features import SignalTheoryFeatureEngineer


def create_dirs() -> None:
    for d in ["data", "results"]:
        Path(d).mkdir(parents=True, exist_ok=True)


def _fetch_binance_5m(days: int) -> pd.DataFrame:
    ex = ccxt.binance({"enableRateLimit": True, "timeout": 30000})
    symbol = "BTC/USDT"
    timeframe = "5m"
    limit = 1000

    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    rows: list[list[float]] = []

    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        since_ms = int(batch[-1][0]) + 5 * 60_000

    if not rows:
        raise RuntimeError("No OHLCV rows from Binance fallback.")

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp"]).set_index("timestamp").sort_index()

    # Match project target construction.
    df["return_1"] = df["close"].pct_change()
    df["target"] = (df["return_1"].shift(-1) > 0).astype(int)
    df = df.dropna().copy()
    return df


def _fetch_price_base(days: int) -> tuple[pd.DataFrame, str]:
    # Primary path: 1m -> 5m resample (higher fidelity).
    try:
        collector = BybitDataCollector(symbol="BTC/USDT", timeframe="1m")
        df_1min = collector.fetch_historical_ohlcv(days=days)
        df_5min = collector.resample_to_5min(df_1min)
        df_5min = collector.calculate_returns(df_5min)
        return df_5min, "bybit_1m_resampled"
    except Exception:
        pass

    # Fallback path: direct 5m fetch for long windows.
    try:
        collector5 = BybitDataCollector(symbol="BTC/USDT", timeframe="5m")
        df_5 = collector5.fetch_historical_ohlcv(days=days)
        df_5 = collector5.calculate_returns(df_5)
        return df_5, "bybit_5m_direct"
    except Exception:
        pass

    # Final fallback: Binance 5m.
    df_binance = _fetch_binance_5m(days)
    return df_binance, "binance_5m_fallback"


def build_dataset(days: int, include_signal_theory: bool, run_arb_scan: bool) -> dict:
    create_dirs()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ingest_time = datetime.now(timezone.utc).isoformat()

    df_5min, price_source = _fetch_price_base(days)

    fe = FeatureEngineer(df_5min)
    df = fe.create_all_features()

    scraper = NewsScraper(cryptopanic_api_key=None)
    df_news = scraper.fetch_news(hours=days * 24)
    analyzer = SentimentAnalyzer()
    df_sentiment = analyzer.analyze_dataframe(df_news)

    sentiment_integrator = SentimentFeatureIntegrator()
    df = sentiment_integrator.integrate(df, df_sentiment)

    arb_file = Path("data/arb_events.jsonl")
    if run_arb_scan:
        scanner = PolymarketArbScanner(min_gross_edge=0.003, fee_buffer=0.001, slippage_buffer=0.001)
        try:
            events = scanner.scan_once()
            append_events(events, arb_file)
        except Exception:
            pass

    arb_integrator = ArbFeatureIntegrator()
    df_arb = arb_integrator.load_events(str(arb_file))
    df = arb_integrator.integrate(df, df_arb)

    signal_cols: list[str] = []
    mi_features: list[str] = []
    if include_signal_theory:
        st = SignalTheoryFeatureEngineer()
        df = st.integrate(df)
        signal_cols = [
            c
            for c in df.columns
            if c.startswith("sign_entropy_")
            or c.startswith("return_entropy_")
            or c
            in {
                "surprisal_ret",
                "signal_strength_30",
                "noise_level_30",
                "snr_proxy_30",
                "channel_capacity_proxy",
                "communication_efficiency",
                "mi_weighted_composite",
                "mi_topk_mean",
                "mi_topk_std",
            }
        ]
        mi_features = st.selected_mi_features

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")

    df["feature_time_utc"] = df.index
    df["ingest_time_utc"] = ingest_time
    df["run_id"] = run_id

    out_csv = Path(f"data/dataset_{run_id}.csv")
    df.to_csv(out_csv)

    try:
        out_parquet = Path(f"data/dataset_{run_id}.parquet")
        df.to_parquet(out_parquet)
        parquet_path = str(out_parquet)
    except Exception:
        parquet_path = "not_written (install pyarrow/fastparquet)"

    if not df_news.empty:
        df_news.to_csv(Path(f"data/news_raw_{run_id}.csv"), index=False)
    if not df_sentiment.empty:
        df_sentiment.to_csv(Path(f"data/news_sentiment_{run_id}.csv"), index=False)

    summary = {
        "run_id": run_id,
        "days": days,
        "price_source": price_source,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "news_articles": int(len(df_news)),
        "arb_events_total": int(len(df_arb)),
        "include_signal_theory": include_signal_theory,
        "signal_feature_count": int(len(signal_cols)),
        "mi_selected_features": mi_features,
        "dataset_csv": str(out_csv),
        "dataset_parquet": parquet_path,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    with Path(f"results/dataset_build_summary_{run_id}.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build timestamp-safe long-horizon dataset")
    parser.add_argument("--days", type=int, default=30, help="Historical days to pull from Bybit")
    parser.add_argument("--no-signal-theory", action="store_true", help="Disable signal theory features")
    parser.add_argument("--skip-arb-scan", action="store_true", help="Do not perform live arb scan before integration")
    args = parser.parse_args()

    summary = build_dataset(
        days=args.days,
        include_signal_theory=not args.no_signal_theory,
        run_arb_scan=not args.skip_arb_scan,
    )

    print("Dataset build complete")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

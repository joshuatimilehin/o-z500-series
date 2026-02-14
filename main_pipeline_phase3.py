"""
PHASE 3 PIPELINE - Technical + Sentiment + Arb + Signal Theory
Runs: Price Data -> Features -> Signal Theory Layer -> Model -> Backtest
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from arb_feature_integrator import ArbFeatureIntegrator
from arb_scanner import PolymarketArbScanner, append_events
from backtester import Backtester
from data_collector import BybitDataCollector
from feature_engineer import FeatureEngineer
from model_trainer import BTCPredictor
from news_scraper import NewsScraper
from sentiment_analyzer import SentimentAnalyzer
from sentiment_feature_integrator import SentimentFeatureIntegrator
from signal_theory_features import SignalTheoryFeatureEngineer


def create_directories() -> None:
    for d in ["data", "models", "results"]:
        Path(d).mkdir(parents=True, exist_ok=True)


def load_json_if_exists(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main() -> dict:
    print("=" * 60)
    print("POLYMARKET BTC 5-MINUTE PREDICTOR - PHASE 3")
    print("Technical + Sentiment + Arb + Signal Theory")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    create_directories()

    print("\n" + "=" * 60)
    print("STEP 1: PRICE DATA COLLECTION")
    print("=" * 60)
    collector = BybitDataCollector(symbol="BTC/USDT", timeframe="1m")
    df_1min = collector.fetch_historical_ohlcv(days=7)
    df_5min = collector.resample_to_5min(df_1min)
    df_5min = collector.calculate_returns(df_5min)
    collector.save_data(df_5min, "btc_5min_historical_phase3.csv")
    print(f"Price candles (5m): {len(df_5min)}")

    print("\n" + "=" * 60)
    print("STEP 2: TECHNICAL FEATURES")
    print("=" * 60)
    fe = FeatureEngineer(df_5min)
    df_tech = fe.create_all_features()
    print(f"Technical features: {len(fe.get_feature_columns())}")

    print("\n" + "=" * 60)
    print("STEP 3: NEWS COLLECTION + SENTIMENT")
    print("=" * 60)
    cp_key = os.getenv("CRYPTOPANIC_API_KEY")
    scraper = NewsScraper(cryptopanic_api_key=cp_key)
    df_news = scraper.fetch_news(hours=24 * 7)
    df_news.to_csv("data/news_raw_phase3.csv", index=False)
    print(f"News articles collected: {len(df_news)}")

    analyzer = SentimentAnalyzer()
    df_sentiment = analyzer.analyze_dataframe(df_news)
    df_sentiment.to_csv("data/news_sentiment_phase3.csv", index=False)

    print("\n" + "=" * 60)
    print("STEP 4: ARB SCAN + BASE FEATURE INTEGRATION")
    print("=" * 60)
    arb_output = Path("data/arb_events.jsonl")
    scanner = PolymarketArbScanner(min_gross_edge=0.003, fee_buffer=0.001, slippage_buffer=0.001)
    try:
        arb_events = scanner.scan_once()
        append_events(arb_events, arb_output)
        print(f"Arb opportunities logged this run: {len(arb_events)}")
    except Exception as exc:
        print(f"Arb scan failed (continuing): {exc}")

    sentiment_integrator = SentimentFeatureIntegrator()
    df_base = sentiment_integrator.integrate(df_tech, df_sentiment)

    arb_integrator = ArbFeatureIntegrator()
    df_arb = arb_integrator.load_events(str(arb_output))
    df_base = arb_integrator.integrate(df_base, df_arb)

    print("\n" + "=" * 60)
    print("STEP 5: SIGNAL THEORY FEATURES")
    print("=" * 60)
    signal_engineer = SignalTheoryFeatureEngineer()
    df_featured = signal_engineer.integrate(df_base)
    df_featured.to_csv("data/btc_5min_featured_phase3.csv")

    signal_cols = [
        c
        for c in df_featured.columns
        if c.startswith("sign_entropy_")
        or c.startswith("return_entropy_")
        or c in {
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

    print(f"Signal theory features: {len(signal_cols)}")
    print(f"MI selected features: {signal_engineer.selected_mi_features[:8]}")
    print(f"Rows after Phase 3 integration: {len(df_featured)}")

    print("\n" + "=" * 60)
    print("STEP 6: TRAINING + BACKTEST")
    print("=" * 60)
    predictor = BTCPredictor()
    X_train, X_test, y_train, y_test = predictor.prepare_data(df_featured, test_size=0.2)
    predictor.train(X_train, y_train)
    metrics = predictor.evaluate(X_test, y_test)
    predictor.save_model("models/btc_predictor_phase3.pkl")

    y_pred = predictor.predict(X_test)
    y_pred_proba = predictor.predict_proba(X_test)

    backtester = Backtester(initial_capital=1000, position_size=0.02, confidence_threshold=0.6)
    df_test = df_featured.iloc[-len(X_test):]
    results = backtester.run_backtest(df_test, y_pred, y_pred_proba)
    backtester.print_results(results)
    backtester.save_results(results, "results/backtest_results_phase3.json")

    phase1 = load_json_if_exists("results/backtest_results.json")
    phase2 = load_json_if_exists("results/backtest_results_phase2.json")

    summary = {
        "phase3_metrics": metrics,
        "phase3_backtest": results,
        "phase1_backtest": phase1,
        "phase2_backtest": phase2,
        "news_articles": int(len(df_news)),
        "arb_events_total": int(len(df_arb)),
        "signal_feature_count": int(len(signal_cols)),
        "mi_selected_features": signal_engineer.selected_mi_features,
        "timestamp": datetime.now().isoformat(),
    }

    with open("results/phase3_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print("PHASE 3 COMPLETE")
    print("=" * 60)
    print(f"Model Accuracy: {metrics['accuracy']*100:.2f}%")
    print(f"Win Rate: {results['win_rate']*100:.2f}%")
    print(f"Total Return: {results['total_return']*100:.2f}%")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")

    if phase2:
        print("\nPhase 2 comparison:")
        print(f"Phase 2 Accuracy: {phase2.get('accuracy', 0.0)*100:.2f}%")
        print(f"Phase 2 Return: {phase2.get('total_return', 0.0)*100:.2f}%")

    print("\nOutputs:")
    print(" - data/btc_5min_featured_phase3.csv")
    print(" - models/btc_predictor_phase3.pkl")
    print(" - results/backtest_results_phase3.json")
    print(" - results/phase3_summary.json")

    return summary


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()

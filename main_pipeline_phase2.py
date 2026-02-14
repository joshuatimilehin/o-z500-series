"""
PHASE 2 PIPELINE - Technical + News Sentiment + Arb Signal
Runs: Price Data -> Technical Features -> News Sentiment -> Arb Spike Features -> Model -> Backtest
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


def create_directories() -> None:
    for d in ["data", "models", "results"]:
        Path(d).mkdir(parents=True, exist_ok=True)


def maybe_load_baseline(path: str = "results/backtest_results.json") -> dict | None:
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
    print("POLYMARKET BTC 5-MINUTE PREDICTOR - PHASE 2")
    print("Technical + News Sentiment + Arb Spike Signal")
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
    collector.save_data(df_5min, "btc_5min_historical_phase2.csv")
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
    df_news.to_csv("data/news_raw_phase2.csv", index=False)
    print(f"News articles collected: {len(df_news)}")

    analyzer = SentimentAnalyzer()
    df_sentiment = analyzer.analyze_dataframe(df_news)
    df_sentiment.to_csv("data/news_sentiment_phase2.csv", index=False)
    print("Sentiment analysis complete")

    print("\n" + "=" * 60)
    print("STEP 4: ARB SCAN + FEATURE INTEGRATION")
    print("=" * 60)

    arb_output = Path("data/arb_events.jsonl")
    scanner = PolymarketArbScanner(min_gross_edge=0.003, fee_buffer=0.001, slippage_buffer=0.001)
    try:
        arb_events = scanner.scan_once()
        append_events(arb_events, arb_output)
        print(f"Arb opportunities logged this run: {len(arb_events)}")
    except Exception as exc:
        print(f"Arb scan failed (continuing with existing/no arb file): {exc}")

    sentiment_integrator = SentimentFeatureIntegrator()
    df_featured = sentiment_integrator.integrate(df_tech, df_sentiment)

    arb_integrator = ArbFeatureIntegrator()
    df_arb = arb_integrator.load_events(str(arb_output))
    df_featured = arb_integrator.integrate(df_featured, df_arb)

    df_featured.to_csv("data/btc_5min_featured_phase2.csv")

    sentiment_cols = [c for c in df_featured.columns if "sentiment" in c or "news_count" in c or "ratio_" in c]
    arb_cols = [c for c in df_featured.columns if c.startswith("arb_")]
    print(f"Integrated sentiment features: {len(sentiment_cols)}")
    print(f"Integrated arb features: {len(arb_cols)}")
    print(f"Total rows after integration: {len(df_featured)}")

    print("\n" + "=" * 60)
    print("STEP 5: TRAINING + BACKTEST")
    print("=" * 60)
    predictor = BTCPredictor()
    X_train, X_test, y_train, y_test = predictor.prepare_data(df_featured, test_size=0.2)
    predictor.train(X_train, y_train)
    metrics = predictor.evaluate(X_test, y_test)
    predictor.save_model("models/btc_predictor_phase2.pkl")

    y_pred = predictor.predict(X_test)
    y_pred_proba = predictor.predict_proba(X_test)
    backtester = Backtester(initial_capital=1000, position_size=0.02, confidence_threshold=0.6)
    df_test = df_featured.iloc[-len(X_test):]
    results = backtester.run_backtest(df_test, y_pred, y_pred_proba)
    backtester.print_results(results)
    backtester.save_results(results, "results/backtest_results_phase2.json")

    baseline = maybe_load_baseline()
    summary = {
        "phase2_metrics": metrics,
        "phase2_backtest": results,
        "news_articles": int(len(df_news)),
        "sentiment_feature_count": int(len(sentiment_cols)),
        "arb_feature_count": int(len(arb_cols)),
        "arb_events_total": int(len(df_arb)),
        "baseline_phase1": baseline,
        "timestamp": datetime.now().isoformat(),
    }
    with open("results/phase2_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print("PHASE 2 COMPLETE")
    print("=" * 60)
    print(f"Model Accuracy: {metrics['accuracy']*100:.2f}%")
    print(f"Win Rate: {results['win_rate']*100:.2f}%")
    print(f"Total Return: {results['total_return']*100:.2f}%")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")

    if baseline:
        print("\nPhase 1 comparison from results/backtest_results.json")
        print(f"Phase 1 Accuracy: {baseline.get('accuracy', 0.0)*100:.2f}%")
        print(f"Phase 1 Win Rate: {baseline.get('win_rate', 0.0)*100:.2f}%")
        print(f"Phase 1 Return: {baseline.get('total_return', 0.0)*100:.2f}%")

    print("\nOutputs:")
    print(" - data/news_raw_phase2.csv")
    print(" - data/news_sentiment_phase2.csv")
    print(" - data/arb_events.jsonl")
    print(" - data/btc_5min_featured_phase2.csv")
    print(" - models/btc_predictor_phase2.pkl")
    print(" - results/backtest_results_phase2.json")
    print(" - results/phase2_summary.json")

    return summary


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()

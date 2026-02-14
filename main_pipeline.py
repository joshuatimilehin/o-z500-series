"""
MAIN PIPELINE - Polymarket BTC Predictor POC
Runs complete workflow: Data → Features → Model → Backtest
"""

import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data_collector import BybitDataCollector
from feature_engineer import FeatureEngineer
from model_trainer import BTCPredictor
from backtester import Backtester

import warnings
warnings.filterwarnings('ignore')

def create_directories():
    """Create necessary directories"""
    dirs = ['data', 'models', 'results']
    for d in dirs:
        os.makedirs(d, exist_ok=True)

def main():
    """
    Main pipeline execution
    
    PHASE 1: PROOF OF CONCEPT
    - Collect 7 days of BTC data from Bybit
    - Engineer technical features
    - Train XGBoost model
    - Backtest on historical data
    - Evaluate if strategy is viable
    """
    
    print("="*60)
    print("POLYMARKET BTC 5-MINUTE PREDICTOR - PROOF OF CONCEPT")
    print("="*60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Create directories
    create_directories()
    
    # ==========================================
    # STEP 1: DATA COLLECTION
    # ==========================================
    print("\n" + "="*60)
    print("STEP 1: DATA COLLECTION")
    print("="*60)
    
    collector = BybitDataCollector(symbol='BTC/USDT', timeframe='1m')
    
    print("\nFetching historical data from Bybit...")
    df_1min = collector.fetch_historical_ohlcv(days=7)
    
    print("\nResampling to 5-minute candles...")
    df_5min = collector.resample_to_5min(df_1min)
    
    print("\nCalculating returns and direction...")
    df_5min = collector.calculate_returns(df_5min)
    
    collector.save_data(df_5min, 'btc_5min_historical.csv')
    
    print(f"\n✅ Data collection complete: {len(df_5min)} 5-minute candles")
    
    # ==========================================
    # STEP 2: FEATURE ENGINEERING
    # ==========================================
    print("\n" + "="*60)
    print("STEP 2: FEATURE ENGINEERING")
    print("="*60)
    
    fe = FeatureEngineer(df_5min)
    df_featured = fe.create_all_features()
    
    feature_cols = fe.get_feature_columns()
    print(f"\n✅ Created {len(feature_cols)} features")
    
    # Save featured data
    df_featured.to_csv('data/btc_5min_featured.csv')
    
    # ==========================================
    # STEP 3: MODEL TRAINING
    # ==========================================
    print("\n" + "="*60)
    print("STEP 3: MODEL TRAINING")
    print("="*60)
    
    predictor = BTCPredictor()
    
    # Prepare data
    X_train, X_test, y_train, y_test = predictor.prepare_data(df_featured, test_size=0.2)
    
    # Train model
    predictor.train(X_train, y_train)
    
    # Evaluate
    metrics = predictor.evaluate(X_test, y_test)
    
    # Show top features
    print("\n📊 TOP 10 MOST IMPORTANT FEATURES:")
    top_features = predictor.get_top_features(10)
    print(top_features.to_string(index=False))
    
    # Save model
    predictor.save_model('models/btc_predictor.pkl')
    
    # ==========================================
    # STEP 4: BACKTESTING
    # ==========================================
    print("\n" + "="*60)
    print("STEP 4: BACKTESTING")
    print("="*60)
    
    # Get predictions for test set
    y_pred = predictor.predict(X_test)
    y_pred_proba = predictor.predict_proba(X_test)
    
    # Run backtest
    backtester = Backtester(
        initial_capital=1000,
        position_size=0.02,  # 2% per trade
        confidence_threshold=0.6  # Only trade when >60% confident
    )
    
    # Get corresponding price data for test period
    df_test = df_featured.iloc[-len(X_test):]
    
    results = backtester.run_backtest(df_test, y_pred, y_pred_proba)
    
    # Print results
    backtester.print_results(results)
    
    # Save results
    backtester.save_results(results, 'results/backtest_results.json')
    
    # ==========================================
    # FINAL SUMMARY
    # ==========================================
    print("\n" + "="*60)
    print("PROOF OF CONCEPT COMPLETE")
    print("="*60)
    
    print(f"\n📊 KEY METRICS:")
    print(f"Model Accuracy: {metrics['accuracy']*100:.2f}%")
    print(f"Backtest Accuracy: {results['accuracy']*100:.2f}%")
    print(f"Win Rate: {results['win_rate']*100:.2f}%")
    print(f"Total Return: {results['total_return']*100:.2f}%")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    
    print(f"\n🎯 NEXT STEPS:")
    
    if results['accuracy'] >= 0.60:
        print("✅ Strategy shows promise!")
        print("   → Proceed to Phase 2: Add news sentiment")
        print("   → Expand to ETH and SOL")
        print("   → Deploy to cloud for paper trading")
    elif results['accuracy'] >= 0.55:
        print("⚠️  Strategy is marginal")
        print("   → Try different features or model architectures")
        print("   → Add news sentiment to improve accuracy")
        print("   → Optimize hyperparameters")
    else:
        print("❌ Strategy needs improvement")
        print("   → Revisit feature engineering")
        print("   → Try different prediction windows")
        print("   → Add external data sources (news, social sentiment)")
    
    print(f"\n✅ All outputs saved to:")
    print(f"   - data/btc_5min_featured.csv")
    print(f"   - models/btc_predictor.pkl")
    print(f"   - results/backtest_results.json")
    
    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    return {
        'metrics': metrics,
        'backtest': results,
        'predictor': predictor
    }


if __name__ == "__main__":
    try:
        results = main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

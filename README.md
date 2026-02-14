# Polymarket BTC 5-Minute Predictor - POC

**Predict BTC price direction for Polymarket's 5-minute markets using Machine Learning**

## Project Overview

This is a Proof of Concept (POC) for an ML-powered trading bot that predicts BTC price movements in 5-minute intervals for Polymarket betting markets.

**Current Phase:** Phase 1 - Technical Analysis Only  
**Target Accuracy:** 90% (stretch), 60-70% (realistic for profitability)

---

## Features

### Phase 1 (Current)
- ✅ Bybit BTC/USDT data collection
- ✅ 40+ technical indicators (RSI, MACD, Bollinger Bands, etc.)
- ✅ XGBoost classification model
- ✅ Backtesting engine with performance metrics
- ✅ Feature importance analysis

### Coming Soon
- 🔜 News sentiment analysis
- 🔜 Social media sentiment (Twitter, Reddit)
- 🔜 ETH and SOL support
- 🔜 Real-time trading execution
- 🔜 Cloud deployment

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the POC

```bash
python main_pipeline.py
```

This will:
1. Fetch 7 days of BTC data from Bybit
2. Calculate 40+ technical features
3. Train an XGBoost model
4. Backtest on historical data
5. Output performance metrics

### 3. Review Results

Check these files after running:
- `data/btc_5min_featured.csv` - Featured dataset
- `models/btc_predictor.pkl` - Trained model
- `results/backtest_results.json` - Performance metrics

---

## Project Structure

```
polymarket_bot/
├── main_pipeline.py        # Main execution script
├── config.py               # Configuration settings
├── data_collector.py       # Bybit data fetching
├── feature_engineer.py     # Technical indicator calculation
├── model_trainer.py        # XGBoost model training
├── backtester.py          # Backtesting engine
├── requirements.txt        # Python dependencies
├── data/                   # Data storage
├── models/                 # Trained models
└── results/               # Backtest results
```

---

## How It Works

### Data Collection
- Fetches 1-minute candles from Bybit
- Resamples to 5-minute intervals
- Calculates returns and direction (up/down)

### Feature Engineering
Creates 40+ features including:
- **Momentum**: RSI, MACD, price rate of change
- **Trend**: Moving averages, crossovers
- **Volatility**: Bollinger Bands, ATR
- **Volume**: Relative volume, volume trends
- **Price Action**: Candle patterns, shadows
- **Time**: Hour of day, day of week

### Model Training
- Algorithm: XGBoost Classifier
- Target: Binary (0=down, 1=up)
- Validation: Time-series split (no shuffle)
- Metrics: Accuracy, Precision, Recall, F1

### Backtesting
- Simulates trades on historical data
- Capital management: 2% position size
- Confidence threshold: 60%
- Outputs: Win rate, P&L, Sharpe ratio, max drawdown

---

## Expected Results (Phase 1)

**Realistic Targets:**
- Accuracy: 55-65%
- Win Rate: 50-60%
- Positive Sharpe Ratio

**Why not 90%?**
- Technical indicators alone are limited
- 5-minute timeframe is very noisy
- Need news sentiment for higher accuracy

**Phase 2 additions** (news + social sentiment) should push accuracy to 65-75%.

---

## Next Steps After POC

### If Results Are Promising (>60% accuracy):
1. ✅ Add news sentiment analysis
2. ✅ Expand to ETH and SOL
3. ✅ Deploy to GCP for 24/7 operation
4. ✅ Paper trading with real Polymarket API
5. ✅ Live trading with small capital

### If Results Are Marginal (55-60% accuracy):
1. 🔧 Optimize hyperparameters
2. 🔧 Try ensemble models (LSTM + XGBoost)
3. 🔧 Add news sentiment immediately
4. 🔧 Experiment with different timeframes

### If Results Are Poor (<55% accuracy):
1. 🔄 Revisit feature engineering
2. 🔄 Try different prediction windows
3. 🔄 Add external data sources
4. 🔄 Consider deep learning (LSTM/Transformers)

---

## Configuration

Edit `config.py` to customize:
- Trading symbol
- Timeframe
- Model parameters
- Backtesting settings
- API keys (when ready for production)

---

## Requirements

- Python 3.8+
- Internet connection (for data fetching)
- ~100MB disk space for data

---

## Team

**Maxwell** - Technical Director / Strategic Architect  
**MAX** - AI Implementation Agent

---

## Status: PHASE 1 POC COMPLETE ✅

Ready to run and evaluate!

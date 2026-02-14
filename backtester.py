from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


class Backtester:
    def __init__(self, initial_capital: float = 1000.0, position_size: float = 0.02, confidence_threshold: float = 0.6) -> None:
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.confidence_threshold = confidence_threshold

    def run_backtest(self, df_test: pd.DataFrame, y_pred: np.ndarray, y_pred_proba: np.ndarray) -> dict:
        if len(df_test) == 0:
            raise ValueError("df_test is empty")

        true = df_test["target"].astype(int).values
        conf = np.max(y_pred_proba, axis=1)
        take_trade = conf >= self.confidence_threshold

        pnl = []
        wins = 0
        trades = 0
        equity = self.initial_capital
        equity_curve = [equity]

        for i in range(len(true)):
            if not take_trade[i]:
                equity_curve.append(equity)
                continue

            trades += 1
            stake = equity * self.position_size
            correct = int(y_pred[i] == true[i])
            ret = 0.02 if correct else -0.02
            trade_pnl = stake * ret
            equity += trade_pnl
            pnl.append(trade_pnl)
            wins += correct
            equity_curve.append(equity)

        pnl_arr = np.array(pnl, dtype=float) if pnl else np.array([0.0])
        returns = np.diff(np.array(equity_curve)) / np.array(equity_curve[:-1]) if len(equity_curve) > 1 else np.array([0.0])
        sharpe = float((returns.mean() / returns.std()) * np.sqrt(252 * 24 * 12)) if returns.std() > 0 else 0.0

        results = {
            "accuracy": float((y_pred == true).mean()),
            "trades": int(trades),
            "win_rate": float(wins / trades) if trades else 0.0,
            "total_return": float((equity - self.initial_capital) / self.initial_capital),
            "sharpe_ratio": sharpe,
            "ending_capital": float(equity),
        }
        return results

    def print_results(self, results: dict) -> None:
        print("\nBacktest Results")
        print(f"Trades: {results['trades']}")
        print(f"Win rate: {results['win_rate']*100:.2f}%")
        print(f"Total return: {results['total_return']*100:.2f}%")
        print(f"Sharpe ratio: {results['sharpe_ratio']:.2f}")

    def save_results(self, results: dict, path: str) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        return out

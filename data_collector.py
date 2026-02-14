from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep

import ccxt
import pandas as pd


class BybitDataCollector:
    def __init__(self, symbol: str = "BTC/USDT", timeframe: str = "1m") -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.exchange = ccxt.bybit({"enableRateLimit": True, "timeout": 30000})
        self._market_id = self._to_bybit_symbol(symbol)

    def _to_bybit_symbol(self, symbol: str) -> str:
        # Spot symbols are e.g. BTC/USDT -> BTCUSDT for Bybit v5 endpoints.
        return symbol.split(":")[0].replace("/", "")

    def _timeframe_to_ms(self) -> int:
        mapping = {
            "1m": 60_000,
            "3m": 180_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
            "1d": 86_400_000,
        }
        if self.timeframe not in mapping:
            raise ValueError(f"Unsupported timeframe for collector: {self.timeframe}")
        return mapping[self.timeframe]

    def _to_bybit_interval(self) -> str:
        mapping = {
            "1m": "1",
            "3m": "3",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "4h": "240",
            "1d": "D",
        }
        if self.timeframe not in mapping:
            raise ValueError(f"Unsupported timeframe for Bybit interval: {self.timeframe}")
        return mapping[self.timeframe]

    def _fetch_bybit_kline_page(self, start_ms: int, end_ms: int, limit: int) -> list[list[str]]:
        params = {
            "category": "spot",
            "symbol": self._market_id,
            "interval": self._to_bybit_interval(),
            "start": str(start_ms),
            "end": str(end_ms),
            "limit": str(limit),
        }

        last_error = None
        for _ in range(3):
            try:
                if hasattr(self.exchange, "public_get_v5_market_kline"):
                    resp = self.exchange.public_get_v5_market_kline(params)
                else:
                    resp = self.exchange.publicGetV5MarketKline(params)
                return resp.get("result", {}).get("list", [])
            except Exception as exc:
                last_error = exc
                sleep(0.8)

        raise RuntimeError(f"Bybit kline request failed after retries: {last_error}")

    def fetch_historical_ohlcv(self, days: int = 7) -> pd.DataFrame:
        tf_ms = self._timeframe_to_ms()
        limit = 1000

        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_target_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

        all_rows: list[list[float]] = []
        seen_ts: set[int] = set()

        while end_ms > start_target_ms:
            window_start_ms = max(start_target_ms, end_ms - (limit * tf_ms))
            page = self._fetch_bybit_kline_page(window_start_ms, end_ms, limit)
            if not page:
                break

            min_ts = None
            for row in page:
                ts = int(row[0])
                if ts < start_target_ms:
                    continue
                if ts in seen_ts:
                    continue
                seen_ts.add(ts)

                all_rows.append([
                    ts,
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                ])

                if min_ts is None or ts < min_ts:
                    min_ts = ts

            if min_ts is None:
                break

            next_end_ms = min_ts - tf_ms
            if next_end_ms >= end_ms:
                break
            end_ms = next_end_ms

        if not all_rows:
            raise RuntimeError("No OHLCV data returned from exchange.")

        df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.drop_duplicates(subset=["timestamp"]).set_index("timestamp").sort_index()
        return df

    def resample_to_5min(self, df_1min: pd.DataFrame) -> pd.DataFrame:
        df_5 = (
            df_1min.resample("5min")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            })
            .dropna()
        )
        return df_5

    def calculate_returns(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["return_1"] = out["close"].pct_change()
        out["target"] = (out["return_1"].shift(-1) > 0).astype(int)
        out = out.dropna()
        return out

    def save_data(self, df: pd.DataFrame, filename: str) -> Path:
        out_path = Path("data") / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path)
        return out_path

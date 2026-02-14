from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import ccxt
import pandas as pd
import requests


GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"


@dataclass
class BuilderConfig:
    max_markets: int = 6000
    min_liquidity: float = 0.0
    include_active: bool = True
    include_closed: bool = True
    btc_only: bool = True
    fallback_mode: str = "auto"  # none | btc_timebounded | crypto_timebounded | auto
    fallback_min_rows: int = 120
    max_candidates: int = 250


class WindowTruthBuilder:
    def __init__(self, config: BuilderConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.bybit = ccxt.bybit({"enableRateLimit": True, "timeout": 30000})
        self.binance = ccxt.binance({"enableRateLimit": True, "timeout": 30000})
        self.price_cache: dict[int, float | None] = {}

    def _fetch_markets(self, active: bool | None, closed: bool | None) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        while offset < self.config.max_markets:
            limit = min(500, self.config.max_markets - offset)
            params: dict[str, Any] = {"limit": limit, "offset": offset}
            if active is not None:
                params["active"] = str(active).lower()
            if closed is not None:
                params["closed"] = str(closed).lower()
            resp = self.session.get(GAMMA_MARKETS_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            rows.extend(data)
            if len(data) < limit:
                break
            offset += limit
        return rows

    def fetch_candidate_markets(self) -> list[dict]:
        all_rows: list[dict] = []
        seen: set[str] = set()

        pulls: list[tuple[bool | None, bool | None]] = []
        if self.config.include_active:
            pulls.append((True, False))
        if self.config.include_closed:
            pulls.append((False, True))
        if not pulls:
            pulls.append((None, None))

        for active, closed in pulls:
            for m in self._fetch_markets(active, closed):
                mid = str(m.get("id"))
                if mid in seen:
                    continue
                seen.add(mid)
                if float(m.get("liquidityNum") or 0.0) < self.config.min_liquidity:
                    continue
                all_rows.append(m)

        return all_rows

    def _contains_btc(self, text: str) -> bool:
        t = text.lower()
        return ("bitcoin" in t) or (" btc" in f" {t}")

    def _contains_crypto(self, text: str) -> bool:
        t = text.lower()
        keys = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto", "doge", "xrp"]
        return any(k in t for k in keys)

    def _looks_window(self, text: str) -> bool:
        t = text.lower()
        window_re = re.compile(r"(\\b(minute|minutes|hour|hours|today|tonight)\\b|at\\s+\\d{1,2}:\\d{2}|\\bin\\s+\\d+\\s*(minute|minutes|hour|hours)\\b)")
        direction_re = re.compile(r"\b(up|down|higher|lower|above|below|rise|fall)\b")
        return bool(window_re.search(t) and direction_re.search(t))

    def _looks_timebounded(self, text: str) -> bool:
        t = text.lower()
        direction_re = re.compile(r"\b(up|down|higher|lower|above|below|rise|fall|hit)\b")
        if not direction_re.search(t):
            return False

        # Explicit temporal phrasing for bounded contracts.
        month_re = re.compile(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b"
        )
        date_like_re = re.compile(r"\b(20\d{2}|[0-1]?\d/[0-3]?\d(?:/[0-9]{2,4})?)\b")
        bounded_re = re.compile(r"\b(by|before|after|on|during|this week|this month|by end of)\b")

        return bool(month_re.search(t) or date_like_re.search(t) or bounded_re.search(t))

    def is_btc_window_market(self, m: dict) -> bool:
        q = str(m.get("question") or "")
        ev_title = str(((m.get("events") or [{}])[0].get("title") or ""))
        text = f"{q} {ev_title}"

        if self.config.btc_only and not self._contains_btc(text):
            return False

        # Strict: only explicit short time-window style contracts.
        return self._looks_window(text)

    def is_btc_timebounded_market(self, m: dict) -> bool:
        q = str(m.get("question") or "")
        ev_title = str(((m.get("events") or [{}])[0].get("title") or ""))
        text = f"{q} {ev_title}"
        return self._contains_btc(text) and self._looks_timebounded(text)

    def is_crypto_timebounded_market(self, m: dict) -> bool:
        q = str(m.get("question") or "")
        ev_title = str(((m.get("events") or [{}])[0].get("title") or ""))
        text = f"{q} {ev_title}"
        return self._contains_crypto(text) and self._looks_timebounded(text)

    def _select_candidates(self, markets: list[dict]) -> tuple[list[dict], str]:
        strict = [m for m in markets if self.is_btc_window_market(m)]
        if len(strict) >= self.config.fallback_min_rows or self.config.fallback_mode == "none":
            return strict, "strict_btc_window"

        fallback_order: list[str]
        if self.config.fallback_mode == "auto":
            fallback_order = ["btc_timebounded", "crypto_timebounded"]
        else:
            fallback_order = [self.config.fallback_mode]

        for i, mode in enumerate(fallback_order):
            if mode == "btc_timebounded":
                cand = [m for m in markets if self.is_btc_timebounded_market(m)]
            elif mode == "crypto_timebounded":
                cand = [m for m in markets if self.is_crypto_timebounded_market(m)]
            else:
                cand = []

            # Use this fallback if it reaches desired size or if it's the last attempt and non-empty.
            if len(cand) >= self.config.fallback_min_rows or (i == len(fallback_order) - 1 and len(cand) > 0):
                return cand, f"fallback_{mode}"

        return strict, "strict_btc_window"

    def _parse_json_list(self, value: Any) -> list:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
        return []

    def _token_mapping(self, m: dict) -> dict[str, Any]:
        outcomes = self._parse_json_list(m.get("outcomes"))
        token_ids = self._parse_json_list(m.get("clobTokenIds"))

        if len(outcomes) != 2 or len(token_ids) != 2:
            return {}

        o0 = str(outcomes[0]).strip().lower()
        o1 = str(outcomes[1]).strip().lower()

        yes_idx = 0
        no_idx = 1

        pairs = [
            ({"yes", "no"}, "yes"),
            ({"up", "down"}, "up"),
            ({"higher", "lower"}, "higher"),
            ({"above", "below"}, "above"),
        ]

        for allowed, yes_word in pairs:
            if {o0, o1} == allowed:
                yes_idx = 0 if o0 == yes_word else 1
                no_idx = 1 - yes_idx
                break

        return {
            "yes_label": outcomes[yes_idx],
            "no_label": outcomes[no_idx],
            "yes_token": token_ids[yes_idx],
            "no_token": token_ids[no_idx],
        }

    def _book_side(self, token_id: str) -> dict[str, float | None]:
        try:
            resp = self.session.get(CLOB_BOOK_URL, params={"token_id": token_id}, timeout=20)
            resp.raise_for_status()
            book = resp.json()
            asks = [float(x["price"]) for x in (book.get("asks") or [])]
            bids = [float(x["price"]) for x in (book.get("bids") or [])]

            best_ask = min(asks) if asks else None
            best_bid = max(bids) if bids else None
            spread = None
            if best_ask is not None and best_bid is not None:
                spread = best_ask - best_bid

            return {"best_ask": best_ask, "best_bid": best_bid, "spread": spread}
        except Exception:
            return {"best_ask": None, "best_bid": None, "spread": None}

    def _parse_strike_rule(self, question: str) -> tuple[str | None, float | None]:
        q = question.lower()
        comparator = None
        if any(k in q for k in ["above", "over", "higher than"]):
            comparator = "above"
        elif any(k in q for k in ["below", "under", "lower than"]):
            comparator = "below"

        m = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", question)
        if not m:
            return comparator, None

        strike = float(m.group(1).replace(",", ""))
        return comparator, strike

    def _resolved_yes(self, m: dict, yes_idx: int) -> float | None:
        outcome_prices = self._parse_json_list(m.get("outcomePrices"))
        if len(outcome_prices) != 2:
            return None

        try:
            p0 = float(outcome_prices[0])
            p1 = float(outcome_prices[1])
        except Exception:
            return None

        # Use hard resolution-like states only.
        if abs((p0 + p1) - 1.0) > 0.02:
            return None

        if p0 > 0.99 and p1 < 0.01:
            winner_idx = 0
        elif p1 > 0.99 and p0 < 0.01:
            winner_idx = 1
        else:
            return None

        return 1.0 if yes_idx == winner_idx else 0.0

    def _fetch_ohlcv_close(self, ex: ccxt.Exchange, symbol: str, ts_ms: int) -> float | None:
        since = max(0, ts_ms - 20 * 60_000)
        try:
            rows = ex.fetch_ohlcv(symbol, timeframe="1m", since=since, limit=50)
            if not rows:
                return None
            # last close at/near timestamp
            rows = sorted(rows, key=lambda r: r[0])
            close = rows[-1][4]
            return float(close)
        except Exception:
            return None

    def reference_price(self, end_dt: datetime) -> float | None:
        ts_ms = int(end_dt.timestamp() * 1000)
        minute_key = ts_ms // 60_000
        if minute_key in self.price_cache:
            return self.price_cache[minute_key]

        price = self._fetch_ohlcv_close(self.bybit, "BTC/USDT", ts_ms)
        if price is None:
            price = self._fetch_ohlcv_close(self.binance, "BTC/USDT", ts_ms)

        self.price_cache[minute_key] = price
        return price

    def build(self) -> pd.DataFrame:
        markets = self.fetch_candidate_markets()
        selected_markets, selection_mode = self._select_candidates(markets)
        selected_markets = sorted(
            selected_markets,
            key=lambda m: float(m.get("liquidityNum") or 0.0),
            reverse=True,
        )[: self.config.max_candidates]
        rows: list[dict[str, Any]] = []

        for m in selected_markets:
            token_map = self._token_mapping(m)
            if not token_map:
                continue

            yes_token = str(token_map["yes_token"])
            no_token = str(token_map["no_token"])

            yes_book = self._book_side(yes_token)
            no_book = self._book_side(no_token)

            end_raw = m.get("endDateIso") or m.get("endDate")
            try:
                end_dt = pd.to_datetime(end_raw, utc=True).to_pydatetime()
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            except Exception:
                end_dt = datetime.now(timezone.utc)

            now = datetime.now(timezone.utc)
            time_to_end_min = (end_dt - now).total_seconds() / 60.0

            question = str(m.get("question") or "")
            comparator, strike = self._parse_strike_rule(question)
            ref_price = self.reference_price(end_dt)

            mapping_outcomes = self._parse_json_list(m.get("outcomes"))
            yes_idx = 0
            if len(mapping_outcomes) == 2 and str(mapping_outcomes[1]) == str(token_map["yes_label"]):
                yes_idx = 1

            resolved_yes = self._resolved_yes(m, yes_idx)

            derived_yes = None
            if ref_price is not None and comparator and strike is not None:
                if comparator == "above":
                    derived_yes = 1.0 if ref_price > strike else 0.0
                elif comparator == "below":
                    derived_yes = 1.0 if ref_price < strike else 0.0

            if resolved_yes is not None:
                target = resolved_yes
                target_source = "resolved_market"
            elif derived_yes is not None:
                target = derived_yes
                target_source = "derived_from_strike"
            else:
                target = None
                target_source = "unlabeled"

            row = {
                "market_id": m.get("id"),
                "slug": m.get("slug"),
                "question": question,
                "event_title": ((m.get("events") or [{}])[0].get("title") or ""),
                "active": bool(m.get("active")),
                "closed": bool(m.get("closed")),
                "end_time_utc": end_dt.isoformat(),
                "time_to_end_min": float(time_to_end_min),
                "liquidity": float(m.get("liquidityNum") or 0.0),
                "volume24h": float(m.get("volume24hr") or 0.0),
                "yes_label": token_map["yes_label"],
                "no_label": token_map["no_label"],
                "yes_token": yes_token,
                "no_token": no_token,
                "bid_yes": yes_book["best_bid"],
                "ask_yes": yes_book["best_ask"],
                "spread_yes": yes_book["spread"],
                "bid_no": no_book["best_bid"],
                "ask_no": no_book["best_ask"],
                "spread_no": no_book["spread"],
                "mid_yes": None if yes_book["best_ask"] is None or yes_book["best_bid"] is None else (yes_book["best_ask"] + yes_book["best_bid"]) / 2,
                "mid_no": None if no_book["best_ask"] is None or no_book["best_bid"] is None else (no_book["best_ask"] + no_book["best_bid"]) / 2,
                "book_sum_ask": None if yes_book["best_ask"] is None or no_book["best_ask"] is None else yes_book["best_ask"] + no_book["best_ask"],
                "book_sum_bid": None if yes_book["best_bid"] is None or no_book["best_bid"] is None else yes_book["best_bid"] + no_book["best_bid"],
                "reference_btc_price": ref_price,
                "strike_price": strike,
                "comparator": comparator,
                "resolved_yes": resolved_yes,
                "derived_yes": derived_yes,
                "target": target,
                "target_source": target_source,
                "universe_mode": selection_mode,
                "snapshot_time_utc": now.isoformat(),
            }
            rows.append(row)

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("end_time_utc").reset_index(drop=True)
        return df


def save_outputs(df: pd.DataFrame, prefix: str = "window_truth") -> dict:
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("results").mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = Path(f"data/{prefix}_{run_id}.csv")
    df.to_csv(csv_path, index=False)

    labeled = int(df["target"].notna().sum()) if "target" in df.columns else 0
    summary = {
        "run_id": run_id,
        "rows": int(len(df)),
        "labeled_rows": labeled,
        "unlabeled_rows": int(len(df) - labeled),
        "csv": str(csv_path),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if "universe_mode" in df.columns and len(df):
        summary["universe_mode_counts"] = df["universe_mode"].value_counts().to_dict()

    summary_path = Path(f"results/{prefix}_summary_{run_id}.json")
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    summary["summary_json"] = str(summary_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC window truth dataset from Polymarket + exchange reference prices")
    parser.add_argument("--max-markets", type=int, default=6000)
    parser.add_argument("--max-candidates", type=int, default=250, help="Max selected markets to enrich with books/prices")
    parser.add_argument("--min-liquidity", type=float, default=0.0)
    parser.add_argument("--active-only", action="store_true")
    parser.add_argument("--closed-only", action="store_true")
    parser.add_argument("--include-non-btc", action="store_true")
    parser.add_argument(
        "--fallback-mode",
        default="auto",
        choices=["none", "btc_timebounded", "crypto_timebounded", "auto"],
        help="Fallback universe if strict BTC-window rows are scarce.",
    )
    parser.add_argument(
        "--fallback-min-rows",
        type=int,
        default=120,
        help="Minimum strict rows required before fallback activates.",
    )
    args = parser.parse_args()

    include_active = True
    include_closed = True
    if args.active_only:
        include_closed = False
    if args.closed_only:
        include_active = False

    cfg = BuilderConfig(
        max_markets=args.max_markets,
        max_candidates=args.max_candidates,
        min_liquidity=args.min_liquidity,
        include_active=include_active,
        include_closed=include_closed,
        btc_only=not args.include_non_btc,
        fallback_mode=args.fallback_mode,
        fallback_min_rows=args.fallback_min_rows,
    )

    builder = WindowTruthBuilder(cfg)
    df = builder.build()
    summary = save_outputs(df)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

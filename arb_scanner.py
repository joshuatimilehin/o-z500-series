from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"


class PolymarketArbScanner:
    def __init__(
        self,
        min_gross_edge: float = 0.005,
        fee_buffer: float = 0.001,
        slippage_buffer: float = 0.001,
        min_liquidity: float = 1000.0,
        market_limit: int = 120,
        timeout_sec: int = 15,
    ) -> None:
        self.min_gross_edge = min_gross_edge
        self.fee_buffer = fee_buffer
        self.slippage_buffer = slippage_buffer
        self.min_liquidity = min_liquidity
        self.market_limit = market_limit
        self.session = requests.Session()
        self.timeout_sec = timeout_sec

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

    def _get_markets(self) -> list[dict]:
        resp = self.session.get(
            GAMMA_MARKETS_URL,
            params={"active": "true", "closed": "false", "limit": self.market_limit},
            timeout=self.timeout_sec,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_best_ask(self, token_id: str) -> tuple[float | None, float]:
        resp = self.session.get(CLOB_BOOK_URL, params={"token_id": token_id}, timeout=self.timeout_sec)
        resp.raise_for_status()
        book = resp.json()
        asks = book.get("asks", [])
        if not asks:
            return None, 0.0

        best = min(float(a["price"]) for a in asks)
        best_size = sum(float(a["size"]) for a in asks if abs(float(a["price"]) - best) < 1e-9)
        return best, best_size

    def scan_once(self) -> list[dict]:
        opportunities: list[dict] = []
        for m in self._get_markets():
            if not m.get("acceptingOrders"):
                continue

            liquidity = float(m.get("liquidityNum") or 0.0)
            if liquidity < self.min_liquidity:
                continue

            token_ids = self._parse_json_list(m.get("clobTokenIds"))
            outcomes = self._parse_json_list(m.get("outcomes"))
            if len(token_ids) != 2 or len(outcomes) != 2:
                continue

            try:
                ask_a, size_a = self._get_best_ask(token_ids[0])
                ask_b, size_b = self._get_best_ask(token_ids[1])
            except Exception:
                continue

            if ask_a is None or ask_b is None:
                continue

            gross_cost = ask_a + ask_b
            gross_edge = 1.0 - gross_cost
            net_edge = gross_edge - self.fee_buffer - self.slippage_buffer

            if gross_edge < self.min_gross_edge:
                continue

            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "market_id": m.get("id"),
                "slug": m.get("slug"),
                "question": m.get("question"),
                "outcome_a": outcomes[0],
                "outcome_b": outcomes[1],
                "token_a": token_ids[0],
                "token_b": token_ids[1],
                "ask_a": ask_a,
                "ask_b": ask_b,
                "best_pair_size": min(size_a, size_b),
                "gross_cost": gross_cost,
                "gross_edge": gross_edge,
                "net_edge": net_edge,
                "liquidity": liquidity,
            }
            opportunities.append(event)

        opportunities.sort(key=lambda x: x["net_edge"], reverse=True)
        return opportunities


def append_events(events: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def print_top(events: list[dict], top_n: int = 5) -> None:
    print(f"Found {len(events)} opportunities; top {min(top_n, len(events))}:")
    for e in events[:top_n]:
        print(
            f"edge={e['net_edge']:.4f} gross={e['gross_edge']:.4f} "
            f"cost={e['gross_cost']:.4f} size={e['best_pair_size']:.2f} | {e['question']}"
        )


def run_loop(args: argparse.Namespace) -> None:
    scanner = PolymarketArbScanner(
        min_gross_edge=args.min_gross_edge,
        fee_buffer=args.fee_buffer,
        slippage_buffer=args.slippage_buffer,
        min_liquidity=args.min_liquidity,
        market_limit=args.market_limit,
        timeout_sec=args.timeout_sec,
    )

    output_path = Path(args.output)
    i = 0
    while True:
        i += 1
        try:
            events = scanner.scan_once()
            append_events(events, output_path)

            should_heartbeat = (i % max(1, args.heartbeat_every) == 0)
            if events:
                print(f"[{i}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print_top(events, top_n=args.top_n)
            elif args.once:
                print(f"[{i}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} No arb opportunities found.")
            elif (not args.quiet) or should_heartbeat:
                print(
                    f"[{i}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                    f"No arb opportunities found."
                )
        except Exception as exc:
            print(f"Scan error: {exc}")

        if args.once:
            break
        time.sleep(args.interval_sec)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Polymarket cross-outcome arbitrage scanner")
    p.add_argument("--once", action="store_true", help="Run one scan and exit")
    p.add_argument("--interval-sec", type=int, default=30, help="Polling interval for loop mode")
    p.add_argument("--market-limit", type=int, default=120, help="How many active markets to inspect")
    p.add_argument("--min-liquidity", type=float, default=1000.0, help="Minimum market liquidity")
    p.add_argument("--min-gross-edge", type=float, default=0.005, help="Min raw edge before costs")
    p.add_argument("--fee-buffer", type=float, default=0.001, help="Cost buffer for fees")
    p.add_argument("--slippage-buffer", type=float, default=0.001, help="Cost buffer for slippage")
    p.add_argument("--timeout-sec", type=int, default=15, help="HTTP timeout")
    p.add_argument("--top-n", type=int, default=5, help="Top opportunities to print")
    p.add_argument("--output", default="data/arb_events.jsonl", help="JSONL output for detected opportunities")
    p.add_argument(
        "--quiet",
        action="store_true",
        default=True,
        help="Only print when opportunities are found (plus heartbeat).",
    )
    p.add_argument(
        "--heartbeat-every",
        type=int,
        default=20,
        help="Print a heartbeat every N cycles when quiet mode is on.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Disable quiet mode and print every cycle.",
    )
    return p


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    if args.verbose:
        args.quiet = False
    run_loop(args)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

import feedparser
import pandas as pd
import requests


@dataclass
class NewsSource:
    name: str
    kind: str
    url: str


class NewsScraper:
    def __init__(self, cryptopanic_api_key: str | None = None, timeout: int = 20) -> None:
        self.cryptopanic_api_key = cryptopanic_api_key
        self.timeout = timeout
        self.sources = [
            NewsSource("CoinDesk", "rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
            NewsSource("Cointelegraph", "rss", "https://cointelegraph.com/rss"),
            NewsSource("Decrypt", "rss", "https://decrypt.co/feed"),
        ]

    def _parse_date(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _fetch_rss(self, source: NewsSource, since_dt: datetime) -> list[dict]:
        feed = feedparser.parse(source.url)
        out: list[dict] = []
        for e in getattr(feed, "entries", []):
            published = self._parse_date(getattr(e, "published", None)) or self._parse_date(getattr(e, "updated", None))
            if published is None or published < since_dt:
                continue
            title = getattr(e, "title", "") or ""
            summary = getattr(e, "summary", "") or ""
            url = getattr(e, "link", "") or ""
            out.append(
                {
                    "source": source.name,
                    "published_at": published,
                    "title": title.strip(),
                    "summary": summary.strip(),
                    "url": url.strip(),
                }
            )
        return out

    def _fetch_cryptopanic(self, since_dt: datetime) -> list[dict]:
        if not self.cryptopanic_api_key:
            return []

        resp = requests.get(
            "https://cryptopanic.com/api/v1/posts/",
            params={
                "auth_token": self.cryptopanic_api_key,
                "currencies": "BTC",
                "kind": "news",
                "public": "true",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()

        out: list[dict] = []
        for row in payload.get("results", []):
            dt_text = row.get("published_at")
            try:
                published = datetime.fromisoformat(dt_text.replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                continue
            if published < since_dt:
                continue
            title = row.get("title") or ""
            out.append(
                {
                    "source": "CryptoPanic",
                    "published_at": published,
                    "title": title.strip(),
                    "summary": "",
                    "url": (row.get("url") or "").strip(),
                }
            )
        return out

    def fetch_news(self, hours: int = 24) -> pd.DataFrame:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows: list[dict] = []

        for src in self.sources:
            if src.kind == "rss":
                try:
                    rows.extend(self._fetch_rss(src, since_dt))
                except Exception:
                    continue

        try:
            rows.extend(self._fetch_cryptopanic(since_dt))
        except Exception:
            pass

        if not rows:
            return pd.DataFrame(columns=["source", "published_at", "title", "summary", "url"])

        df = pd.DataFrame(rows)
        df = df.drop_duplicates(subset=["title", "published_at", "source"])
        df = df.sort_values("published_at").reset_index(drop=True)
        return df

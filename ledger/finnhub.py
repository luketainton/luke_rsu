"""Fetch and cache current USD stock quotes from Finnhub."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.utils import timezone

from .models import StockPrice

FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


class FinnhubQuoteUnavailable(ValueError):
    """Raised when Finnhub cannot provide a usable quote."""


def is_configured():
    return bool(os.environ.get("FINNHUB_API_KEY"))


@dataclass(frozen=True)
class FinnhubQuote:
    ticker: str
    usd_price: Decimal
    quoted_at: datetime
    source_url: str


def fetch_quote(ticker):
    token = os.environ.get("FINNHUB_API_KEY")
    if not token:
        raise FinnhubQuoteUnavailable(
            "Finnhub is not configured. Set FINNHUB_API_KEY on the server."
        )
    query = urlencode({"symbol": ticker, "token": token})
    try:
        with urlopen(f"{FINNHUB_QUOTE_URL}?{query}", timeout=15) as response:
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise FinnhubQuoteUnavailable(f"Finnhub could not provide a quote for {ticker}.") from exc
    try:
        price = Decimal(str(payload["c"]))
        quoted_at = datetime.fromtimestamp(int(payload["t"]), UTC)
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise FinnhubQuoteUnavailable(f"Finnhub returned an invalid quote for {ticker}.") from exc
    if price <= 0 or quoted_at.year < 2000:
        raise FinnhubQuoteUnavailable(f"Finnhub returned an invalid quote for {ticker}.")
    return FinnhubQuote(
        ticker=ticker,
        usd_price=price,
        quoted_at=quoted_at,
        source_url=f"{FINNHUB_QUOTE_URL}?{urlencode({'symbol': ticker})}",
    )


def refresh_live_price(workspace, ticker, now=None):
    """Return a cached quote unless it is older than the configured refresh interval."""
    now = now or timezone.now()
    latest = (
        StockPrice.objects.filter(workspace=workspace, ticker=ticker, source="finnhub")
        .order_by("-fetched_at", "-id")
        .first()
    )
    if (
        latest
        and latest.fetched_at
        and latest.fetched_at >= now - timedelta(minutes=settings.STOCK_PRICE_REFRESH_MINUTES)
    ):
        return latest, False
    quote = fetch_quote(ticker)
    price, _ = StockPrice.objects.update_or_create(
        workspace=workspace,
        ticker=ticker,
        price_date=quote.quoted_at.date(),
        source="finnhub",
        defaults={
            "usd_price": quote.usd_price,
            "fetched_at": now,
            "source_url": quote.source_url,
            "notes": "Retrieved automatically from Finnhub.",
        },
    )
    return price, True

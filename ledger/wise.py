"""Fetch a historical GBP/USD rate from Wise using a server-side personal token."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

WISE_RATES_URL = "https://api.wise.com/2026Q3/rates"


class WiseRateUnavailable(ValueError):
    """Raised when Wise cannot return the requested historical rate."""


@dataclass(frozen=True)
class WiseRate:
    label: str
    method: str
    starts_on: date
    ends_on: date
    usd_per_gbp: Decimal
    source_url: str


def fetch_usd_rate(requested_date):
    """Retrieve the GBP to USD midpoint at noon UTC on the selected event date."""
    token = os.environ.get("WISE_PERSONAL_API_TOKEN")
    if not token:
        raise WiseRateUnavailable(
            "Wise is not configured. Set WISE_PERSONAL_API_TOKEN on the server."
        )
    timestamp = datetime.combine(requested_date, time(12), UTC).strftime("%Y-%m-%dT%H:%M:%S%z")
    query = urlencode({"source": "GBP", "target": "USD", "time": timestamp})
    source_url = f"{WISE_RATES_URL}?{query}"
    request = Request(
        source_url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-External-Correlation-Id": str(uuid4()),
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise WiseRateUnavailable("Wise could not provide a rate for that event date.") from exc
    if not isinstance(payload, list) or not payload:
        raise WiseRateUnavailable("Wise did not return a GBP/USD rate for that event date.")
    try:
        rate = Decimal(str(payload[0]["rate"]))
    except (KeyError, InvalidOperation) as exc:
        raise WiseRateUnavailable("Wise returned an invalid GBP/USD rate.") from exc
    if rate <= 0:
        raise WiseRateUnavailable("Wise returned an invalid GBP/USD rate.")
    return WiseRate(
        label=f"Wise historical GBP/USD spot rate — {timestamp}",
        method="wise",
        starts_on=requested_date,
        ends_on=requested_date,
        usd_per_gbp=rate,
        source_url=source_url,
    )

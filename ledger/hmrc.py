"""Fetch HMRC Trade Tariff exchange-rate CSVs without storing any credentials."""

from __future__ import annotations

import csv
import io
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

API_URL = "https://www.trade-tariff.service.gov.uk/api/v2/exchange_rates/files/{method}_csv_{year}-{month}.csv"
VIEW_URL = (
    "https://www.trade-tariff.service.gov.uk/exchange_rates/view/{year}-{month}?type={method}"
)


class HmrcRateUnavailable(ValueError):
    """Raised when HMRC has no published rate for the selected period."""


@dataclass(frozen=True)
class HmrcRate:
    label: str
    method: str
    starts_on: date
    ends_on: date
    usd_per_gbp: Decimal
    source_url: str


def _published_period(method, requested_date):
    if method == "monthly":
        return (
            requested_date.year,
            requested_date.month,
            requested_date.replace(day=1),
            requested_date.replace(day=monthrange(requested_date.year, requested_date.month)[1]),
        )
    publication_month = 3 if requested_date.month <= 6 else 12
    publication_year = requested_date.year
    if publication_month == 3:
        starts_on, ends_on = date(publication_year - 1, 4, 1), date(publication_year, 3, 31)
    else:
        starts_on, ends_on = date(publication_year, 1, 1), date(publication_year, 12, 31)
    return publication_year, publication_month, starts_on, ends_on


def fetch_usd_rate(method, requested_date):
    year, month, starts_on, ends_on = _published_period(method, requested_date)
    api_url = API_URL.format(method=method, year=year, month=month)
    try:
        with urlopen(api_url, timeout=15) as response:
            content = response.read().decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise HmrcRateUnavailable("HMRC could not provide a rate for that period.") from exc
    row = next(
        (row for row in csv.DictReader(io.StringIO(content)) if row["Currency Code"] == "USD"), None
    )
    if not row:
        raise HmrcRateUnavailable("The HMRC file did not contain a USD rate.")
    return HmrcRate(
        label=f"{starts_on:%B %Y} HMRC {method} rate",
        method=method,
        starts_on=starts_on,
        ends_on=ends_on,
        usd_per_gbp=Decimal(row["Currency Units per £1"]),
        source_url=VIEW_URL.format(year=year, month=month, method=method),
    )

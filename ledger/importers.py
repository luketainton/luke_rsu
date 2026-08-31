"""Importers for broker exports.

The raw source key is intentionally based on the export values rather than a row
number: E*TRADE downloads are complete histories and their row ordering can vary.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from .models import Grant, Sale, Vest


class UnsupportedImport(ValueError):
    """Raised when an uploaded file is not a recognised broker export."""


def _value(row, field):
    value = row.get(field)
    return value.strip() if isinstance(value, str) else value


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation as exc:
        raise UnsupportedImport("The export contains an invalid quantity.") from exc


def _date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return (
                date.fromisoformat(value)
                if pattern == "%Y-%m-%d"
                else datetime.strptime(value, pattern).replace(tzinfo=UTC).date()
            )
        except ValueError:
            continue
    raise UnsupportedImport("The export contains an unrecognised date.")


def _source_key(event_type, grant_number, event_date, units):
    values = [
        "etrade-benefit-history-v1",
        event_type,
        str(grant_number),
        event_date.isoformat(),
        str(units),
    ]
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _event_rows(upload):
    workbook = load_workbook(upload, read_only=True, data_only=True)
    worksheet = workbook.active
    rows = worksheet.iter_rows(values_only=True)
    headers = next(rows, None)
    if not headers:
        raise UnsupportedImport("The workbook is empty.")
    names = [str(header).strip() if header is not None else "" for header in headers]
    required = {"Record Type", "Event Type", "Grant Number"}
    if not required.issubset(names):
        raise UnsupportedImport("This is not an E*TRADE Benefit History export.")
    return [dict(zip(names, row, strict=False)) for row in rows]


def import_etrade_benefit_history(upload, workspace):
    """Insert recognisable E*TRADE events, skipping events already imported."""
    rows = _event_rows(upload)
    released = {}
    for row in rows:
        if _value(row, "Event Type") == "Shares released":
            event_date = _date(_value(row, "Date"))
            units = _decimal(_value(row, "Qty. or Amount"))
            if event_date and units is not None:
                released[(_value(row, "Grant Number"), event_date)] = units

    counts = Counter()
    missing_sale_prices = 0
    seen_grants = set()
    for row in rows:
        event_type = _value(row, "Event Type")
        event_date = _date(_value(row, "Date"))
        units = _decimal(_value(row, "Qty. or Amount"))
        grant_number = _value(row, "Grant Number")
        if event_type not in {"Shares granted", "Shares vested", "Shares sold"}:
            continue
        if not event_date or units is None or units <= 0:
            counts["skipped"] += 1
            continue
        if event_type == "Shares granted":
            model, kind, defaults = Grant, "grants", {}
            seen_grants.add(grant_number)
        elif event_type == "Shares vested":
            model, kind = Vest, "vests"
            withheld = max(Decimal(), units - released.get((grant_number, event_date), Decimal()))
            defaults = {"withheld_units": withheld}
        else:
            model, kind = Sale, "sales"
            defaults = {
                "notes": "Imported from E*TRADE; add the USD sale price before CGT reporting."
            }
            missing_sale_prices += 1
        key = _source_key(event_type, grant_number, event_date, units)
        _, created = model.objects.get_or_create(
            workspace=workspace,
            source_key=key,
            defaults={
                "date": event_date,
                "units": units,
                "notes": f"E*TRADE grant {grant_number}",
                **defaults,
            },
        )
        counts[kind if created else "duplicates"] += 1

    # A few exports contain only the award header instead of a Shares granted event.
    for row in rows:
        grant_number = _value(row, "Grant Number")
        if _value(row, "Record Type") != "Grant" or grant_number in seen_grants:
            continue
        event_date = _date(_value(row, "Grant Date"))
        units = _decimal(_value(row, "Granted Qty."))
        if not event_date or units is None or units <= 0:
            continue
        key = _source_key("Grant header", grant_number, event_date, units)
        _, created = Grant.objects.get_or_create(
            workspace=workspace,
            source_key=key,
            defaults={"date": event_date, "units": units, "notes": f"E*TRADE grant {grant_number}"},
        )
        counts["grants" if created else "duplicates"] += 1
    counts["missing_sale_prices"] = missing_sale_prices
    for key in ("grants", "vests", "sales", "duplicates"):
        counts.setdefault(key, 0)
    return counts

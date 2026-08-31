"""Resolve and retrieve exchange rates needed by record events."""

from __future__ import annotations

import os

from .hmrc import HmrcRateUnavailable
from .hmrc import fetch_usd_rate as fetch_hmrc_usd_rate
from .models import FxRate
from .wise import WiseRateUnavailable
from .wise import fetch_usd_rate as fetch_wise_usd_rate


class EventRateUnavailable(ValueError):
    """Raised when no applicable rate can be retrieved for an event."""


def applicable_rate(workspace, event_date):
    return (
        FxRate.objects.filter(
            workspace=workspace, starts_on__lte=event_date, ends_on__gte=event_date
        )
        .order_by("-starts_on", "-id")
        .first()
    )


def ensure_event_rate(workspace, event_date):
    """Return a saved rate covering an event, retrieving one when required."""
    if rate := applicable_rate(workspace, event_date):
        return rate
    try:
        rate = (
            fetch_wise_usd_rate(event_date)
            if os.environ.get("WISE_PERSONAL_API_TOKEN")
            else fetch_hmrc_usd_rate("monthly", event_date)
        )
    except WiseRateUnavailable:
        try:
            rate = fetch_hmrc_usd_rate("monthly", event_date)
        except HmrcRateUnavailable as exc:
            raise EventRateUnavailable(
                "An exchange rate could not be retrieved for this event date. "
                "Add a rate manually and try again."
            ) from exc
    except HmrcRateUnavailable as exc:
        raise EventRateUnavailable(
            "An exchange rate could not be retrieved for this event date. "
            "Add a rate manually and try again."
        ) from exc
    saved_rate, _ = FxRate.objects.update_or_create(
        workspace=workspace,
        method=rate.method,
        starts_on=rate.starts_on,
        ends_on=rate.ends_on,
        defaults={
            "label": rate.label,
            "usd_per_gbp": rate.usd_per_gbp,
            "source_url": rate.source_url,
        },
    )
    return saved_rate

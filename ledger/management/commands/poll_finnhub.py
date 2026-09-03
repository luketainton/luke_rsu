"""Refresh saved Finnhub prices outside web requests."""

from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from ledger.finnhub import FinnhubQuoteUnavailable, is_configured, refresh_live_price
from ledger.models import Grant, Workspace


class Command(BaseCommand):
    help = "Refresh stale Finnhub prices for all tracked grant securities."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Poll once and exit instead of running continuously.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=settings.FINNHUB_POLL_INTERVAL_SECONDS,
            help="Seconds to wait between polls.",
        )

    def handle(self, *args, **options):
        if not is_configured():
            self.stdout.write("Finnhub is not configured; polling is disabled.")
            return
        if options["interval"] < 1:
            raise self.CommandError("--interval must be at least 1 second")

        while True:
            self.poll()
            if options["once"]:
                return
            time.sleep(options["interval"])

    def poll(self):
        tracked = (
            Grant.objects.filter(security__isnull=False)
            .exclude(security__ticker="")
            .values_list("workspace_id", "security__ticker")
            .distinct()
        )
        for workspace_id, ticker in tracked:
            workspace = Workspace.objects.get(pk=workspace_id)
            try:
                _, refreshed = refresh_live_price(workspace, ticker)
            except FinnhubQuoteUnavailable as exc:
                self.stderr.write(str(exc))
            else:
                if refreshed:
                    self.stdout.write(f"Refreshed Finnhub quote for {ticker}.")

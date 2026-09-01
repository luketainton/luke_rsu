"""UK share-identification and Section 104 working-paper calculations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

ZERO = Decimal(0)


@dataclass
class Acquisition:
    vest: object
    units: Decimal
    cost: Decimal | None
    remaining: Decimal


@dataclass
class Match:
    kind: str
    units: Decimal
    cost: Decimal | None
    proceeds: Decimal | None
    acquisition_date: object | None = None

    @property
    def gain_or_loss(self):
        if self.cost is None or self.proceeds is None:
            return None
        return self.proceeds - self.cost


@dataclass
class Disposal:
    sale: object
    matches: list[Match] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def gain_or_loss(self):
        values = [match.gain_or_loss for match in self.matches]
        return None if any(value is None for value in values) else sum(values, ZERO)


@dataclass
class Section104Report:
    security: object
    disposals: list[Disposal]
    pool_units: Decimal
    pool_cost: Decimal | None
    warnings: list[str]

    @property
    def average_cost(self):
        if self.pool_cost is None or not self.pool_units:
            return None
        return self.pool_cost / self.pool_units


def event_security(event, grants):
    """Resolve an event to an explicitly linked security, without guessing ambiguously."""
    key = (event.broker_id, event.grant_id)
    candidates = [grant.security for grant in grants if (grant.broker_id, grant.grant_id) == key]
    candidates = [security for security in candidates if security]
    if len({security.id for security in candidates}) == 1:
        return candidates[0]
    return None


def event_cost(event, units):
    if event.usd_price is None or event.gbp_per_usd is None:
        return None
    return units * event.usd_price * event.gbp_per_usd


def sale_proceeds(sale):
    if sale.usd_price is None or sale.gbp_per_usd is None:
        return None
    return sale.units * sale.usd_price * sale.gbp_per_usd - sale.fees_gbp


def section_104_report(security, grants, vests, sales):
    """Apply same-day, 30-day and residual Section 104 matching for one security."""
    relevant_vests = [vest for vest in vests if event_security(vest, grants) == security]
    relevant_sales = [sale for sale in sales if event_security(sale, grants) == security]
    acquisitions = [
        Acquisition(
            vest=vest,
            units=max(ZERO, vest.units - vest.withheld_units),
            cost=event_cost(vest, max(ZERO, vest.units - vest.withheld_units)),
            remaining=max(ZERO, vest.units - vest.withheld_units),
        )
        for vest in relevant_vests
    ]
    disposals = [
        Disposal(sale=sale)
        for sale in sorted(relevant_sales, key=lambda sale: (sale.date, sale.id))
    ]

    # Reserve priority matches before calculating the residual pool movements.
    for disposal in disposals:
        remaining = disposal.sale.units
        for kind, candidates in (
            ("Same day", [a for a in acquisitions if a.vest.date == disposal.sale.date]),
            (
                "30-day",
                [
                    a
                    for a in acquisitions
                    if disposal.sale.date < a.vest.date <= disposal.sale.date + timedelta(days=30)
                ],
            ),
        ):
            for acquisition in sorted(candidates, key=lambda a: (a.vest.date, a.vest.id)):
                if remaining <= ZERO:
                    break
                units = min(remaining, acquisition.remaining)
                if units <= ZERO:
                    continue
                cost = (
                    None
                    if acquisition.cost is None
                    else acquisition.cost * units / acquisition.units
                )
                acquisition.remaining -= units
                disposal.matches.append(
                    Match(
                        kind=kind,
                        units=units,
                        cost=cost,
                        proceeds=None,
                        acquisition_date=acquisition.vest.date,
                    )
                )
                remaining -= units
        disposal._pool_units = remaining

    pool_units = ZERO
    pool_cost = ZERO
    pool_cost_complete = True
    warnings = []
    acquisitions_by_date = defaultdict(list)
    for acquisition in acquisitions:
        acquisitions_by_date[acquisition.vest.date].append(acquisition)
    disposals_by_date = defaultdict(list)
    for disposal in disposals:
        disposals_by_date[disposal.sale.date].append(disposal)

    for event_date in sorted(set(acquisitions_by_date) | set(disposals_by_date)):
        for disposal in disposals_by_date[event_date]:
            remaining = disposal._pool_units
            if remaining > pool_units:
                disposal.warnings.append("Insufficient shares in the Section 104 pool.")
                remaining = pool_units
            if remaining:
                cost = None if not pool_cost_complete else pool_cost * remaining / pool_units
                disposal.matches.append(
                    Match(kind="Section 104 pool", units=remaining, cost=cost, proceeds=None)
                )
                pool_units -= remaining
                if cost is not None:
                    pool_cost -= cost
            matched_units = sum((match.units for match in disposal.matches), ZERO)
            if matched_units < disposal.sale.units:
                disposal.warnings.append("Disposal has unmatched shares.")
        for acquisition in acquisitions_by_date[event_date]:
            if acquisition.remaining <= ZERO:
                continue
            pool_units += acquisition.remaining
            if acquisition.cost is None:
                pool_cost_complete = False
            elif pool_cost_complete:
                pool_cost += acquisition.cost * acquisition.remaining / acquisition.units

    for disposal in disposals:
        proceeds = sale_proceeds(disposal.sale)
        if proceeds is None:
            disposal.warnings.append("Missing USD sale price or exchange rate evidence.")
        matched_units = sum((match.units for match in disposal.matches), ZERO)
        for match in disposal.matches:
            match.proceeds = (
                None if proceeds is None else proceeds * match.units / disposal.sale.units
            )
        if matched_units != disposal.sale.units:
            warnings.append(f"Sale on {disposal.sale.date} has unmatched shares.")
        if any(match.cost is None for match in disposal.matches):
            disposal.warnings.append(
                "Missing vest price or exchange rate evidence for allowable cost."
            )

    if not pool_cost_complete:
        pool_cost = None
        warnings.append(
            "Section 104 pool contains acquisitions without complete allowable cost evidence."
        )
    return Section104Report(
        security=security,
        disposals=disposals,
        pool_units=pool_units,
        pool_cost=pool_cost,
        warnings=warnings,
    )

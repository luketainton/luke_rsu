"""UK share-identification and Section 104 working-paper calculations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from .broker_rules import grant_accepts_event_broker

ZERO = Decimal(0)


def event_date(event):
    """Return the operative CGT date, preferring a recorded contract date."""
    return getattr(event, "contract_date", None) or event.date


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
    pool_identity: tuple | None = None

    @property
    def average_cost(self):
        if self.pool_cost is None or not self.pool_units:
            return None
        return self.pool_cost / self.pool_units


def event_security(event, grants):
    """Resolve directly, then safely fall back to the legacy Grant link."""
    if getattr(event, "security_id", None):
        return event.security
    candidates = [
        grant.security
        for grant in grants
        if grant.grant_id == event.grant_id
        and (
            grant.broker_id == getattr(event, "broker_id", None)
            or grant_accepts_event_broker(grant, getattr(event, "broker", None))
        )
    ]
    candidates = [security for security in candidates if security]
    if len({security.id for security in candidates}) == 1:
        return candidates[0]
    return None


def event_cost(event, units):
    if getattr(event, "capital_cost_gbp", None) is not None:
        acquired_units = max(
            ZERO,
            event.units
            if getattr(event, "withholding_treatment", "net") == "gross_sell_to_cover"
            else event.units - getattr(event, "withheld_units", ZERO),
        )
        if not acquired_units:
            return ZERO
        return event.capital_cost_gbp * units / acquired_units
    if event.usd_price is None or event.gbp_per_usd is None:
        return None
    cost = units * event.usd_price * event.gbp_per_usd
    return cost + getattr(event, "fees_gbp", ZERO)


def sale_proceeds(sale):
    if sale.proceeds_gbp is not None:
        return sale.proceeds_gbp
    if sale.usd_price is None or sale.gbp_per_usd is None:
        return None
    return sale.units * sale.usd_price * sale.gbp_per_usd - sale.fees_gbp


def section_104_report(
    security,
    grants,
    vests,
    sales,
    opening_balance=None,
    purchases=None,
    adjustments=None,
    pool_identity=None,
):
    """Apply same-day, 30-day and residual Section 104 matching for one security."""
    relevant_vests = [vest for vest in vests if event_security(vest, grants) == security]
    relevant_purchases = [
        purchase for purchase in (purchases or []) if purchase.security_id == security.id
    ]
    relevant_sales = [sale for sale in sales if event_security(sale, grants) == security]
    if pool_identity is not None:
        identity = lambda event: (
            getattr(event, "beneficial_owner", ""),
            getattr(event, "capacity", "personal"),
            getattr(event, "account_reference", ""),
        )
        relevant_vests = [vest for vest in relevant_vests if identity(vest) == pool_identity]
        relevant_sales = [sale for sale in relevant_sales if identity(sale) == pool_identity]
        relevant_purchases = [
            purchase for purchase in relevant_purchases if identity(purchase) == pool_identity
        ]
    for vest in relevant_vests:
        if (
            getattr(vest, "withholding_treatment", "net") == "gross_sell_to_cover"
            and vest.withheld_units > ZERO
        ):
            relevant_sales.append(
                SimpleNamespace(
                    id=-vest.id,
                    date=event_date(vest),
                    units=vest.withheld_units,
                    usd_price=None,
                    proceeds_gbp=vest.sell_to_cover_proceeds_gbp,
                    fees_gbp=vest.sell_to_cover_fees_gbp,
                    security_id=security.id,
                    security=security,
                    grant_id=vest.grant_id,
                    broker_id=vest.broker_id,
                    workspace=vest.workspace,
                    workspace_id=vest.workspace_id,
                    beneficial_owner=vest.beneficial_owner,
                    capacity=vest.capacity,
                    account_reference=vest.account_reference,
                    notes="Synthetic sell-to-cover disposal from Vest",
                )
            )
    relevant_adjustments = [
        adjustment for adjustment in (adjustments or []) if adjustment.security_id == security.id
    ]
    identities = {
        (
            getattr(event, "beneficial_owner", ""),
            getattr(event, "capacity", "personal"),
            getattr(event, "account_reference", ""),
        )
        for event in [*relevant_vests, *relevant_sales, *relevant_purchases]
    }
    if opening_balance:
        relevant_vests = [
            vest for vest in relevant_vests if event_date(vest) >= opening_balance.effective_on
        ]
        relevant_purchases = [
            purchase
            for purchase in relevant_purchases
            if event_date(purchase) >= opening_balance.effective_on
        ]
        relevant_adjustments = [
            adjustment
            for adjustment in relevant_adjustments
            if adjustment.effective_on >= opening_balance.effective_on
        ]
        relevant_sales = [
            sale for sale in relevant_sales if event_date(sale) >= opening_balance.effective_on
        ]
    acquisitions = [
        Acquisition(
            vest=vest,
            units=max(
                ZERO,
                vest.units
                if getattr(vest, "withholding_treatment", "net") == "gross_sell_to_cover"
                else vest.units - vest.withheld_units,
            ),
            cost=event_cost(
                vest,
                max(
                    ZERO,
                    vest.units
                    if getattr(vest, "withholding_treatment", "net") == "gross_sell_to_cover"
                    else vest.units - vest.withheld_units,
                ),
            ),
            remaining=max(
                ZERO,
                vest.units
                if getattr(vest, "withholding_treatment", "net") == "gross_sell_to_cover"
                else vest.units - vest.withheld_units,
            ),
        )
        for vest in relevant_vests
    ]
    acquisitions.extend(
        Acquisition(
            vest=purchase,
            units=max(ZERO, purchase.units),
            cost=event_cost(purchase, max(ZERO, purchase.units)),
            remaining=max(ZERO, purchase.units),
        )
        for purchase in relevant_purchases
    )
    disposals = [
        Disposal(sale=sale)
        for sale in sorted(relevant_sales, key=lambda sale: (event_date(sale), sale.id))
    ]

    # Reserve priority matches before calculating the residual pool movements.
    for disposal in disposals:
        remaining = disposal.sale.units
        for kind, candidates in (
            (
                "Same day",
                [a for a in acquisitions if event_date(a.vest) == event_date(disposal.sale)],
            ),
            (
                "30-day",
                [
                    a
                    for a in acquisitions
                    if event_date(disposal.sale)
                    < event_date(a.vest)
                    <= event_date(disposal.sale) + timedelta(days=30)
                ],
            ),
        ):
            for acquisition in sorted(candidates, key=lambda a: (event_date(a.vest), a.vest.id)):
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
                        acquisition_date=event_date(acquisition.vest),
                    )
                )
                remaining -= units
        disposal._pool_units = remaining

    pool_units = ZERO if opening_balance is None else opening_balance.units
    pool_cost = ZERO if opening_balance is None else opening_balance.pool_cost_gbp
    pool_cost_complete = True
    warnings = []
    if len(identities) > 1:
        warnings.append(
            "Multiple owner/capacity/account identities are present; review before relying on this combined report."
        )
    if opening_balance:
        earlier_events = [
            event
            for event in [*vests, *sales]
            if event_security(event, grants) == security
            and event_date(event) < opening_balance.effective_on
        ]
        if earlier_events:
            warnings.append(
                f"{len(earlier_events)} event(s) before the opening balance date were excluded."
            )
    unresolved = [
        event
        for event in [*vests, *sales]
        if event_security(event, grants) is None and (event.grant_id or event.security_id)
    ]
    if unresolved:
        warnings.append(
            f"{len(unresolved)} event(s) could not be linked to a Security and were excluded."
        )
    acquisitions_by_date = defaultdict(list)
    for acquisition in acquisitions:
        acquisitions_by_date[event_date(acquisition.vest)].append(acquisition)
    disposals_by_date = defaultdict(list)
    for disposal in disposals:
        disposals_by_date[disposal.sale.date].append(disposal)
    adjustments_by_date = defaultdict(list)
    for adjustment in relevant_adjustments:
        adjustments_by_date[adjustment.effective_on].append(adjustment)

    for date_key in sorted(
        set(acquisitions_by_date) | set(disposals_by_date) | set(adjustments_by_date)
    ):
        for adjustment in adjustments_by_date[date_key]:
            pool_units += adjustment.units_delta
            pool_cost += adjustment.cost_delta_gbp
            if pool_units < ZERO or pool_cost < ZERO:
                warnings.append(
                    f"Pool adjustment on {adjustment.effective_on} creates a negative pool."
                )
        for disposal in disposals_by_date[date_key]:
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
        for acquisition in acquisitions_by_date[date_key]:
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
            warnings.append(f"Sale on {event_date(disposal.sale)} has unmatched shares.")
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
        pool_identity=pool_identity,
    )

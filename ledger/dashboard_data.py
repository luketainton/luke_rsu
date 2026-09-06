"""Calculations used by the private workspace overview dashboard."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .broker_rules import grant_accepts_event_broker
from .section104 import event_date, event_security, sale_proceeds, section_104_report

ZERO = Decimal(0)


@dataclass
class TaxYearSummary:
    label: str
    vested_units: Decimal = ZERO
    sold_units: Decimal = ZERO
    proceeds: Decimal = ZERO
    allowable_cost: Decimal = ZERO
    gain_or_loss: Decimal = ZERO
    incomplete_sales: int = 0
    lower_rate_cgt: Decimal = ZERO
    higher_rate_cgt: Decimal = ZERO
    chart_width: int = 0
    gain_components: list[tuple[Decimal, Decimal, Decimal]] = field(default_factory=list)

    @property
    def annual_exempt_amount(self):
        return annual_exempt_amount(self.label)

    @property
    def taxable_gain(self):
        return max(ZERO, self.gain_or_loss - self.annual_exempt_amount)


@dataclass
class TickerPosition:
    ticker: str
    units: Decimal = ZERO
    usd_cost: Decimal = ZERO
    cost_is_complete: bool = True
    latest_price: Decimal | None = None
    price_date: date | None = None

    @property
    def market_value(self):
        return None if self.latest_price is None else self.units * self.latest_price

    @property
    def unrealised_gain_or_loss(self):
        if self.market_value is None or not self.cost_is_complete:
            return None
        return self.market_value - self.usd_cost


def financial_year(event_date):
    start_year = (
        event_date.year if (event_date.month, event_date.day) >= (4, 5) else event_date.year - 1
    )
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def annual_exempt_amount(tax_year):
    start_year = int(tax_year[:4])
    if start_year >= 2024:
        return Decimal(3000)
    if start_year == 2023:
        return Decimal(6000)
    return Decimal(12300)


def cgt_rates(disposal_date):
    """Return main CGT rates for non-residential shares on the disposal date."""
    if disposal_date < date(2024, 10, 30):
        return Decimal("0.10"), Decimal("0.20")
    return Decimal("0.18"), Decimal("0.24")


def gbp_value(record, units):
    if record.usd_price is None or record.gbp_per_usd is None:
        return None
    return units * record.usd_price * record.gbp_per_usd


def _dashboard_summary_legacy(vests, sales):
    """Build the pre-HMRC dashboard estimate for backwards-compatible callers."""
    summaries = defaultdict(lambda: TaxYearSummary(label=""))
    events = [(vest.date, 0, vest) for vest in vests] + [(sale.date, 1, sale) for sale in sales]
    pool_units = ZERO
    pool_cost = ZERO
    incomplete_sales = 0

    for _, event_type, event in sorted(events, key=lambda item: (item[0], item[1], item[2].id)):
        year = financial_year(event.date)
        summary = summaries[year]
        summary.label = year
        if event_type == 0:
            net_units = max(ZERO, event.units - event.withheld_units)
            summary.vested_units += net_units
            cost = gbp_value(event, net_units)
            if cost is not None:
                pool_cost += cost
            pool_units += net_units
            continue

        summary.sold_units += event.units
        proceeds = gbp_value(event, event.units)
        if proceeds is None or pool_units <= ZERO or event.units > pool_units:
            summary.incomplete_sales += 1
            incomplete_sales += 1
            continue

        cost = pool_cost * event.units / pool_units
        net_proceeds = proceeds - event.fees_gbp
        gain_or_loss = net_proceeds - cost
        summary.proceeds += net_proceeds
        summary.allowable_cost += cost
        summary.gain_or_loss += gain_or_loss
        summary.gain_components.append((gain_or_loss, *cgt_rates(event.date)))
        pool_units -= event.units
        pool_cost -= cost

    summaries = list(summaries.values())
    for summary in summaries:
        summary.lower_rate_cgt, summary.higher_rate_cgt = estimated_cgt(summary)

    largest_result = max((abs(summary.gain_or_loss) for summary in summaries), default=ZERO)
    for summary in summaries:
        summary.chart_width = (
            0 if largest_result == ZERO else int(abs(summary.gain_or_loss) / largest_result * 100)
        )

    return {
        "held_units": pool_units,
        "pool_cost": pool_cost,
        "incomplete_sales": incomplete_sales,
        "tax_years": sorted(summaries, key=lambda item: item.label, reverse=True),
    }


def dashboard_summary(
    vests,
    sales,
    grants=None,
    securities=None,
    opening_balances=None,
    purchases=None,
    adjustments=None,
):
    """Build dashboard results using HMRC matching when grant data is available.

    The legacy two-argument form is retained for small callers that do not have
    Security/Grant context.  The dashboard passes the full workspace context,
    allowing same-day, 30-day and Section 104 matching to be reflected in the
    realised gains.
    """
    if grants is None or (not grants and not securities):
        return _dashboard_summary_legacy(vests, sales)

    securities_by_id = {security.id: security for security in (securities or [])}
    for event in [*vests, *sales]:
        security = event_security(event, grants)
        if security:
            securities_by_id[security.id] = security
    reports = []
    for security in securities_by_id.values():
        events = [event for event in [*vests, *sales] if event_security(event, grants) == security]
        identities = {
            (
                getattr(event, "beneficial_owner", ""),
                getattr(event, "capacity", "personal"),
                getattr(event, "account_reference", ""),
            )
            for event in events
        }
        opening = (opening_balances or {}).get(security.id)
        if len(identities) <= 1:
            reports.append(
                section_104_report(
                    security,
                    grants,
                    vests,
                    sales,
                    opening,
                    purchases,
                    adjustments,
                )
            )
        else:
            reports.extend(
                section_104_report(
                    security,
                    grants,
                    vests,
                    sales,
                    None,
                    purchases,
                    adjustments,
                    identity,
                )
                for identity in sorted(identities)
            )

    summaries = defaultdict(lambda: TaxYearSummary(label=""))
    for vest in vests:
        year = financial_year(event_date(vest))
        summary = summaries[year]
        summary.label = year
        summary.vested_units += max(
            ZERO,
            vest.units
            if getattr(vest, "withholding_treatment", "net") == "gross_sell_to_cover"
            else vest.units - vest.withheld_units,
        )
    incomplete_sales = 0
    for report in reports:
        for disposal in report.disposals:
            year = financial_year(event_date(disposal.sale))
            summary = summaries[year]
            summary.label = year
            summary.sold_units += disposal.sale.units
            proceeds = sale_proceeds(disposal.sale)
            gain = disposal.gain_or_loss
            if proceeds is None or gain is None or disposal.warnings:
                summary.incomplete_sales += 1
                incomplete_sales += 1
                continue
            summary.proceeds += proceeds
            summary.allowable_cost += proceeds - gain
            summary.gain_or_loss += gain
            for match in disposal.matches:
                if match.gain_or_loss is not None:
                    summary.gain_components.append(
                        (match.gain_or_loss, *cgt_rates(event_date(disposal.sale)))
                    )
    summaries = list(summaries.values())
    for summary in summaries:
        summary.lower_rate_cgt, summary.higher_rate_cgt = estimated_cgt(summary)
    largest_result = max((abs(summary.gain_or_loss) for summary in summaries), default=ZERO)
    for summary in summaries:
        summary.chart_width = (
            0 if largest_result == ZERO else int(abs(summary.gain_or_loss) / largest_result * 100)
        )
    return {
        "held_units": sum((report.pool_units for report in reports), ZERO),
        "pool_cost": sum(
            (report.pool_cost for report in reports if report.pool_cost is not None), ZERO
        ),
        "incomplete_sales": incomplete_sales,
        "tax_years": sorted(summaries, key=lambda item: item.label, reverse=True),
    }


def ticker_positions(grants, vests, sales, prices):
    """Return ticker-level estimated positions from linked Grant IDs and saved quotes."""
    tickers_by_grant = {}
    for grant in grants:
        if grant.security and grant.grant_id:
            tickers_by_grant[(grant.broker_id, grant.grant_id)] = grant.security.ticker

    def ticker_for(event):
        if ticker := tickers_by_grant.get((event.broker_id, event.grant_id)):
            return ticker
        candidates = {
            grant.security.ticker
            for grant in grants
            if grant.grant_id == event.grant_id
            and grant.security
            and grant_accepts_event_broker(grant, getattr(event, "broker", None))
        }
        return next(iter(candidates)) if len(candidates) == 1 else None

    positions = {}
    events = [(vest.date, 0, vest) for vest in vests] + [(sale.date, 1, sale) for sale in sales]
    for _, event_type, event in sorted(events, key=lambda item: (item[0], item[1], item[2].id)):
        ticker = ticker_for(event)
        if not ticker:
            continue
        position = positions.setdefault(ticker, TickerPosition(ticker=ticker))
        if event_type == 0:
            net_units = max(ZERO, event.units - event.withheld_units)
            position.units += net_units
            if event.usd_price is None:
                position.cost_is_complete = False
            else:
                position.usd_cost += net_units * event.usd_price
            continue
        if event.units > position.units or position.units <= ZERO:
            position.cost_is_complete = False
            continue
        cost = position.usd_cost * event.units / position.units
        position.units -= event.units
        position.usd_cost -= cost

    latest_prices = {}
    for price in sorted(prices, key=lambda item: (item.price_date, item.id)):
        latest_prices[price.security.ticker] = price
    for ticker, position in positions.items():
        if price := latest_prices.get(ticker):
            position.latest_price = price.usd_price
            position.price_date = price.price_date
    return sorted(
        (position for position in positions.values() if position.units > ZERO),
        key=lambda p: p.ticker,
    )


def estimated_cgt(summary):
    """Apply losses and the annual exempt amount against the highest-rate gains first."""
    relief = max(ZERO, -sum((gain for gain, _, _ in summary.gain_components), ZERO))
    relief += summary.annual_exempt_amount
    lower_tax = ZERO
    higher_tax = ZERO
    for gain, lower_rate, higher_rate in sorted(
        (component for component in summary.gain_components if component[0] > ZERO),
        key=lambda component: component[2],
        reverse=True,
    ):
        taxable_component = max(ZERO, gain - relief)
        relief = max(ZERO, relief - gain)
        lower_tax += taxable_component * lower_rate
        higher_tax += taxable_component * higher_rate
    return lower_tax, higher_tax

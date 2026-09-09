"""Read-only transaction simulations for the workspace overview."""

from dataclasses import dataclass
from types import SimpleNamespace

from .dashboard_data import dashboard_summary
from .section104 import section_104_report


@dataclass
class SimulationResult:
    transaction: str
    event: object
    before: dict
    after: dict
    section_before: object
    section_after: object

    @property
    def held_delta(self):
        return self.after["held_units"] - self.before["held_units"]

    @property
    def pool_cost_delta(self):
        return self.after["pool_cost"] - self.before["pool_cost"]


class SimulatedEvent(SimpleNamespace):
    @property
    def gbp_per_usd(self):
        rate = (
            self.workspace.fxrate_set.filter(starts_on__lte=self.date, ends_on__gte=self.date)
            .order_by("-starts_on", "-id")
            .first()
        )
        return None if rate is None else 1 / rate.usd_per_gbp


def _event(transaction, workspace, security, cleaned_data):
    values = {
        "id": -1,
        "workspace": workspace,
        "workspace_id": workspace.id,
        "security": security,
        "security_id": security.id,
        "date": cleaned_data["date"],
        "contract_date": None,
        "units": cleaned_data["units"],
        "usd_price": cleaned_data.get("usd_price"),
        "capital_cost_gbp": cleaned_data.get("capital_cost_gbp"),
        "proceeds_gbp": cleaned_data.get("proceeds_gbp"),
        "fees_gbp": cleaned_data.get("fees_gbp") or 0,
        "withheld_units": 0,
        "withholding_treatment": "net",
        "grant_id": "",
        "broker_id": None,
        "broker": None,
        "beneficial_owner": cleaned_data.get("beneficial_owner", ""),
        "capacity": cleaned_data.get("capacity", "personal"),
        "account_reference": cleaned_data.get("account_reference", ""),
    }
    return SimulatedEvent(**values)


def simulate_transaction(
    transaction,
    workspace,
    security,
    grants,
    vests,
    sales,
    purchases,
    securities,
    opening_balance=None,
    adjustments=None,
    cleaned_data=None,
):
    """Calculate before/after dashboard and Section 104 results without saving."""
    cleaned_data = cleaned_data or {}
    event = _event(transaction, workspace, security, cleaned_data)
    before = dashboard_summary(
        vests,
        sales,
        grants=grants,
        securities=securities,
        opening_balances={security.id: opening_balance} if opening_balance else {},
        purchases=purchases,
        adjustments=adjustments,
    )
    before_section = section_104_report(
        security, grants, vests, sales, opening_balance, purchases, adjustments
    )
    after_vests = [*vests, event] if transaction == "vest" else vests
    after_sales = [*sales, event] if transaction == "sale" else sales
    after_purchases = [*purchases, event] if transaction == "purchase" else purchases
    after = dashboard_summary(
        after_vests,
        after_sales,
        grants=grants,
        securities=securities,
        opening_balances={security.id: opening_balance} if opening_balance else {},
        purchases=after_purchases,
        adjustments=adjustments,
    )
    after_section = section_104_report(
        security,
        grants,
        after_vests,
        after_sales,
        opening_balance,
        after_purchases,
        adjustments,
    )
    return SimulationResult(transaction, event, before, after, before_section, after_section)

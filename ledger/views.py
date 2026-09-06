import hashlib
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q
from django.http import HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .broker_rules import grants_for_event_broker
from .dashboard_data import dashboard_summary, ticker_positions
from .enrichment import infer_event_security
from .finnhub import is_configured
from .forms import (
    BenefitHistoryImportForm,
    BrokerForm,
    FxRateForm,
    GrantForm,
    HmrcRateFetchForm,
    MembershipForm,
    PoolAdjustmentForm,
    PurchaseForm,
    SaleForm,
    Section104OpeningBalanceForm,
    SecurityForm,
    StockPriceForm,
    VestForm,
    WiseRateFetchForm,
    WorkspaceForm,
)
from .fx import EventRateUnavailable, ensure_event_rate
from .hmrc import HmrcRateUnavailable, fetch_usd_rate
from .importers import (
    UnsupportedImport,
    import_etrade_benefit_history,
    import_legacy_restricted_stock,
    import_legacy_stock_transactions,
    import_schwab_equity_details,
    import_schwab_transaction_history,
)
from .models import (
    Broker,
    FxRate,
    Grant,
    PoolAdjustment,
    Purchase,
    Sale,
    Section104OpeningBalance,
    Section104Snapshot,
    Security,
    StockPrice,
    Vest,
    Workspace,
    WorkspaceMembership,
)
from .section104 import event_date, event_security, section_104_report
from .wise import WiseRateUnavailable
from .wise import fetch_usd_rate as fetch_wise_usd_rate
from .workspaces import active_membership, membership_for_workspace


def request_membership(request):
    return active_membership(request)


def can_edit(member):
    return member.role in {"owner", "editor"}


def return_url(request, fallback):
    """Return a same-site destination supplied by the originating list page."""
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return reverse(fallback)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("dashboard")
    return render(
        request,
        "registration/login.html",
        {"form": form, "oidc_enabled": bool(__import__("os").environ.get("OIDC_ISSUER_URL"))},
    )


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def switch_workspace(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    membership = membership_for_workspace(request.user, request.POST.get("workspace_id"))
    if membership is None:
        return HttpResponseForbidden("Ledger access required")
    request.session["active_workspace_id"] = membership.workspace_id
    return redirect(return_url(request, "dashboard"))


@login_required
def create_workspace(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    form = WorkspaceForm(request.POST)
    if form.is_valid():
        workspace = Workspace.objects.create(name=form.cleaned_data["name"])
        WorkspaceMembership.objects.create(
            workspace=workspace, user=request.user, role=WorkspaceMembership.Role.OWNER
        )
        request.session["active_workspace_id"] = workspace.id
        messages.success(request, "Ledger created.")
        return redirect("dashboard")
    messages.error(request, "; ".join(error for errors in form.errors.values() for error in errors))
    return redirect("dashboard")


@login_required
def rename_workspace(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    member = request_membership(request)
    if member.role != WorkspaceMembership.Role.OWNER:
        return HttpResponseForbidden("Owner permission required")
    form = WorkspaceForm(request.POST, instance=member.workspace)
    if form.is_valid():
        form.save()
        messages.success(request, "Ledger renamed.")
    else:
        messages.error(
            request, "; ".join(error for errors in form.errors.values() for error in errors)
        )
    return redirect("dashboard")


@login_required
def dashboard(request):
    member = request_membership(request)
    workspace = member.workspace
    grants = list(Grant.objects.filter(workspace=workspace).select_related("broker", "security"))
    vests = list(Vest.objects.filter(workspace=workspace).order_by("date", "id"))
    sales = list(Sale.objects.filter(workspace=workspace).order_by("date", "id"))
    securities = list(Security.objects.filter(workspace=workspace))
    purchases = list(Purchase.objects.filter(workspace=workspace))
    adjustments = list(PoolAdjustment.objects.filter(workspace=workspace))
    opening_balances = {
        balance.security_id: balance
        for balance in Section104OpeningBalance.objects.filter(workspace=workspace)
    }
    positions = ticker_positions(
        grants,
        vests,
        sales,
        StockPrice.objects.filter(workspace=workspace),
    )
    summary = dashboard_summary(
        vests,
        sales,
        grants=grants,
        securities=securities,
        opening_balances=opening_balances,
        purchases=purchases,
        adjustments=adjustments,
    )
    context = {
        "membership": member,
        "grant_count": len(grants),
        "vest_count": len(vests),
        "sale_count": len(sales),
        "rate_count": FxRate.objects.filter(workspace=workspace).count(),
        "pool_cost": summary["pool_cost"],
        "tax_years": summary["tax_years"],
        "incomplete_sales": summary["incomplete_sales"],
        "ticker_positions": positions,
        "market_value_usd": sum(
            (position.market_value for position in positions if position.market_value is not None),
            Decimal(0),
        ),
        "unpriced_ticker_count": sum(position.latest_price is None for position in positions),
        "live_price_configured": is_configured(),
    }
    context["held"] = summary["held_units"]
    return render(request, "ledger/dashboard.html", context)


def filtered_table(request, queryset, search_fields, sort_options, default_sort):
    """Apply safe, workspace-scoped text search and ordering to a table."""
    search = request.GET.get("q", "").strip()
    if search:
        filters = Q()
        for field in search_fields:
            filters |= Q(**{f"{field}__icontains": search})
        queryset = queryset.filter(filters)
    allowed_sorts = {value for value, _ in sort_options}
    sort = request.GET.get("sort", default_sort)
    if sort not in allowed_sorts:
        sort = default_sort
    return queryset.order_by(sort), search, sort


def list_records(
    request, model, template, context_name, sort_options, default_sort, search_fields=None
):
    member = request_membership(request)
    records, search, sort = filtered_table(
        request,
        model.objects.filter(workspace=member.workspace).select_related("broker"),
        search_fields or ["grant_id", "broker__name", "notes"],
        sort_options,
        default_sort,
    )
    return render(
        request,
        template,
        {
            "membership": member,
            context_name: records,
            "q": search,
            "sort": sort,
            "sort_options": sort_options,
        },
    )


@login_required
def grant_list(request):
    return list_records(
        request,
        Grant,
        "ledger/grants.html",
        "grants",
        [
            ("-date", "Newest first"),
            ("date", "Oldest first"),
            ("grant_id", "Grant ID"),
            ("security__ticker", "Ticker"),
            ("broker__name", "Broker"),
            ("-units", "Most units"),
        ],
        "-date",
        ["grant_id", "security__ticker", "broker__name", "notes"],
    )


@login_required
def vest_list(request):
    return list_records(
        request,
        Vest,
        "ledger/vests.html",
        "vests",
        [
            ("-date", "Newest first"),
            ("date", "Oldest first"),
            ("grant_id", "Grant ID"),
            ("broker__name", "Broker"),
            ("-units", "Most units"),
        ],
        "-date",
    )


@login_required
def sale_list(request):
    return list_records(
        request,
        Sale,
        "ledger/sales.html",
        "sales",
        [
            ("-date", "Newest first"),
            ("date", "Oldest first"),
            ("grant_id", "Grant ID"),
            ("broker__name", "Broker"),
            ("-units", "Most units"),
        ],
        "-date",
    )


@login_required
def rate_list(request):
    member = request_membership(request)
    sort_options = [
        ("-ends_on", "Latest period first"),
        ("ends_on", "Earliest period first"),
        ("label", "Label"),
        ("method", "Method"),
    ]
    rates, search, sort = filtered_table(
        request,
        FxRate.objects.filter(workspace=member.workspace),
        ["label", "method"],
        sort_options,
        "-ends_on",
    )
    return render(
        request,
        "ledger/rates.html",
        {
            "membership": member,
            "rates": rates,
            "q": search,
            "sort": sort,
            "sort_options": sort_options,
        },
    )


@login_required
def price_list(request):
    member = request_membership(request)
    sort_options = [
        ("-price_date", "Latest first"),
        ("price_date", "Oldest first"),
        ("security__ticker", "Ticker"),
        ("-usd_price", "Highest price"),
    ]
    prices, search, sort = filtered_table(
        request,
        StockPrice.objects.filter(workspace=member.workspace),
        ["security__ticker", "notes"],
        sort_options,
        "-price_date",
    )
    return render(
        request,
        "ledger/prices.html",
        {
            "membership": member,
            "prices": prices,
            "q": search,
            "sort": sort,
            "sort_options": sort_options,
            "live_price_configured": is_configured(),
        },
    )


@login_required
def security_list(request):
    member = request_membership(request)
    securities = Security.objects.filter(workspace=member.workspace)
    return render(
        request, "ledger/securities.html", {"membership": member, "securities": securities}
    )


@login_required
def add_security(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = SecurityForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        security = form.save(commit=False)
        security.workspace = member.workspace
        security.save()
        messages.success(request, "Security saved.")
        return redirect(return_url(request, "security_list"))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": "Security", "next": return_url(request, "security_list")},
    )


@login_required
def edit_security(request, security_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    security = get_object_or_404(Security, id=security_id, workspace=member.workspace)
    form = SecurityForm(request.POST or None, instance=security)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Security updated.")
        return redirect(return_url(request, "security_list"))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": "Security", "next": return_url(request, "security_list")},
    )


@login_required
def delete_security(request, security_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    security = get_object_or_404(Security, id=security_id, workspace=member.workspace)
    if request.method == "POST":
        security.delete()
        messages.success(
            request, "Security deleted. Linked Grants need relinking for Section 104 reporting."
        )
        return redirect(return_url(request, "security_list"))
    return render(
        request,
        "ledger/confirm_delete_security.html",
        {"security": security, "next": return_url(request, "security_list")},
    )


@login_required
def section_104_working_paper(request):
    member = request_membership(request)
    security_id = request.GET.get("security")
    securities = Security.objects.filter(workspace=member.workspace)
    if security_id:
        securities = securities.filter(id=security_id)
    grants = list(
        Grant.objects.filter(workspace=member.workspace).select_related("security", "broker")
    )
    vests = list(Vest.objects.filter(workspace=member.workspace).select_related("broker"))
    sales = list(Sale.objects.filter(workspace=member.workspace).select_related("broker"))
    purchases = list(
        Purchase.objects.filter(workspace=member.workspace).select_related("broker", "security")
    )
    adjustments = list(PoolAdjustment.objects.filter(workspace=member.workspace))
    opening_balances = {
        balance.security_id: balance
        for balance in Section104OpeningBalance.objects.filter(workspace=member.workspace)
    }
    reports = []
    for security in securities:
        events = [
            event
            for event in [*vests, *sales, *purchases]
            if (
                event.security_id == security.id
                if isinstance(event, Purchase)
                else event_security(event, grants) == security
            )
        ]
        identities = {
            (
                getattr(event, "beneficial_owner", ""),
                getattr(event, "capacity", "personal"),
                getattr(event, "account_reference", ""),
            )
            for event in events
        }
        if len(identities) <= 1:
            reports.append(
                section_104_report(
                    security,
                    grants,
                    vests,
                    sales,
                    opening_balances.get(security.id),
                    purchases,
                    adjustments,
                )
            )
        else:
            for identity in sorted(identities):
                reports.append(
                    section_104_report(
                        security, grants, vests, sales, None, purchases, adjustments, identity
                    )
                )
    return render(
        request,
        "ledger/section_104.html",
        {
            "membership": member,
            "reports": reports,
            "securities": Security.objects.filter(workspace=member.workspace),
            "selected_security": security_id,
        },
    )


def section104_snapshot_payload(report):
    return {
        "security": report.security.id,
        "pool_units": str(report.pool_units),
        "pool_cost": None if report.pool_cost is None else str(report.pool_cost),
        "warnings": report.warnings,
        "disposals": [
            {
                "sale_id": getattr(disposal.sale, "id", None),
                "date": event_date(disposal.sale).isoformat(),
                "units": str(disposal.sale.units),
                "matches": [
                    {
                        "kind": match.kind,
                        "units": str(match.units),
                        "cost": None if match.cost is None else str(match.cost),
                        "proceeds": None if match.proceeds is None else str(match.proceeds),
                    }
                    for match in disposal.matches
                ],
                "warnings": disposal.warnings,
            }
            for disposal in report.disposals
        ],
    }


@login_required
def save_section_104_snapshot(request, security_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    security = get_object_or_404(Security, id=security_id, workspace=member.workspace)
    grants = list(
        Grant.objects.filter(workspace=member.workspace).select_related("security", "broker")
    )
    vests = list(
        Vest.objects.filter(workspace=member.workspace).select_related("broker", "security")
    )
    sales = list(
        Sale.objects.filter(workspace=member.workspace).select_related("broker", "security")
    )
    purchases = list(
        Purchase.objects.filter(workspace=member.workspace).select_related("broker", "security")
    )
    adjustments = list(PoolAdjustment.objects.filter(workspace=member.workspace))
    opening = Section104OpeningBalance.objects.filter(
        workspace=member.workspace, security=security
    ).first()
    report = section_104_report(security, grants, vests, sales, opening, purchases, adjustments)
    payload = section104_snapshot_payload(report)
    payload["inputs"] = {
        "grants": [
            {
                "id": grant.id,
                "security_id": grant.security_id,
                "date": grant.date.isoformat(),
                "units": str(grant.units),
            }
            for grant in grants
        ],
        "vests": [
            {
                "id": vest.id,
                "security_id": vest.security_id,
                "date": event_date(vest).isoformat(),
                "units": str(vest.units),
                "withheld_units": str(vest.withheld_units),
                "capital_cost_gbp": None
                if vest.capital_cost_gbp is None
                else str(vest.capital_cost_gbp),
            }
            for vest in vests
        ],
        "sales": [
            {
                "id": sale.id,
                "security_id": sale.security_id,
                "date": event_date(sale).isoformat(),
                "units": str(sale.units),
                "proceeds_gbp": None if sale.proceeds_gbp is None else str(sale.proceeds_gbp),
                "fees_gbp": str(sale.fees_gbp),
            }
            for sale in sales
        ],
        "purchases": [
            {
                "id": purchase.id,
                "security_id": purchase.security_id,
                "date": event_date(purchase).isoformat(),
                "units": str(purchase.units),
                "capital_cost_gbp": None
                if purchase.capital_cost_gbp is None
                else str(purchase.capital_cost_gbp),
                "fees_gbp": str(purchase.fees_gbp),
            }
            for purchase in purchases
        ],
        "adjustments": [
            {
                "id": adjustment.id,
                "security_id": adjustment.security_id,
                "effective_on": adjustment.effective_on.isoformat(),
                "units_delta": str(adjustment.units_delta),
                "cost_delta_gbp": str(adjustment.cost_delta_gbp),
            }
            for adjustment in adjustments
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    Section104Snapshot.objects.create(
        workspace=member.workspace,
        security=security,
        engine_version="section104-v2",
        input_hash=hashlib.sha256(encoded).hexdigest(),
        payload=payload,
    )
    messages.success(request, "Section 104 snapshot saved.")
    return redirect(return_url(request, "section_104_working_paper"))


@login_required
def section_104_reconciliation(request):
    member = request_membership(request)
    workspace = member.workspace
    issues = []
    for label, event_model in (("Vest", Vest), ("Sale", Sale)):
        for event in event_model.objects.filter(workspace=workspace).select_related(
            "security", "broker"
        ):
            inferred_id = infer_event_security(event)
            if event.security_id is None and inferred_id is None:
                issues.append((label, event, "No direct Security and no unique Grant match"))
            elif event.security_id is None and inferred_id is not None:
                issues.append((label, event, "Security link is missing; save again to enrich"))
            elif inferred_id is not None and inferred_id != event.security_id:
                issues.append((label, event, "Direct Security differs from Grant Security"))
    for purchase in Purchase.objects.filter(workspace=workspace).select_related(
        "security", "broker"
    ):
        if purchase.security_id is None:
            issues.append(("Purchase", purchase, "No Security selected"))
    return render(
        request,
        "ledger/section_104_reconciliation.html",
        {
            "membership": member,
            "issues": issues,
            "snapshot_count": Section104Snapshot.objects.filter(workspace=workspace).count(),
        },
    )


@login_required
def add_section_104_opening_balance(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = Section104OpeningBalanceForm(request.POST or None, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        balance = form.save(commit=False)
        balance.workspace = member.workspace
        balance.save()
        messages.success(request, "Section 104 opening balance saved.")
        return redirect(return_url(request, "section_104_working_paper"))
    return render(
        request,
        "ledger/form.html",
        {
            "form": form,
            "title": "Section 104 opening balance",
            "next": return_url(request, "section_104_working_paper"),
        },
    )


@login_required
def edit_section_104_opening_balance(request, balance_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    balance = get_object_or_404(Section104OpeningBalance, id=balance_id, workspace=member.workspace)
    form = Section104OpeningBalanceForm(
        request.POST or None, instance=balance, workspace=member.workspace
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Section 104 opening balance updated.")
        return redirect(return_url(request, "section_104_working_paper"))
    return render(
        request,
        "ledger/form.html",
        {
            "form": form,
            "title": "Edit Section 104 opening balance",
            "next": return_url(request, "section_104_working_paper"),
        },
    )


@login_required
def delete_section_104_opening_balance(request, balance_id):
    return delete_record(
        request,
        Section104OpeningBalance,
        balance_id,
        "Section 104 opening balance",
        "section_104_working_paper",
    )


@login_required
def add_purchase(request):
    return add_record(request, PurchaseForm, "Purchase", "section_104_working_paper")


@login_required
def edit_purchase(request, purchase_id):
    return edit_record(
        request, Purchase, PurchaseForm, purchase_id, "Purchase", "section_104_working_paper"
    )


@login_required
def delete_purchase(request, purchase_id):
    return delete_record(request, Purchase, purchase_id, "purchase", "section_104_working_paper")


@login_required
def add_pool_adjustment(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = PoolAdjustmentForm(request.POST or None, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        adjustment = form.save(commit=False)
        adjustment.workspace = member.workspace
        adjustment.save()
        messages.success(request, "Pool adjustment saved.")
        return redirect(return_url(request, "section_104_working_paper"))
    return render(
        request,
        "ledger/form.html",
        {
            "form": form,
            "title": "Pool adjustment",
            "next": return_url(request, "section_104_working_paper"),
        },
    )


def add_record(request, form_class, title, fallback):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = form_class(request.POST or None, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.workspace = member.workspace
        try:
            ensure_event_rate(member.workspace, item.date)
        except EventRateUnavailable as exc:
            form.add_error("date", str(exc))
        else:
            item.save()
            messages.success(request, f"{title} saved.")
            return redirect(return_url(request, fallback))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": title, "next": return_url(request, fallback)},
    )


@login_required
def add_grant(request):
    return add_record(request, GrantForm, "Grant", "grant_list")


@login_required
def edit_grant(request, grant_id):
    return edit_record(request, Grant, GrantForm, grant_id, "Grant", "grant_list")


@login_required
def delete_grant(request, grant_id):
    return delete_record(request, Grant, grant_id, "grant", "grant_list")


def edit_record(request, model, form_class, record_id, title, fallback):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    record = get_object_or_404(model, id=record_id, workspace=member.workspace)
    form = form_class(request.POST or None, instance=record, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        try:
            ensure_event_rate(member.workspace, form.cleaned_data["date"])
        except EventRateUnavailable as exc:
            form.add_error("date", str(exc))
        else:
            form.save()
            messages.success(request, f"{title} updated.")
            return redirect(return_url(request, fallback))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": f"Edit {title.lower()}", "next": return_url(request, fallback)},
    )


def delete_record(request, model, record_id, title, fallback):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    record = get_object_or_404(model, id=record_id, workspace=member.workspace)
    if request.method == "POST":
        record.delete()
        messages.success(request, f"{title.capitalize()} deleted.")
        return redirect(return_url(request, fallback))
    return render(
        request,
        "ledger/confirm_delete_record.html",
        {"record": record, "title": title, "next": return_url(request, fallback)},
    )


@login_required
def add_price(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = StockPriceForm(request.POST or None, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        price = form.save(commit=False)
        price.workspace = member.workspace
        price.save()
        messages.success(request, "Stock price saved.")
        return redirect(return_url(request, "price_list"))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": "Stock price", "next": return_url(request, "price_list")},
    )


@login_required
def edit_price(request, price_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    price = get_object_or_404(StockPrice, id=price_id, workspace=member.workspace)
    form = StockPriceForm(request.POST or None, instance=price, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Stock price updated.")
        return redirect(return_url(request, "price_list"))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": "Stock price", "next": return_url(request, "price_list")},
    )


@login_required
def delete_price(request, price_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    price = get_object_or_404(StockPrice, id=price_id, workspace=member.workspace)
    if request.method == "POST":
        price.delete()
        messages.success(request, "Stock price deleted.")
        return redirect(return_url(request, "price_list"))
    return render(
        request,
        "ledger/confirm_delete_price.html",
        {"price": price, "next": return_url(request, "price_list")},
    )


@login_required
def add_vest(request):
    return add_record(request, VestForm, "Vest", "vest_list")


@login_required
def edit_vest(request, vest_id):
    return edit_record(request, Vest, VestForm, vest_id, "Vest", "vest_list")


@login_required
def delete_vest(request, vest_id):
    return delete_record(request, Vest, vest_id, "vest", "vest_list")


@login_required
def add_sale(request):
    return add_record(request, SaleForm, "Sale", "sale_list")


@login_required
def edit_sale(request, sale_id):
    return edit_record(request, Sale, SaleForm, sale_id, "Sale", "sale_list")


@login_required
def delete_sale(request, sale_id):
    return delete_record(request, Sale, sale_id, "sale", "sale_list")


@login_required
def broker_management(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    sort_options = [("name", "Name A–Z"), ("-name", "Name Z–A")]
    brokers, search, sort = filtered_table(
        request,
        Broker.objects.filter(workspace=member.workspace),
        ["name"],
        sort_options,
        "name",
    )
    return render(
        request,
        "ledger/brokers.html",
        {"brokers": brokers, "q": search, "sort": sort, "sort_options": sort_options},
    )


@login_required
def broker_grant_ids(request, broker_id):
    """Return only the current workspace's non-blank Grant IDs for a broker."""
    member = request_membership(request)
    broker = get_object_or_404(Broker, id=broker_id, workspace=member.workspace)
    grant_ids = (
        grants_for_event_broker(Grant.objects.filter(workspace=member.workspace), broker)
        .exclude(grant_id="")
        .order_by("grant_id")
        .values_list("grant_id", flat=True)
        .distinct()
    )
    return JsonResponse({"grant_ids": list(grant_ids)})


@login_required
def add_broker(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = BrokerForm(request.POST or None, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        broker = form.save(commit=False)
        broker.workspace = member.workspace
        broker.save()
        messages.success(request, "Broker saved.")
        return redirect(return_url(request, "broker_management"))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": "broker", "next": return_url(request, "broker_management")},
    )


@login_required
def edit_broker(request, broker_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    broker = get_object_or_404(Broker, id=broker_id, workspace=member.workspace)
    form = BrokerForm(request.POST or None, instance=broker, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Broker updated.")
        return redirect(return_url(request, "broker_management"))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": "broker", "next": return_url(request, "broker_management")},
    )


@login_required
def delete_broker(request, broker_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    broker = get_object_or_404(Broker, id=broker_id, workspace=member.workspace)
    if request.method == "POST":
        broker.delete()
        messages.success(
            request, "Broker deleted. Associated records no longer have a broker assigned."
        )
        return redirect(return_url(request, "broker_management"))
    return render(
        request,
        "ledger/confirm_delete_broker.html",
        {"broker": broker, "next": return_url(request, "broker_management")},
    )


@login_required
def import_etrade_history(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = BenefitHistoryImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            importers = {
                "etrade_benefit_history": import_etrade_benefit_history,
                "legacy_stock_transactions": import_legacy_stock_transactions,
                "legacy_restricted_stock": import_legacy_restricted_stock,
                "schwab_equity_details": import_schwab_equity_details,
                "schwab_transaction_history": import_schwab_transaction_history,
            }
            counts = importers[form.cleaned_data["import_type"]](
                form.cleaned_data["file"], member.workspace
            )
        except UnsupportedImport as exc:
            form.add_error("file", str(exc))
        else:
            messages.success(
                request,
                "Imported {grants} grants, {vests} vests and {sales} sales; "
                "{duplicates} existing events skipped. {missing_sale_prices} sales need a USD price.".format(
                    **counts
                ),
            )
            if counts.get("unrecognised_transaction_types"):
                messages.warning(
                    request,
                    "These transaction types were not imported because their "
                    f"meaning is not mapped yet: {counts['unrecognised_transaction_types']}.",
                )
            return redirect(return_url(request, "dashboard"))
    return render(
        request,
        "ledger/import.html",
        {"form": form, "next": return_url(request, "dashboard")},
    )


@login_required
def add_rate(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = FxRateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        rate = form.save(commit=False)
        rate.workspace = member.workspace
        rate.save()
        messages.success(request, "Exchange rate saved.")
        return redirect(return_url(request, "rate_list"))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": "Exchange rate", "next": return_url(request, "rate_list")},
    )


@login_required
def fetch_hmrc_rate(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = HmrcRateFetchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            rate = fetch_usd_rate(form.cleaned_data["method"], form.cleaned_data["rate_date"])
        except HmrcRateUnavailable as exc:
            form.add_error(None, str(exc))
        else:
            FxRate.objects.update_or_create(
                workspace=member.workspace,
                method=rate.method,
                starts_on=rate.starts_on,
                ends_on=rate.ends_on,
                defaults={
                    "label": rate.label,
                    "usd_per_gbp": rate.usd_per_gbp,
                    "source_url": rate.source_url,
                },
            )
            messages.success(request, "HMRC USD rate retrieved and saved.")
            return redirect(return_url(request, "rate_list"))
    return render(
        request,
        "ledger/fetch_hmrc_rate.html",
        {"form": form, "next": return_url(request, "rate_list")},
    )


@login_required
def fetch_wise_rate(request):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = WiseRateFetchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            rate = fetch_wise_usd_rate(form.cleaned_data["rate_date"])
        except WiseRateUnavailable as exc:
            form.add_error(None, str(exc))
        else:
            FxRate.objects.update_or_create(
                workspace=member.workspace,
                method=rate.method,
                starts_on=rate.starts_on,
                ends_on=rate.ends_on,
                defaults={
                    "label": rate.label,
                    "usd_per_gbp": rate.usd_per_gbp,
                    "source_url": rate.source_url,
                },
            )
            messages.success(request, "Wise GBP/USD rate retrieved and saved.")
            return redirect(return_url(request, "rate_list"))
    return render(
        request,
        "ledger/fetch_wise_rate.html",
        {"form": form, "next": return_url(request, "rate_list")},
    )


@login_required
def edit_rate(request, rate_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    rate = get_object_or_404(FxRate, id=rate_id, workspace=member.workspace)
    form = FxRateForm(request.POST or None, instance=rate)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Exchange rate updated.")
        return redirect(return_url(request, "rate_list"))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": "Edit HMRC rate", "next": return_url(request, "rate_list")},
    )


@login_required
def delete_rate(request, rate_id):
    member = request_membership(request)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    rate = get_object_or_404(FxRate, id=rate_id, workspace=member.workspace)
    if request.method == "POST":
        rate.delete()
        messages.success(request, "Exchange rate deleted.")
        return redirect(return_url(request, "rate_list"))
    return render(
        request,
        "ledger/confirm_delete_rate.html",
        {"rate": rate, "next": return_url(request, "rate_list")},
    )


@login_required
def access_management(request):
    member = request_membership(request)
    if member.role != "owner":
        return HttpResponseForbidden("Owner permission required")
    form = MembershipForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = get_user_model().objects.get(email__iexact=form.cleaned_data["email"])
        except get_user_model().DoesNotExist:
            form.add_error("email", "This user must sign in once before access can be granted.")
        else:
            WorkspaceMembership.objects.update_or_create(
                workspace=member.workspace, user=user, defaults={"role": form.cleaned_data["role"]}
            )
            messages.success(request, "Access updated.")
            return redirect("access_management")
    return render(
        request,
        "ledger/access.html",
        {
            "form": form,
            "members": member.workspace.memberships.select_related("user").order_by("user__email"),
        },
    )


@login_required
def remove_workspace_access(request, membership_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    member = request_membership(request)
    if member.role != "owner":
        return HttpResponseForbidden("Owner permission required")
    target = get_object_or_404(WorkspaceMembership, id=membership_id, workspace=member.workspace)
    if target.user_id == request.user.id:
        messages.error(request, "The active owner cannot remove their own access.")
    elif (
        target.role == WorkspaceMembership.Role.OWNER
        and not member.workspace.memberships.filter(role=WorkspaceMembership.Role.OWNER)
        .exclude(id=target.id)
        .exists()
    ):
        messages.error(request, "A ledger must retain at least one owner.")
    else:
        target.delete()
        messages.success(request, "Ledger access removed.")
    return redirect("access_management")

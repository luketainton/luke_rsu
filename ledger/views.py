from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import (
    BenefitHistoryImportForm,
    BrokerForm,
    FxRateForm,
    GrantForm,
    HmrcRateFetchForm,
    MembershipForm,
    SaleForm,
    VestForm,
    WiseRateFetchForm,
)
from .hmrc import HmrcRateUnavailable, fetch_usd_rate
from .importers import UnsupportedImport, import_etrade_benefit_history
from .models import Broker, FxRate, Grant, Sale, Vest, WorkspaceMembership
from .wise import WiseRateUnavailable
from .wise import fetch_usd_rate as fetch_wise_usd_rate


def private_membership(user):
    return (
        user.workspace_memberships.select_related("workspace")
        .order_by("workspace__created_at")
        .first()
    )


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
def dashboard(request):
    member = private_membership(request.user)
    workspace = member.workspace
    vests = Vest.objects.filter(workspace=workspace)
    sales = Sale.objects.filter(workspace=workspace)
    context = {
        "membership": member,
        "grant_count": Grant.objects.filter(workspace=workspace).count(),
        "vest_count": vests.count(),
        "sale_count": sales.count(),
        "rate_count": FxRate.objects.filter(workspace=workspace).count(),
    }
    context["held"] = sum((v.units - v.withheld_units for v in vests), Decimal()) - sum(
        (s.units for s in sales), Decimal()
    )
    return render(request, "ledger/dashboard.html", context)


def list_records(request, model, template, context_name, order_by):
    member = private_membership(request.user)
    records = (
        model.objects.filter(workspace=member.workspace).select_related("broker").order_by(order_by)
    )
    return render(request, template, {"membership": member, context_name: records})


@login_required
def grant_list(request):
    return list_records(request, Grant, "ledger/grants.html", "grants", "-date")


@login_required
def vest_list(request):
    return list_records(request, Vest, "ledger/vests.html", "vests", "-date")


@login_required
def sale_list(request):
    return list_records(request, Sale, "ledger/sales.html", "sales", "-date")


@login_required
def rate_list(request):
    member = private_membership(request.user)
    return render(
        request,
        "ledger/rates.html",
        {
            "membership": member,
            "rates": FxRate.objects.filter(workspace=member.workspace).order_by("-ends_on"),
        },
    )


def add_record(request, form_class, title, fallback):
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = form_class(request.POST or None, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.workspace = member.workspace
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
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    record = get_object_or_404(model, id=record_id, workspace=member.workspace)
    form = form_class(request.POST or None, instance=record, workspace=member.workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{title} updated.")
        return redirect(return_url(request, fallback))
    return render(
        request,
        "ledger/form.html",
        {"form": form, "title": f"Edit {title.lower()}", "next": return_url(request, fallback)},
    )


def delete_record(request, model, record_id, title, fallback):
    member = private_membership(request.user)
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
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    return render(
        request,
        "ledger/brokers.html",
        {"brokers": Broker.objects.filter(workspace=member.workspace)},
    )


@login_required
def add_broker(request):
    member = private_membership(request.user)
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
    member = private_membership(request.user)
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
    member = private_membership(request.user)
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
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = BenefitHistoryImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            counts = import_etrade_benefit_history(form.cleaned_data["file"], member.workspace)
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
            return redirect(return_url(request, "dashboard"))
    return render(
        request,
        "ledger/import.html",
        {"form": form, "next": return_url(request, "dashboard")},
    )


@login_required
def add_rate(request):
    member = private_membership(request.user)
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
    member = private_membership(request.user)
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
    member = private_membership(request.user)
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
    member = private_membership(request.user)
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
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    rate = get_object_or_404(FxRate, id=rate_id, workspace=member.workspace)
    if request.method == "POST":
        rate.delete()
        messages.success(request, "HMRC rate deleted.")
        return redirect(return_url(request, "rate_list"))
    return render(
        request,
        "ledger/confirm_delete_rate.html",
        {"rate": rate, "next": return_url(request, "rate_list")},
    )


@login_required
def access_management(request):
    member = private_membership(request.user)
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

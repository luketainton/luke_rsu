from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from .forms import FxRateForm, GrantForm, MembershipForm, SaleForm, VestForm
from .models import FxRate, Grant, Sale, Vest, WorkspaceMembership


def private_membership(user):
    return (
        user.workspace_memberships.select_related("workspace")
        .order_by("workspace__created_at")
        .first()
    )


def can_edit(member):
    return member.role in {"owner", "editor"}


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
    context = {
        "membership": member,
        "grants": Grant.objects.filter(workspace=workspace).order_by("-date"),
        "vests": Vest.objects.filter(workspace=workspace).order_by("-date"),
        "sales": Sale.objects.filter(workspace=workspace).order_by("-date"),
        "rates": FxRate.objects.filter(workspace=workspace).order_by("-ends_on"),
    }
    context["held"] = sum((v.units - v.withheld_units for v in context["vests"]), Decimal()) - sum(
        (s.units for s in context["sales"]), Decimal()
    )
    return render(request, "ledger/dashboard.html", context)


def add_record(request, form_class, title):
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.workspace = member.workspace
        item.save()
        messages.success(request, f"{title} saved.")
        return redirect("dashboard")
    return render(request, "ledger/form.html", {"form": form, "title": title})


@login_required
def add_grant(request):
    return add_record(request, GrantForm, "Grant")


@login_required
def edit_grant(request, grant_id):
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    grant = get_object_or_404(Grant, id=grant_id, workspace=member.workspace)
    form = GrantForm(request.POST or None, instance=grant)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Grant updated.")
        return redirect("dashboard")
    return render(request, "ledger/form.html", {"form": form, "title": "Edit grant"})


@login_required
def delete_grant(request, grant_id):
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    grant = get_object_or_404(Grant, id=grant_id, workspace=member.workspace)
    if request.method == "POST":
        grant.delete()
        messages.success(request, "Grant deleted.")
        return redirect("dashboard")
    return render(request, "ledger/confirm_delete.html", {"grant": grant})


@login_required
def add_vest(request):
    return add_record(request, VestForm, "Vest")


@login_required
def add_sale(request):
    return add_record(request, SaleForm, "Sale")


@login_required
def add_rate(request):
    return add_record(request, FxRateForm, "Exchange rate")


@login_required
def edit_rate(request, rate_id):
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    rate = get_object_or_404(FxRate, id=rate_id, workspace=member.workspace)
    form = FxRateForm(request.POST or None, instance=rate)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "HMRC rate updated.")
        return redirect("dashboard")
    return render(request, "ledger/form.html", {"form": form, "title": "Edit HMRC rate"})


@login_required
def delete_rate(request, rate_id):
    member = private_membership(request.user)
    if not can_edit(member):
        return HttpResponseForbidden("Editor permission required")
    rate = get_object_or_404(FxRate, id=rate_id, workspace=member.workspace)
    if request.method == "POST":
        rate.delete()
        messages.success(request, "HMRC rate deleted.")
        return redirect("dashboard")
    return render(request, "ledger/confirm_delete_rate.html", {"rate": rate})


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

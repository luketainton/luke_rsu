"""Manage write consent from the signed-in RSU user's account."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import MCPApiKey
from .workspaces import active_membership, can_edit


@login_required
@require_GET
def manage_keys(request):
    membership = active_membership(request)
    if membership is None:
        return HttpResponseForbidden("Ledger access required")
    keys = MCPApiKey.objects.filter(membership=membership, expires_at__gt=timezone.now()).order_by(
        "pk"
    )
    return render(
        request, "ledger/mcp_keys.html", {"keys": keys, "can_write": can_edit(membership)}
    )


@login_required
@require_POST
def set_write_access(request, key_id):
    membership = active_membership(request)
    if membership is None or request.POST.get("workspace_id") != str(membership.workspace_id):
        return HttpResponseForbidden("Select the ledger for this key")
    key = get_object_or_404(
        MCPApiKey, pk=key_id, membership=membership, expires_at__gt=timezone.now()
    )
    access = request.POST.get("access")
    if access not in {"read-write", "read-only"}:
        return HttpResponseBadRequest("Invalid access mode")
    if access == "read-write" and not can_edit(membership):
        return HttpResponseForbidden("Editor permission required")
    MCPApiKey.objects.filter(pk=key.pk).update(allow_write=access == "read-write")
    messages.success(request, f"MCP key {key.pk} is set to {access}.")
    return redirect("mcp_keys")

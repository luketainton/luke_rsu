from .workspaces import active_membership, memberships_for


def workspace_membership(request):
    """Make the signed-in user's private workspace role available to shared navigation."""
    if not request.user.is_authenticated:
        return {}
    membership = active_membership(request)
    return {
        "membership": membership,
        "workspaces": memberships_for(request.user),
        "display_name": request.user.get_full_name() or request.user.email,
    }

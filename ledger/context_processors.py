from django.conf import settings

from .workspaces import active_membership, memberships_for


def app_version(request):
    """Make the deployed release version available to shared navigation."""
    return {"app_version": settings.APP_VERSION}


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

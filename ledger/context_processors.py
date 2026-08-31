from .models import WorkspaceMembership


def workspace_membership(request):
    """Make the signed-in user's private workspace role available to shared navigation."""
    if not request.user.is_authenticated:
        return {}
    membership = (
        WorkspaceMembership.objects.filter(user=request.user)
        .select_related("workspace")
        .order_by("workspace__created_at")
        .first()
    )
    return {"membership": membership}

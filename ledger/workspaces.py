from .models import WorkspaceMembership


def memberships_for(user):
    return user.workspace_memberships.select_related("workspace").order_by("workspace__created_at")


def active_membership(request):
    memberships = list(memberships_for(request.user))
    if not memberships:
        return None
    selected_id = request.session.get("active_workspace_id")
    membership = next((item for item in memberships if item.workspace_id == selected_id), None)
    if membership is None:
        membership = memberships[0]
        request.session["active_workspace_id"] = membership.workspace_id
    return membership


def membership_for_workspace(user, workspace_id):
    return (
        WorkspaceMembership.objects.filter(user=user, workspace_id=workspace_id)
        .select_related("workspace")
        .first()
    )

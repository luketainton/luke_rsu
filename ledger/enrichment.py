"""Safe enrichment of legacy securities events from their Grant records."""

from .models import Grant


def infer_event_security(event):
    """Return the unique Grant Security for an event, or ``None``.

    Grant ID is only meaningful together with its broker inside a workspace.
    Never infer across brokers, workspaces, or multiple Security candidates.
    """
    if not event.grant_id:
        return None
    security_ids = set(
        Grant.objects.filter(
            workspace_id=event.workspace_id,
            broker_id=event.broker_id,
            grant_id=event.grant_id,
            security__isnull=False,
        ).values_list("security_id", flat=True)
    )
    if len(security_ids) != 1:
        return None
    return next(iter(security_ids))


def enrich_event_security(event):
    """Populate a missing direct Security link without overriding user input."""
    if getattr(event, "security_id", None) is None:
        event.security_id = infer_event_security(event)
    return event

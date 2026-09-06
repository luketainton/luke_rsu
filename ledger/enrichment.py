"""Safe enrichment of legacy securities events from their Grant records."""

from .broker_rules import grant_accepts_event_broker
from .models import Grant


def infer_event_security(event):
    """Return the unique Grant Security for an event, or ``None``.

    Grant ID is meaningful together with its broker inside a workspace. A
    Schwab-originated grant may also be represented by an E*TRADE event after
    a broker migration; never infer across workspaces or multiple securities.
    """
    if not event.grant_id:
        return None
    grants = Grant.objects.filter(
        workspace_id=event.workspace_id,
        grant_id=event.grant_id,
        security__isnull=False,
    ).select_related("broker")
    security_ids = {
        grant.security_id for grant in grants if grant_accepts_event_broker(grant, event.broker)
    }
    if len(security_ids) != 1:
        return None
    return next(iter(security_ids))


def enrich_event_security(event):
    """Populate a missing direct Security link without overriding user input."""
    if getattr(event, "security_id", None) is None:
        event.security_id = infer_event_security(event)
    return event

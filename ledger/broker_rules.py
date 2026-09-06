"""Broker rules for grants and the later events they represent."""

from django.db.models import Q


def broker_family(name):
    """Return the supported broker family for a broker display name."""
    normalized = (name or "").casefold()
    if "schwab" in normalized:
        return "schwab"
    if "etrade" in normalized or "e*trade" in normalized:
        return "etrade"
    return None


def grant_accepts_event_broker(grant, event_broker):
    """Whether an event broker can be used with a grant's originating broker."""
    if grant is None or event_broker is None:
        return False
    if grant.broker_id == event_broker.id:
        return True

    origin = broker_family(getattr(grant.broker, "name", ""))
    event = broker_family(getattr(event_broker, "name", ""))
    return origin == "schwab" and event in {"schwab", "etrade"}


def grants_for_event_broker(grants, event_broker):
    """Filter grants to those linkable from an event recorded by ``event_broker``."""
    if event_broker is None:
        return grants.none()
    family = broker_family(getattr(event_broker, "name", ""))
    if family == "schwab":
        return grants.filter(broker__name__icontains="schwab")
    if family == "etrade":
        return grants.filter(
            Q(broker__name__icontains="schwab")
            | Q(broker__name__icontains="etrade")
            | Q(broker__name__icontains="e*trade")
        )
    return grants.filter(broker_id=event_broker.id)

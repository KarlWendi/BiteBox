"""Customer-facing order timing labels."""
from datetime import datetime, timezone
from math import ceil


def ready_label(order, now=None):
    """Format saved UTC estimates, rounding remaining partial minutes up."""
    status = order["status"]
    if status == "collected":
        return "Collected"
    if status == "ready":
        return "Ready now"
    if status == "queued":
        return "Waiting to start"
    estimate = order.get("estimated_ready_at")
    if not estimate:
        return "Being prepared"
    try:
        ready_at = datetime.fromisoformat(estimate)
    except (TypeError, ValueError):
        return "Being prepared"
    if ready_at.tzinfo is None:
        ready_at = ready_at.replace(tzinfo=timezone.utc)
    now = now if now is not None else datetime.now(timezone.utc)
    minutes = ceil((ready_at - now).total_seconds() / 60)
    if minutes <= 0:
        return "Ready now"
    return f"Ready in {minutes} {'minute' if minutes == 1 else 'minutes'}"

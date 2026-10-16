STATUS_TRANSITIONS = {
    "queued": "preparing",
    "preparing": "ready",
    "ready": "collected",
}

# A function that validates the status change.
def validate_status_change(current_status, new_status):
    if new_status == "cancelled":
        if current_status in ("queued", "received"):
            return
        raise ValueError(f"Cannot cancel order in status '{current_status}'. Only queued orders can be cancelled.")

    expected_status = STATUS_TRANSITIONS.get(current_status)

    if new_status != expected_status:
        raise ValueError(
            f"Cannot change status from {current_status} to {new_status}."
        )

# Invented per-unit times: burger 3 minutes, fries 2, wrap 4.
PREP_MINUTES = {
    1: 3, 2: 2, 3: 4, 4: 3, 5: 5, 6: 4,
    7: 4, 8: 3, 9: 2, 10: 1, 11: 1, 12: 2, 13: 4,
}

# A function to simulate the preparation queue for orders, 
# assigning each order to the station that becomes free first and calculating waiting times 
# and preparation times for each order, returning a summary of the simulation including average 
# and maximum waiting times.

def simulate_queue(orders, stations=2):
    """Assign orders in ID order to the station that becomes free first."""
    if type(stations) is not int or not 1 <= stations <= 10:
        raise ValueError("Stations must be a whole number from 1 to 10.")

    available_at = [0] * stations
    schedule = []
    for order in sorted(orders, key=lambda order: order["id"]):
        if order["status"] != "queued":
            continue
        items = order.get("items") or [{
            "item_id": order["item_id"],
            "quantity": order["quantity"],
        }]
        preparation = 0
        for item in items:
            item_id = item["item_id"]
            if item_id not in PREP_MINUTES:
                raise ValueError(f"No preparation time configured for product {item_id}.")
            quantity = item["quantity"]
            if type(quantity) is not int or quantity < 1:
                raise ValueError("Queued orders must have positive whole-number quantities.")
            preparation += PREP_MINUTES[item_id] * quantity
        station = min(range(stations), key=lambda index: available_at[index])
        start = available_at[station]
        finish = start + preparation
        available_at[station] = finish
        schedule.append({
            "order_id": order["id"],
            "station": station + 1,
            "prep_minutes": preparation,
            "waiting_minutes": start,
            "ready_after_minutes": finish,
        })

# A variable that contains the length of the schedule as well as the total wait time. 
    count = len(schedule)
    total_wait = sum(entry["waiting_minutes"] for entry in schedule)
    return {
        "stations": stations,
        "order_count": count,
        "average_waiting_minutes": round(total_wait / count, 2) if count else 0,
        "maximum_waiting_minutes": max(
            (entry["waiting_minutes"] for entry in schedule), default=0,
        ),
        "all_ready_after_minutes": max(available_at),
        "schedule": schedule,
    }

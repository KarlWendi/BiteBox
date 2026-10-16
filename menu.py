"""Stage 1: display a fictional takeaway menu. Run with Python 3."""

MENU = [
    {"id": 1, "name": "Cheeseburger", "price_pence": 399, "category": "Burgers"},
    {"id": 2, "name": "Fries", "price_pence": 199, "category": "Sides"},
    {"id": 3, "name": "Wrap", "price_pence": 449, "category": "Mains"},
    {"id": 13, "name": "Mozzarella Sticks", "price_pence": 499, "category": "Sides"},
    {"id": 5, "name": "Chicken Burger", "price_pence": 499, "category": "Burgers"},
    {"id": 6, "name": "Veggie Burger", "price_pence": 479, "category": "Burgers"},
    {"id": 7, "name": "Chicken Nuggets", "price_pence": 349, "category": "Sides"},
    {"id": 8, "name": "Onion Rings", "price_pence": 249, "category": "Sides"},
    {"id": 9, "name": "Side Salad", "price_pence": 299, "category": "Sides"},
    {"id": 10, "name": "Cola", "price_pence": 179, "category": "Drinks"},
    {"id": 11, "name": "Bottled Water", "price_pence": 129, "category": "Drinks"},
    {"id": 12, "name": "Chocolate Milkshake", "price_pence": 329, "category": "Drinks"},
]


def format_price(pence):
    """Turn an integer number of pence into pounds for display."""
    pounds, remaining_pence = divmod(pence, 100)
    return f"£{pounds}.{remaining_pence:02d}"


def display_menu():
    """Print one line for each menu item."""
    print("Takeaway menu")
    for item in MENU:
        price = format_price(item["price_pence"])
        print(f"{item['id']}. {item['name']} - {price}")


if __name__ == "__main__":
    display_menu()

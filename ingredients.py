"""Sensible standard ingredients and dietary tags for BiteBox menu items."""

INGREDIENTS_DATA = {
    1: {
        "name": "Cheeseburger",
        "ingredients": [
            "100% Beef Patty",
            "Cheddar Cheese Slice",
            "Brioche Bun",
            "Pickles",
            "Sliced Onions",
            "Ketchup",
            "Mustard",
        ],
        "dietary": ["Contains Dairy", "Contains Gluten", "Contains Mustard"],
    },
    2: {
        "name": "Fries",
        "ingredients": [
            "Potatoes",
            "Vegetable Oil (Sunflower, Rapeseed)",
            "Sea Salt",
        ],
        "dietary": ["Vegan", "Vegetarian", "Gluten-Free"],
    },
    3: {
        "name": "Wrap",
        "ingredients": [
            "Tortilla Wrap",
            "Crispy Chicken Breast",
            "Crisp Lettuce",
            "Diced Tomatoes",
            "Garlic Mayonnaise",
        ],
        "dietary": ["Contains Gluten", "Contains Egg"],
    },
    5: {
        "name": "Chicken Burger",
        "ingredients": [
            "Crispy Breaded Chicken Breast",
            "Toasted Sesame Seed Bun",
            "Iceberg Lettuce",
            "Creamy Mayonnaise",
        ],
        "dietary": ["Contains Gluten", "Contains Sesame", "Contains Egg"],
    },
    6: {
        "name": "Veggie Burger",
        "ingredients": [
            "Plant-Based Patty (Pea & Potato Protein, Carrots, Sweetcorn)",
            "Vegan Brioche Bun",
            "Baby Spinach",
            "Tomato Slices",
            "Vegan Herb Mayo",
        ],
        "dietary": ["Vegan", "Vegetarian", "Contains Gluten"],
    },
    7: {
        "name": "Chicken Nuggets",
        "ingredients": [
            "Chicken Breast Fillet",
            "Crispy Golden Batter (Wheat Flour, Maize Flour, Salt, Spices)",
            "Vegetable Oil",
        ],
        "dietary": ["Contains Gluten", "Contains Celery"],
    },
    8: {
        "name": "Onion Rings",
        "ingredients": [
            "Whole Sliced Yellow Onions",
            "Beer Batter Coating (Wheat Flour, Starch, Salt, Spices)",
            "Vegetable Oil",
        ],
        "dietary": ["Vegetarian", "Vegan", "Contains Gluten"],
    },
    9: {
        "name": "Side Salad",
        "ingredients": [
            "Mixed Salad Leaves (Romaine, Lollo Rosso, Rocket)",
            "Cherry Tomatoes",
            "Cucumber",
            "Balsamic Vinaigrette (Olive Oil, Balsamic Vinegar, Herbs)",
        ],
        "dietary": ["Vegan", "Vegetarian", "Gluten-Free"],
    },
    10: {
        "name": "Cola",
        "ingredients": [
            "Carbonated Water",
            "Sugar",
            "Caramel Colour (E150d)",
            "Phosphoric Acid",
            "Natural Flavourings (including Caffeine)",
        ],
        "dietary": ["Vegan", "Vegetarian", "Gluten-Free"],
    },
    11: {
        "name": "Bottled Water",
        "ingredients": [
            "Natural Spring Mineral Water",
        ],
        "dietary": ["Vegan", "Vegetarian", "Gluten-Free"],
    },
    12: {
        "name": "Chocolate Milkshake",
        "ingredients": [
            "Whole Milk",
            "Chocolate Dairy Ice Cream",
            "Cocoa Powder",
            "Sugar",
            "Whipped Cream Topping",
        ],
        "dietary": ["Vegetarian", "Contains Dairy"],
    },
    13: {
        "name": "Mozzarella Sticks",
        "ingredients": [
            "Mozzarella Cheese (Pasteurised Cow's Milk)",
            "Seasoned Herb Breadcrumbs (Wheat Flour, Oregano, Basil, Garlic)",
            "Vegetable Oil",
            "Marinara Dipping Sauce",
        ],
        "dietary": ["Vegetarian", "Contains Dairy", "Contains Gluten"],
    },
}


def get_item_ingredients(item_id: int):
    """Retrieve ingredients and dietary tags for a given menu item ID."""
    return INGREDIENTS_DATA.get(item_id, {
        "name": "Menu Item",
        "ingredients": ["Standard freshly prepared ingredients"],
        "dietary": [],
    })

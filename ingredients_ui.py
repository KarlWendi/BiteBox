"""UI rendering for food ingredients and dietary information."""
import streamlit as st
from menu import format_price
from ingredients import get_item_ingredients

ICONS = {
    "Burger": "🍔",
    "Cheeseburger": "🍔",
    "Mozzarella Sticks": "🧀",
    "Chicken Burger": "🍗",
    "Veggie Burger": "🌱",
    "Fries": "🍟",
    "Wrap": "🌯",
    "Chicken Nuggets": "🍗",
    "Onion Rings": "🧅",
    "Side Salad": "🥗",
    "Cola": "🥤",
    "Bottled Water": "💧",
    "Chocolate Milkshake": "🥛",
}


def show_ingredients_page(menu: list[dict]):
    """Display the dedicated ingredients page with item selector and direct ordering."""
    if st.button("🍔 BiteBox", type="tertiary", key="nav_logo_ingredients"):
        st.session_state["ingredients_page"] = False
        st.rerun()

    st.title("BiteBox · Food Ingredients")
    st.caption("Check what goes into our freshly prepared food, dietary tags, and allergens.")

    if not menu:
        st.info("No menu items are currently available.")
        return

    by_id = {item["id"]: item for item in menu}
    item_ids = list(by_id.keys())

    # Determine default selection
    selected_id = st.session_state.get("selected_ingredient_item_id")
    if selected_id not in by_id:
        selected_id = item_ids[0]

    selected_index = item_ids.index(selected_id)

    chosen_id = st.selectbox(
        "Select a food item to view ingredients",
        item_ids,
        index=selected_index,
        format_func=lambda i_id: f"{by_id[i_id]['name']} · {format_price(by_id[i_id]['price_pence'])}",
        key="ingredient_item_selector",
    )
    st.session_state["selected_ingredient_item_id"] = chosen_id

    item = by_id[chosen_id]
    info = get_item_ingredients(chosen_id)

    icon = ICONS.get(item["name"], "🍽️")
    stock_text = f"{item['stock']} available" if item["stock"] > 0 else "Sold out"
    stock_class = "stock" if item["stock"] > 0 else "stock sold"

    st.markdown(
        f"""
        <div class="food-card" style="margin-top: 1rem;">
            <div style="display: flex; align-items: center; gap: 1rem;">
                <div class="food-icon">{icon}</div>
                <div>
                    <div class="food-name" style="font-size: 1.4rem; margin-top: 0;">{item['name']}</div>
                    <div class="food-meta">
                        <span class="food-price" style="font-size: 1.15rem;">{format_price(item['price_pence'])}</span>
                        &nbsp;·&nbsp;
                        <span class="{stock_class}">{stock_text}</span>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([1.2, 0.8], gap="large")

    with col1:
        st.subheader("Ingredients")
        if info.get("ingredients"):
            for ing in info["ingredients"]:
                st.markdown(f"- {ing}")
        else:
            st.write("Fresh standard ingredients.")

        if info.get("dietary"):
            st.subheader("Dietary & Allergen Information")
            tags_html = " ".join(
                f'<span style="display:inline-block; padding: 0.25rem 0.65rem; margin: 0.2rem; border-radius: 999px; background: #e8f4ed; color: #1f6b45; font-size: 0.85rem; font-weight: 700;">{tag}</span>'
                for tag in info["dietary"]
            )
            st.markdown(tags_html, unsafe_allow_html=True)

    with col2:
        st.subheader("Order this item")
        amount = st.session_state.setdefault("trolley", {}).get(chosen_id, 0)
        limit_reached = amount >= min(item["stock"], 50)
        is_sold_out = item["stock"] <= 0

        btn_disabled = is_sold_out or limit_reached
        btn_label = f"Add {item['name']} to trolley"

        if st.button(btn_label, key=f"ingredient_add_{chosen_id}", type="primary", width="stretch", disabled=btn_disabled):
            st.session_state["trolley"][chosen_id] = amount + 1
            st.rerun()

        if is_sold_out:
            st.info(f"{item['name']} is currently sold out.")
        elif amount > 0:
            st.success(f"{amount} currently in your trolley.")
        elif limit_reached:
            st.warning("Maximum quantity reached for your trolley.")

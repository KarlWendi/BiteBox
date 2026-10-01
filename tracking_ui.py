"""Private customer tracking and authenticated staff screens."""
import time

import streamlit as st

from menu import format_price
from order_display import ready_label
import web_client
from web_client import APIError
from account_ui import account_headers


def order_table(orders):
    st.dataframe([{"Order": f"#{o['id']}", "Items": o["name"],
                   "Qty": o["quantity"], "Total": format_price(o["total_pence"]),
                   "Status": o["status"].title(), "Collection": ready_label(o)}
                  for o in orders], hide_index=True, width="stretch")


@st.fragment(run_every="5s")
def customer_orders():
    if st.session_state.get('account_session'):
        try:
            orders = web_client.request_api('GET', '/me/orders', headers=account_headers())
        except APIError as error:
            st.error(str(error))
        else:
            if orders:
                order_table(orders)
            else:
                st.info('Your account has no orders yet.')
    codes = st.session_state.get("tracking_codes", {})
    if not codes and not st.session_state.get('account_session'):
        st.info("Place an order or enter your private tracking code to follow its progress.")
    for code, order_id in list(codes.items()):
        try:
            order = web_client.request_api("POST", "/track", json={"tracking_code": code})
        except APIError as error:
            st.error(str(error))
        else:
            order_table([order])
        with st.expander(f"Save tracking code for order #{order_id}"):
            st.code(code, language=None)
        if st.button(f"Forget order #{order_id}", key=f"forget-{order_id}"):
            del codes[code]
            st.rerun()


@st.fragment(run_every="5s")
def staff_orders():
    account = st.session_state.get('account_session')
    if not account and time.time() >= st.session_state.get("staff_expires", 0):
        st.session_state.pop("staff_auth", None)
        st.rerun()
    access = {'headers': account_headers()} if account else {'auth': st.session_state['staff_auth']}
    try:
        orders = web_client.request_api("GET", "/orders", **access)
    except APIError as error:
        st.error(str(error))
        return
    if orders:
        order_table(orders)
    else:
        st.info("No orders yet.")
    st.caption("Start cooking manually. Ready status is automatic; collection is confirmed by staff.")
    next_status = {"queued": "preparing", "ready": "collected"}
    for order in orders:
        target = next_status.get(order["status"])
        if target and st.button(f"Order #{order['id']}: mark as {target}", key=f"status-{order['id']}-{target}"):
            try:
                web_client.request_api("PATCH", f"/orders/{order['id']}/status", json={"status": target}, **access)
            except APIError as error:
                st.error(str(error))
            else:
                st.session_state["order_notice"] = f"Order #{order['id']} is now {target}."
                st.rerun()
    stations = st.slider("Open kitchen stations", min_value=1, max_value=10, value=2)
    try:
        queue = web_client.request_api("GET", "/queue", params={"stations": stations}, **access)
        left, middle, right = st.columns(3)
        left.metric("Average wait", f"{queue['average_waiting_minutes']} min")
        middle.metric("Longest wait", f"{queue['maximum_waiting_minutes']} min")
        right.metric("Queue cleared", f"{queue['all_ready_after_minutes']} min")
        if queue["schedule"]:
            st.dataframe(queue["schedule"], hide_index=True, width="stretch")
    except APIError as error:
        st.error(str(error))


def show_tracking():
    customer_tab, staff_tab = st.tabs(["Your orders", "Staff"])
    with customer_tab:
        with st.form("track_order", clear_on_submit=True):
            code = st.text_input("Private tracking code", type="password")
            if st.form_submit_button("Track order"):
                try:
                    order = web_client.request_api("POST", "/track", json={"tracking_code": code.strip()})
                except APIError as error:
                    st.error(str(error))
                else:
                    st.session_state.setdefault("tracking_codes", {})[code.strip()] = order["id"]
        st.caption("Save your code to reopen your order later. Anyone with the code can view that order.")
        customer_orders()
    with staff_tab:
        account = st.session_state.get('account_session')
        if account:
            if account['user']['role'] in ('staff', 'admin'):
                staff_orders()
            else:
                st.info('Staff access is required for kitchen controls.')
            return
        if time.time() >= st.session_state.get("staff_expires", 0):
            st.session_state.pop("staff_auth", None)
        if "staff_auth" not in st.session_state:
            with st.form("staff_login", clear_on_submit=True):
                username = st.text_input("Staff username")
                password = st.text_input("Staff password", type="password")
                if st.form_submit_button("Log in"):
                    try:
                        web_client.request_api("GET", "/staff/session", auth=(username, password))
                    except APIError as error:
                        st.error(str(error))
                    else:
                        st.session_state["staff_auth"] = (username, password)
                        st.session_state["staff_expires"] = time.time() + 3600
                        st.rerun()
        else:
            if st.button("Log out"):
                st.session_state.pop("staff_auth", None)
                st.session_state.pop("staff_expires", None)
                st.rerun()
            staff_orders()

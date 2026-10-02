"""Public Streamlit storefront for the takeaway ordering simulator."""
import os
import streamlit as st
from menu import format_price
from tracking_ui import show_tracking
from account_ui import show_account, show_registration, account_headers
from web_client import APIError, request_api

st.set_page_config(page_title="BiteBox | Fresh food, fast", page_icon="🍔", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&family=Outfit:wght@600;700;800&display=swap');
:root{--ink:#17211b;--muted:#68736c;--cream:#f8f4ec;--orange:#ff5a1f;--green:#1f6b45}
.stApp{background:var(--cream);color:var(--ink);font-family:'DM Sans',sans-serif}.block-container{max-width:1180px;padding-top:1.2rem;padding-bottom:4rem}
h1,h2,h3{font-family:'Outfit',sans-serif!important;letter-spacing:-.025em}[data-testid="stHeader"]{background:transparent}
.site-nav{display:flex;align-items:center;justify-content:space-between;padding:.4rem 0 1.2rem}.brand{display:flex;align-items:center;gap:.65rem;font:800 1.35rem 'Outfit'}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:var(--orange);color:#fff}.nav-note{color:var(--muted);font-size:.9rem}
.hero{position:relative;overflow:hidden;padding:3.6rem 4rem;border-radius:30px;color:#fff;background:linear-gradient(120deg,#163f2b,#1f6b45 62%,#2e875c);box-shadow:0 18px 50px rgba(31,107,69,.18)}.hero:after{content:'🍔';position:absolute;right:4%;top:-20%;font-size:14rem;opacity:.16;transform:rotate(-10deg)}.eyebrow{display:inline-block;padding:.42rem .72rem;border-radius:999px;background:#ffffff24;font-weight:700;font-size:.78rem;letter-spacing:.08em;text-transform:uppercase}.hero h1{max-width:650px;margin:.9rem 0 .65rem;color:#fff;font-size:clamp(2.6rem,6vw,5rem);line-height:.94}.hero p{max-width:560px;margin:0;color:#e8f4ed;font-size:1.05rem;line-height:1.65}.hero-points{display:flex;gap:1.4rem;margin-top:1.6rem;font-weight:600;font-size:.88rem}
.kicker{color:var(--orange);font-weight:800;font-size:.78rem;letter-spacing:.09em;text-transform:uppercase;margin-top:2.6rem}.section-title{margin:.2rem 0 .25rem;font:800 2.1rem 'Outfit'}.section-copy{color:var(--muted);margin-bottom:1.25rem}
.food-card{min-height:178px;padding:1.35rem;margin-bottom:1rem;border:1px solid #e8e0d4;border-radius:22px;background:#fff;box-shadow:0 8px 25px #2027230e;transition:.18s}.food-card:hover{transform:translateY(-3px);box-shadow:0 13px 30px #2027231a}.food-icon{display:grid;place-items:center;width:52px;height:52px;border-radius:16px;background:#fff0e8;font-size:1.65rem}.food-name{margin-top:.9rem;font:700 1.05rem 'Outfit'}.food-meta{display:flex;justify-content:space-between;align-items:center;margin-top:.45rem}.food-price{color:var(--green);font-weight:800}.stock{color:var(--muted);font-size:.78rem}.sold{color:#b42318}
.basket{padding:1.35rem;border-radius:24px;background:#fff;border:1px solid #e8e0d4;box-shadow:0 12px 35px #20272312}.basket-title{font:800 1.4rem 'Outfit';margin-bottom:.2rem}.basket-line{display:flex;justify-content:space-between;gap:1rem;padding:.7rem 0;border-bottom:1px solid #eee8df}.basket-line small{color:var(--muted)}.basket-total{display:flex;justify-content:space-between;margin-top:1rem;font:800 1.2rem 'Outfit'}.empty{text-align:center;padding:2.4rem 1rem;color:var(--muted)}.empty span{display:block;font-size:2.5rem;margin-bottom:.5rem}
.footer{margin-top:3.5rem;padding:1.6rem 0;border-top:1px solid #ddd5c9;color:var(--muted);font-size:.84rem;text-align:center}
.stButton>button,.stFormSubmitButton>button{border-radius:12px;font-weight:700;min-height:2.8rem;background:#fff;color:var(--ink);border:1px solid #d9d1c6}.stButton>button:hover,.stFormSubmitButton>button:hover{color:var(--orange);border-color:var(--orange)}.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"]{background:var(--orange);border-color:var(--orange);color:#fff}[data-testid="stForm"]{border:0;padding:0}[data-testid="stMetric"]{padding:1rem;background:#fff;border:1px solid #e8e0d4;border-radius:16px}[data-testid="stDataFrame"]{border-radius:15px;overflow:hidden}button[data-baseweb="tab"]{font-weight:700}
</style>
""", unsafe_allow_html=True)

ICONS={"Burger":"🍔","Cheeseburger":"🧀","Chicken Burger":"🍗","Veggie Burger":"🌱","Fries":"🍟","Wrap":"🌯","Chicken Nuggets":"🍗","Onion Rings":"🧅","Side Salad":"🥗","Cola":"🥤","Bottled Water":"💧","Chocolate Milkshake":"🥛"}

# Navigate within the same session so signing in never loses the customer's meal.
st.markdown('''<style>
.stButton>button[kind="tertiary"]{background:transparent;border:0;color:#1f6b45;text-decoration:underline;padding:0;min-height:1.8rem}
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p {color:#17211b!important;font-weight:700!important}
</style>''', unsafe_allow_html=True)
if st.session_state.get('account_page', False):
    registering = st.session_state['account_page'] == 'register' and not st.session_state.get('account_session')
    st.title('Create a customer account' if registering else 'BiteBox · Your account')
    if st.button('← Back to your order', type='tertiary'):
        st.session_state['account_page'] = False
        st.rerun()
    st.caption('Your trolley is saved while you sign in or create an account.')
    if registering:
        show_registration()
    else:
        show_account()
    st.stop()

account_label = 'Your account' if st.session_state.get('account_session') else "Don't have an account? Create one or sign in"
if st.button(account_label, type='tertiary', key='open_account'):
    st.session_state['account_page'] = True
    st.rerun()

st.markdown("""<div class="site-nav"><div class="brand"><span class="brand-mark">B</span> BiteBox</div><div class="nav-note">Order online · Collect fresh</div></div><section class="hero"><span class="eyebrow">Freshly made · Ready fast</span><h1>Big flavour.<br>Zero fuss.</h1><p>Build your perfect order from our freshly prepared favourites, check out in seconds, and follow it from kitchen to collection.</p><div class="hero-points"><span>✓ Fresh ingredients</span><span>✓ Live order status</span><span>✓ Easy collection</span></div></section>""",unsafe_allow_html=True)
if os.environ.get("TAKEAWAY_TEMPORARY_DEMO")=="1":st.info("Demo mode: orders are simulated, shared by visitors and may reset when the free service restarts.")
notice=st.session_state.pop("order_notice",None)
if notice:st.success(notice)
st.button("↻ Refresh menu and orders")
try:menu=request_api("GET","/menu")
except APIError as error:
    st.error(str(error));st.info("The ordering service may be waking up. Wait a moment, then refresh.");st.stop()
if "trolley" not in st.session_state:st.session_state["trolley"]={}

st.markdown('<div class="kicker">Explore the menu</div><div class="section-title">Made for every craving</div><div class="section-copy">Choose from burgers, sides, lighter bites and drinks.</div>',unsafe_allow_html=True)
for start in range(0,len(menu),4):
    for column,item in zip(st.columns(4),menu[start:start+4]):
        stock=f"{item['stock']} available" if item["stock"] else "Sold out";stock_class="stock" if item["stock"] else "stock sold"
        with column:st.markdown(f'<div class="food-card"><div class="food-icon">{ICONS.get(item["name"],"🍽️")}</div><div class="food-name">{item["name"]}</div><div class="food-meta"><span class="food-price">{format_price(item["price_pence"])}</span><span class="{stock_class}">{stock}</span></div></div>',unsafe_allow_html=True)

st.markdown('<div class="kicker">Your order</div><div class="section-title">Build your meal</div><div class="section-copy">Add different items, review your trolley, then check out once.</div>',unsafe_allow_html=True)
order_column,trolley_column=st.columns([1.15,.85],gap="large");available=[item for item in menu if item["stock"]>0]
with order_column:
    if available:
        by_id={item["id"]:item for item in available}
        with st.form("trolley_form",clear_on_submit=False):
            item_id=st.selectbox("Choose an item",list(by_id),format_func=lambda value:f"{by_id[value]['name']} · {format_price(by_id[value]['price_pence'])}")
            quantity=st.number_input("Quantity",min_value=1,max_value=50,value=1,step=1)
            submitted=st.form_submit_button("Add to trolley",type="primary",width="stretch")
        if submitted:
            new_quantity=st.session_state["trolley"].get(item_id,0)+quantity
            if new_quantity>by_id[item_id]["stock"]:st.error(f"Only {by_id[item_id]['stock']} × {by_id[item_id]['name']} are currently available.")
            elif new_quantity>50:st.error("A trolley can contain at most 50 of one product.")
            else:st.session_state["trolley"][item_id]=new_quantity;st.rerun()
        st.caption("Stock is confirmed when the complete order is checked out.")
    else:st.info("Everything is currently sold out.")

with trolley_column:
    trolley=st.session_state["trolley"];menu_by_id={item["id"]:item for item in menu}
    st.markdown('<div class="basket"><div class="basket-title">Your trolley</div>',unsafe_allow_html=True)
    if trolley:
        total=0
        for product_id,amount in trolley.items():
            item=menu_by_id[product_id];line=item["price_pence"]*amount;total+=line
            st.markdown(f'<div class="basket-line"><span><strong>{item["name"]}</strong><br><small>Qty {amount}</small></span><strong>{format_price(line)}</strong></div>',unsafe_allow_html=True)
        st.markdown(f'<div class="basket-total"><span>Total</span><span>{format_price(total)}</span></div></div>',unsafe_allow_html=True)
        cols=st.columns(min(len(trolley),2))
        for index,product_id in enumerate(list(trolley)):
            item=menu_by_id[product_id]
            with cols[index%len(cols)]:
                if st.button(f"Remove {item['name']}",key=f"remove-{product_id}",width="stretch"):del st.session_state["trolley"][product_id];st.rerun()
        if st.button("Checkout",type="primary",width="stretch"):
            items=[{"item_id":product_id,"quantity":amount} for product_id,amount in trolley.items()]
            try:order=request_api("POST","/checkout",json={"items":items},headers=account_headers())
            except APIError as error:st.error(str(error))
            else:
                if not st.session_state.get('account_session'):
                    st.session_state.setdefault("tracking_codes", {})[order["tracking_code"]] = order["order_id"]
                st.session_state["trolley"]={};st.session_state["order_notice"]=(f"Order #{order['order_id']} placed with {len(order['items'])} item type(s) — {format_price(order['total_pence'])}.");st.rerun()
    else:st.markdown('<div class="empty"><span>🛒</span>Your trolley is empty.<br>Add something delicious to get started.</div></div>',unsafe_allow_html=True)

st.markdown('<div class="kicker">Order tracking</div><div class="section-title">From kitchen to collection</div><div class="section-copy">This view refreshes automatically while food is being prepared.</div>',unsafe_allow_html=True)
show_tracking()
st.markdown('<div class="footer"><strong>BiteBox</strong> · Educational ordering simulation · No payments or real deliveries</div>',unsafe_allow_html=True)

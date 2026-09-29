# BiteBox: a website written in Python

**BiteBox** is the customer-facing brand for this takeaway ordering simulator. It gives the project a memorable identity while the repository name continues to describe the software's purpose.

Streamlit builds the browser interface from website.py. You do not write HTML. web_client.py sends HTTP requests to the existing FastAPI service; database.py remains responsible for transactions and stock.

## Start locally

Open two terminals in the repository folder, using the same Python environment:

```text
python -m pip install -r requirements.txt
```

Terminal one:

```text
python -m uvicorn api:app --reload
```

Terminal two:

```text
python -m streamlit run website.py --server.address 127.0.0.1
```

Open http://127.0.0.1:8501. Keep both terminals running. For the demonstration virtual environment on Windows, replace python with .\.venv\Scripts\python.exe. This is a local website; uploading code to GitHub does not publish a running service.

For one-click startup in VS Code, open `start_website.py` and press the Run button. The launcher starts both services and opens the browser automatically.

## Understand each part

1. st.title, st.columns and st.metric create the menu and price display.
2. GET /menu supplies real database stock. Sold-out items cannot be selected.
3. `st.form` collects a food and quantity. **Add to trolley** stores it in `st.session_state`; it does not change database stock.
4. The trolley displays each line total and the overall total. Customers can remove products before checkout.
5. **Checkout** sends every trolley line to `POST /checkout` as one request.
6. The API validates all items and uses one database transaction. If any product is missing or short of stock, the complete checkout is rejected and all stock remains unchanged.
7. `orders` stores the overall order. `order_items` stores its related products, quantities and price snapshots.
8. A successful checkout clears the trolley, displays a confirmation and refreshes stock and saved orders.
9. The slider changes `GET /queue?stations=...`. For multi-item orders, preparation time is the sum of all line-item preparation times.
10. When staff starts preparation, the database saves `preparation_started_at` and `estimated_ready_at`. The saved-order section polls every five seconds. An elapsed preparing order becomes `ready` automatically on the next poll.

Streamlit reruns the Python script after interactions. That is why POST belongs inside `if submitted`, and why it is never cached or automatically retried. A connection failure may happen after an order was saved: check the saved-order list before submitting again. Duplicate-request protection is still future work.

TAKEAWAY_API_URL optionally changes the service address on the Streamlit server. The browser itself does not call FastAPI; Streamlit's Python process does. Both processes must be able to reach the configured service.

The hosted demo is self-contained. When `TAKEAWAY_TEMPORARY_DEMO=1`, the website runs the same FastAPI routes inside its own process instead of depending on a second free service to wake up. Local development continues to use the separate API process, so the HTTP architecture can still be demonstrated.

## Demonstrate and check

Add two different products, confirm that stock has not changed, remove and re-add a product, then check out. The result should be one order containing two line items, with stock deducted only at checkout. Try a trolley where one product exceeds available stock: the entire checkout is rejected. Stop the API to see the friendly connection error, then restart it. Automated tests use temporary databases and verify the trolley, transaction rollback, migration, status progression and queue timing.

To demonstrate automatic readiness, place an order and use **mark as preparing**. The table shows its UTC ready estimate. Leave the page open: it checks every five seconds and changes the status to **ready** after the calculated preparation duration. **Mark as collected** remains manual because the software cannot know when a customer physically receives the food.

This remains an educational simulation with no payment processing, customer accounts or authentication.

Framework references: [forms](https://docs.streamlit.io/develop/api-reference/execution-flow/st.form), [running an app](https://docs.streamlit.io/develop/concepts/architecture/run-your-app).

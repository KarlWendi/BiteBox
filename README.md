# Takeaway Ordering Simulator

An educational Python project exploring food ordering, inventory and kitchen waiting times. Uses fictional data and is not affiliated with McDonald's or any other restaurant.

[![Python tests](https://github.com/KarlWendi/takeaway-ordering-simulator/actions/workflows/tests.yml/badge.svg)](https://github.com/KarlWendi/takeaway-ordering-simulator/actions/workflows/tests.yml)

## Current stage: 8 — public website

**[Try the live demo](https://takeaway-ordering-demo.onrender.com/)** — no Python installation needed. Free hosting may take about a minute to wake up. Shared fictional stock and orders reset when the service restarts.

The terminal and FastAPI web API share SQLite menu, stock and orders. Both reserve stock and save each order in one transaction. A queue simulator now assigns queued orders to kitchen stations and reports simulated waiting and completion times. It reads a snapshot without changing stock or order status.

Start with [DEMO.md](DEMO.md) for installation and a walkthrough, [RESULTS.md](RESULTS.md) for queue comparisons and assumptions, and [INTERVIEW.md](INTERVIEW.md) for explanation practice. [LEARNING.md](LEARNING.md) follows all six development stages. Developed with AI assistance as a guided learning project.

## Run

See [DEPLOYMENT.md](DEPLOYMENT.md) for public hosting. The free demo uses temporary shared inventory, which resets on server restarts.

### Stage 7: website without handwritten HTML

See [WEBSITE.md](WEBSITE.md) for setup and the request flow. Install requirements, start FastAPI in one terminal, then run this in another:

```text
python -m streamlit run website.py --server.address 127.0.0.1
```

Open http://127.0.0.1:8501 for the menu, order form, saved orders and kitchen estimates. Both servers must remain running. The website calls the API with HTTPX and never edits SQLite directly. GitHub stores the code; the website runs locally.

### Stage 5: compare kitchen stations

Run the standalone demonstration (no external packages or database access needed):

```text
python queue_demo.py
```

It uses three invented orders with preparation durations 6, 2 and 4 minutes:

| Stations | Average wait (minutes) | Longest wait (minutes) | All ready after (minutes) |
| --- | --- | --- | --- |
| 1 | 4.67 | 8 | 12 |
| 2 | 0.67 | 2 | 6 |
| 3 | 0 | 0 | 6 |

For your saved database orders, start the API as below and use GET /queue in /docs. Enter stations 1, execute, then compare with stations 2 or 3. Query example: `/queue?stations=2`. Reads do not create orders or consume stock. Unknown products without a configured preparation time return 409; invalid station counts return 422.

**Assumptions:** all queued orders are available at simulation minute zero; all stations start free, can prepare any item and handle one whole order at a time. Orders are considered in ascending ID order. Per-unit times are invented: burger 3 minutes, fries 2, wrap 4. Quantity multiplies preparation time; there is no batching, travel time or real clock. Existing queued orders remain queued, even if they are old. Repeating the simulation recalculates from zero; it does not cook orders or mark them completed. Adding a product also requires a PREP_MINUTES entry in kitchen.py.

### Stage 4: API (Python 3.11 or newer)

Open the project folder in VS Code, then open its terminal. Install packages with the same Python interpreter you will use to start the server:

```text
python -m pip install -r requirements.txt
python -m uvicorn api:app --reload
```

On Windows, substitute `py` for `python` if needed. If VS Code uses a specific python.exe, select that interpreter and use its terminal, or replace `python` with its full executable path. In PowerShell a quoted executable path needs `&` before it. Do not install sqlite3 separately.

Keep the terminal running and open http://127.0.0.1:8000/docs in a browser. Stop the server with Ctrl+C. `python api.py` alone defines the app but does not start a web server.

| Endpoint | Purpose |
| --- | --- |
| GET / | Show the API greeting |
| GET /menu | Read products and current stock |
| GET /orders | Staff login required: read saved orders |
| GET /queue?stations=2 | Staff login required: simulate the queue |
| GET /staff/session | Verify staff login |
| POST /track | Read one order using its private tracking code |
| PATCH /orders/{id}/status | Staff login required: advance an order |
| POST /orders | Validate, reserve stock and save an order |

In `/docs`, expand GET /menu, choose Try it out, then Execute. Next expand POST /orders and submit:

```json
{"item_id": 1, "quantity": 2}
```

Success returns 201 and an order dictionary with total_pence 798. GET /menu should show stock reduced by two; GET /orders should list the saved order. Every successful POST creates a new order and deducts stock again, so clicking Execute twice places two orders. The API uses the same restaurant.db as the Stage 3 terminal on your computer; your existing data is preserved.

Status codes: 200 = read succeeded; 201 = order created; 404 = product missing; 409 = insufficient stock; 422 = request validation failed. Quoted numbers, booleans, fractions, missing fields and unexpected extra fields are rejected. Use numbers such as `2`, not strings such as `"2"`.

The requirements file pins the three directly used packages to versions tested for this stage. Their supporting dependencies are resolved by pip. HTTPX is needed for API tests, rather than for serving the API itself.

### Stage 3: terminal (no external packages needed)

With Python 3 installed, open a terminal in this folder:

```text
python restaurant.py
```

On Windows, `py restaurant.py` may work if the Python launcher is installed. Earlier stages still run with `python menu.py` or `python ordering.py`. Keep all Python files in the same folder.

Example on a fresh database (the program also prints its database path):

```text
Takeaway menu — current stock
1. Burger - £3.99 (stock: 20)
2. Fries - £1.99 (stock: 30)
3. Wrap - £4.49 (stock: 15)
Saved orders: 0
Product ID (Enter to exit): 1
Quantity (1–50): 2
Saved order #1: 2 x Burger = £7.98
Stock updated. Simulation only; no payment taken.
```

## Development roadmap

- [x] Stage 1: menu, lists, dictionaries, functions and money formatting.
- [x] Stage 2: look up products and calculate an order total; validate inputs.
- [x] Stage 3: persist menu, stock and orders in SQLite; use transactions.
- [x] Stage 4: expose ordering through a FastAPI API.
- [x] Stage 5: simulate kitchen scheduling and compare waiting times.
- [x] Stage 6: document experiments, meaningful tests and a demonstration.
- [x] Stage 7: Streamlit website, API client and interface tests.
- [x] Stage 8: public free demo and hosting documentation.

Each stage will have its own commit and explanation. See [LEARNING.md](LEARNING.md) for the reasoning and exercises.

## Verification

Stage 1 was run with Python and its output checked. Price formatting was also checked at 0, 5, 100 and 399 pence.

Stage 2: six automated tests passed, covering totals, quantity boundaries, invalid quantities/IDs and lookup independent of list position. The terminal flow was checked with valid inputs, an unknown product, zero quantity and non-numeric input.

Stage 3: seven additional database tests passed, including persistence across new connections, reinitialisation without resetting stock, rejected orders and rollback when saving fails. All 13 tests passed together. A separate-process demonstration verified stock and orders survive restarting Python.

Stage 4: eight API tests passed for reads, saved orders, stock updates, errors, strict request validation, persistence and documentation. All 21 tests passed together after installing requirements.txt. Tests use temporary databases and do not change your demonstration stock.

Stage 5: eight algorithm tests and two API tests were added; all 31 project tests passed. Verified sequential and parallel schedules, empty queues, completed-order filtering, station bounds, missing preparation times and simulations leaving inputs and database data unchanged. The standalone demonstration produced the comparison above.

Stage 6 adds a demo guide, recorded results, explanation exercises and a GitHub Actions workflow for Python 3.12 and 3.14. The Actions tab and badge show the current remote test status. The workflow installs requirements, runs all tests and runs the fixed queue example. Tests check temporary databases rather than the demonstration data.

Run the tests from this folder:

```text
python -m unittest -v
```

## Limitations

The site supports a mixed-product trolley, order status changes, private tracking and authenticated customer, staff and administrator accounts. Stock counts finished products; administrators can replace available quantities. There is no ingredient inventory, payment processing, real restaurant integration or duplicate-request protection. The maximum quantity of 50 is an invented demonstration rule. This remains an educational simulation. GitHub hosts the source code; the public demo runs on a separate hosting service.

## Database and files

`database.py` handles SQLite; `restaurant.py` handles the terminal. `ordering.py` supplies shared input validation, and `menu.py` supplies initial products and price formatting. `restaurant.db` is created automatically beside database.py on first run and is ignored by Git. Do not upload your database; someone cloning the code gets a fresh simulation.

Restart `restaurant.py` after placing two burgers: stock should be 18 and the saved order should appear. Press Enter at the product prompt to exit without ordering. Initial products are inserted only when their IDs are missing: editing menu.py does not overwrite existing database prices or reset stock. New products without an entry in INITIAL_STOCK start with zero stock.

## Customer and admin controls

The website includes customer registration, sign-in, personal order history and password changes. Administrators can create staff accounts, enable or disable customer/staff access, update stock and operate the kitchen. Customers cannot access staff or administrator actions.

See [account setup and deployment](DEPLOYMENT.md#customer-and-administrator-accounts) to create the initial administrator using hosting secrets. These features must be deployed before they appear on the public demo.

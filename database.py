# A simple database module for a takeaway ordering system, providing functions to initialise the database, 
# retrieve the menu, place orders, and retrieve all orders, with error handling for item not found and insufficient stock scenarios.
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from menu import MENU
from ordering import validate_order_input
from order_status import validate_status_change
from kitchen import PREP_MINUTES


# Keep the database beside this file, regardless of the terminal's folder.
DATABASE_PATH = Path(__file__).resolve().with_name("restaurant.db")
INITIAL_STOCK = {1: 20, 2: 30, 3: 15, 4: 20, 5: 20, 6: 15, 7: 25, 8: 25, 9: 15, 10: 40, 11: 40, 12: 20}

# Custom exceptions for specific error scenarios in the database operations, allowing the calling code to handle these cases appropriately.
class ItemNotFoundError(ValueError):
    """Requested product does not exist."""

class InsufficientStockError(ValueError):
    """Requested quantity exceeds available stock."""

# A function to connect to the SQLite database, enabling foreign key constraints and returning a connection object for executing SQL queries.
def connect(database_path=DATABASE_PATH):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

# A function to initialise the database, creating the products and orders tables if they do not exist, and populating the products 
# table with initial stock levels.
def initialise_database(database_path=DATABASE_PATH):
    connection = connect(database_path)
    try:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    price_pence INTEGER NOT NULL CHECK(price_pence >= 0),
                    stock INTEGER NOT NULL CHECK(stock >= 0)
                )
            """)
            for item in MENU:
                connection.execute("""
                    INSERT INTO products (id, name, price_pence, stock)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING
                """, (item["id"], item["name"], item["price_pence"],
                      INITIAL_STOCK.get(item["id"], 0)))

            # Older versions stored one product directly in each order. Move
            # those rows into the new order/order_items structure once.
            order_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(orders)"
                ).fetchall()
            }
            if "item_id" in order_columns:
                connection.execute("ALTER TABLE orders RENAME TO legacy_orders")

            connection.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY,
                    total_pence INTEGER NOT NULL CHECK(total_pence >= 0),
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    preparation_started_at TEXT,
                    estimated_ready_at TEXT,
                    status_updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            current_order_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(orders)"
                ).fetchall()
            }
            for column_name, definition in {
                "preparation_started_at": "TEXT",
                "estimated_ready_at": "TEXT",
                "status_updated_at": "TEXT",
                "tracking_hash": "TEXT",
            }.items():
                if column_name not in current_order_columns:
                    connection.execute(
                        f"ALTER TABLE orders ADD COLUMN {column_name} {definition}"
                    )
            connection.execute("""
                UPDATE orders
                SET status_updated_at = COALESCE(status_updated_at, created_at)
            """)
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS orders_tracking_hash ON orders(tracking_hash)")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES products(id),
                    quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 50),
                    unit_price_pence INTEGER NOT NULL CHECK(unit_price_pence >= 0),
                    total_pence INTEGER NOT NULL CHECK(total_pence >= 0),
                    UNIQUE(order_id, item_id)
                )
            """)

            if "item_id" in order_columns:
                connection.execute("""
                    INSERT INTO orders (id, total_pence, status, created_at)
                    SELECT id, total_pence, status, created_at FROM legacy_orders
                """)
                connection.execute("""
                    INSERT INTO order_items (
                        order_id, item_id, quantity,
                        unit_price_pence, total_pence
                    )
                    SELECT legacy_orders.id, legacy_orders.item_id,
                           legacy_orders.quantity, products.price_pence,
                           legacy_orders.total_pence
                    FROM legacy_orders
                    JOIN products ON products.id = legacy_orders.item_id
                """)
                connection.execute("DROP TABLE legacy_orders")
    finally:
        connection.close()

# A function to retrieve the current menu from the database, returning a list of dictionaries representing each menu item,
#  including its ID, name, price in pence, and available stock.
def get_menu(database_path=DATABASE_PATH):
    connection = connect(database_path)
    try:
        rows = connection.execute(
            "SELECT * FROM products ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()

# A function to place an order, validating the input, checking stock availability, updating the stock in the database,
# and inserting a new order record, returning a dictionary with the order details or raising appropriate exceptions for errors.
def place_order(item_id, quantity, database_path=DATABASE_PATH):
    try:
        order = checkout(
            [{"item_id": item_id, "quantity": quantity}],
            database_path,
        )
    except InsufficientStockError as error:
        # Keep the original single-item interface and tests compatible.
        raise InsufficientStockError("Insufficient stock.") from error
    item = order["items"][0]
    return {
        "order_id": order["order_id"],
        "item_id": item["item_id"],
        "name": item["name"],
        "quantity": item["quantity"],
        "total_pence": order["total_pence"],
        "status": order["status"],
        "tracking_code": order["tracking_code"],
    }


def checkout(items, database_path=DATABASE_PATH):
    """Validate and save a complete trolley as one atomic order."""
    if type(items) is not list or not items:
        raise ValueError("The trolley must contain at least one item.")

    combined = {}
    for entry in items:
        if type(entry) is not dict:
            raise ValueError("Each trolley item must contain an item ID and quantity.")
        item_id = entry.get("item_id")
        quantity = entry.get("quantity")
        validate_order_input(item_id, quantity)
        combined[item_id] = combined.get(item_id, 0) + quantity
        if combined[item_id] > 50:
            raise ValueError("The combined quantity for one item cannot exceed 50.")

    connection = connect(database_path)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            lines = []
            for item_id, quantity in combined.items():
                product = connection.execute(
                    "SELECT * FROM products WHERE id = ?", (item_id,)
                ).fetchone()
                if product is None:
                    raise ItemNotFoundError("Menu item not found.")
                if product["stock"] < quantity:
                    raise InsufficientStockError(
                        f"Insufficient stock for {product['name']}."
                    )
                line_total = product["price_pence"] * quantity
                lines.append({
                    "item_id": item_id,
                    "name": product["name"],
                    "quantity": quantity,
                    "unit_price_pence": product["price_pence"],
                    "total_pence": line_total,
                })

            total = sum(line["total_pence"] for line in lines)
            tracking_code = secrets.token_urlsafe(32)
            result = connection.execute(
                "INSERT INTO orders (total_pence, tracking_hash) VALUES (?, ?)",
                (total, hashlib.sha256(tracking_code.encode()).hexdigest()),
            )
            order_id = result.lastrowid
            for line in lines:
                connection.execute("""
                    UPDATE products SET stock = stock - ? WHERE id = ?
                """, (line["quantity"], line["item_id"]))
                connection.execute("""
                    INSERT INTO order_items (
                        order_id, item_id, quantity,
                        unit_price_pence, total_pence
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    order_id, line["item_id"], line["quantity"],
                    line["unit_price_pence"], line["total_pence"],
                ))
            order = {
                "order_id": order_id,
                "total_pence": total,
                "status": "queued",
                "items": lines,
                "tracking_code": tracking_code,
            }
        return order
    finally:
        connection.close()

# A function to retrieve all saved orders from the database, returning a list of dictionaries representing each order,
# including its ID, item ID, name, quantity, total price in pence, status, and creation timestamp.
def get_orders(database_path=DATABASE_PATH, *, tracking_code=None):
    connection = connect(database_path)
    try:
        with connection:
            _mark_elapsed_orders_ready(connection)
        if tracking_code is None:
            rows = connection.execute("SELECT * FROM orders ORDER BY id").fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM orders WHERE tracking_hash = ?",
                (hashlib.sha256(tracking_code.encode()).hexdigest(),),
            ).fetchall()
        orders = []
        for row in rows:
            item_rows = connection.execute("""
                SELECT order_items.item_id, products.name,
                       order_items.quantity, order_items.unit_price_pence,
                       order_items.total_pence
                FROM order_items
                JOIN products ON products.id = order_items.item_id
                WHERE order_items.order_id = ?
                ORDER BY order_items.id
            """, (row["id"],)).fetchall()
            items = [dict(item) for item in item_rows]
            order = dict(row)
            order.pop("tracking_hash", None)
            order["items"] = items
            # These summary fields keep the original single-item interface
            # compatible with the terminal, queue and earlier tests.
            order["item_id"] = items[0]["item_id"] if len(items) == 1 else None
            order["name"] = ", ".join(item["name"] for item in items)
            order["quantity"] = sum(item["quantity"] for item in items)
            orders.append(order)
        return orders
    finally:
        connection.close()

# A function that updates the order status. 
def update_order_status(order_id, new_status, database_path=DATABASE_PATH):
    connection = connect(database_path)

    try:
        with connection:
            # Prevent another writer changing the order during validation.
            connection.execute("BEGIN IMMEDIATE")

            _mark_elapsed_orders_ready(connection)
            order = connection.execute(
                "SELECT status FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()

            if order is None:
                raise ValueError("Order not found.")

            validate_status_change(order["status"], new_status)

            if new_status == "preparing":
                item_rows = connection.execute("""
                    SELECT item_id, quantity FROM order_items
                    WHERE order_id = ?
                """, (order_id,)).fetchall()
                preparation_minutes = 0
                for item in item_rows:
                    if item["item_id"] not in PREP_MINUTES:
                        raise ValueError(
                            f"No preparation time configured for product {item['item_id']}."
                        )
                    preparation_minutes += (
                        PREP_MINUTES[item["item_id"]] * item["quantity"]
                    )
                started_at = datetime.now(timezone.utc).replace(microsecond=0)
                ready_at = started_at + timedelta(minutes=preparation_minutes)
                connection.execute("""
                    UPDATE orders
                    SET status = ?, preparation_started_at = ?,
                        estimated_ready_at = ?, status_updated_at = ?
                    WHERE id = ?
                """, (
                    new_status,
                    _database_timestamp(started_at),
                    _database_timestamp(ready_at),
                    _database_timestamp(started_at),
                    order_id,
                ))
            else:
                connection.execute("""
                    UPDATE orders
                    SET status = ?, status_updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_status, order_id))

        return {"order_id": order_id, "status": new_status}

    finally:
        connection.close()


def _database_timestamp(value):
    """Store UTC in SQLite's sortable timestamp format."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _mark_elapsed_orders_ready(connection):
    """Make elapsed preparation timers ready during the next API poll."""
    connection.execute("""
        UPDATE orders
        SET status = 'ready', status_updated_at = CURRENT_TIMESTAMP
        WHERE status = 'preparing'
          AND estimated_ready_at IS NOT NULL
          AND estimated_ready_at <= CURRENT_TIMESTAMP
    """)
        

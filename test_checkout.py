import tempfile
import unittest
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from api import create_app
from test_support import STAFF_AUTH, configure_staff
from database import checkout, get_menu, get_orders, initialise_database
from kitchen import simulate_queue


class CheckoutDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "checkout.db"
        initialise_database(self.path)

    def test_multiple_items_become_one_order(self):
        order = checkout([
            {"item_id": 1, "quantity": 2},
            {"item_id": 2, "quantity": 1},
        ], self.path)

        self.assertEqual(order["total_pence"], 997)
        self.assertEqual(len(order["items"]), 2)
        self.assertEqual(get_menu(self.path)[0]["stock"], 18)
        self.assertEqual(get_menu(self.path)[1]["stock"], 29)
        self.assertEqual(len(get_orders(self.path)), 1)

    def test_duplicate_products_are_combined(self):
        order = checkout([
            {"item_id": 1, "quantity": 1},
            {"item_id": 1, "quantity": 2},
        ], self.path)

        self.assertEqual(order["items"][0]["quantity"], 3)
        self.assertEqual(get_menu(self.path)[0]["stock"], 17)

    def test_failed_trolley_changes_nothing(self):
        before = get_menu(self.path)
        with self.assertRaisesRegex(ValueError, "Insufficient stock"):
            checkout([
                {"item_id": 1, "quantity": 2},
                {"item_id": 2, "quantity": 31},
            ], self.path)

        self.assertEqual(get_menu(self.path), before)
        self.assertEqual(get_orders(self.path), [])

    def test_existing_single_item_database_is_migrated(self):
        legacy_path = Path(self.folder.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        with connection:
            connection.execute("""
                CREATE TABLE products (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    price_pence INTEGER NOT NULL, stock INTEGER NOT NULL
                )
            """)
            connection.execute(
                "INSERT INTO products VALUES (1, 'Burger', 399, 18)"
            )
            connection.execute("""
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL, total_pence INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "INSERT INTO orders (item_id, quantity, total_pence) "
                "VALUES (1, 2, 798)"
            )
        connection.close()

        initialise_database(legacy_path)

        migrated = get_orders(legacy_path)
        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated[0]["items"][0]["name"], "Burger")
        self.assertEqual(migrated[0]["total_pence"], 798)

    def test_kitchen_sums_all_item_preparation_times(self):
        checkout([
            {"item_id": 1, "quantity": 2},
            {"item_id": 2, "quantity": 1},
        ], self.path)

        result = simulate_queue(get_orders(self.path), stations=1)

        self.assertEqual(result["schedule"][0]["prep_minutes"], 8)


class CheckoutApiTests(unittest.TestCase):
    def setUp(self):
        configure_staff(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.client = self.enterContext(
            TestClient(create_app(Path(folder.name) / "api.db"))
        )
        self.client.auth = STAFF_AUTH

    def test_checkout_endpoint(self):
        response = self.client.post("/checkout", json={"items": [
            {"item_id": 1, "quantity": 2},
            {"item_id": 2, "quantity": 1},
        ]})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["total_pence"], 997)
        self.assertEqual(len(response.json()["items"]), 2)
        self.assertEqual(len(self.client.get("/orders").json()), 1)

    def test_checkout_rejects_empty_trolley(self):
        self.assertEqual(
            self.client.post("/checkout", json={"items": []}).status_code,
            422,
        )

    def test_checkout_rolls_back_all_stock(self):
        response = self.client.post("/checkout", json={"items": [
            {"item_id": 1, "quantity": 2},
            {"item_id": 2, "quantity": 31},
        ]})

        self.assertEqual(response.status_code, 409)
        menu = self.client.get("/menu").json()
        self.assertEqual(menu[0]["stock"], 20)
        self.assertEqual(menu[1]["stock"], 30)


if __name__ == "__main__":
    unittest.main()

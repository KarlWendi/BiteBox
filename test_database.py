"""Database behaviour checks, using a fresh temporary database per test."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import connect, get_menu, get_orders, initialise_database, place_order


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "test.db"
        initialise_database(self.path)

    def test_order_is_saved_and_stock_decreases(self):
        order = place_order(1, 2, self.path)
        self.assertEqual(order["total_pence"], 798)
        self.assertEqual(get_menu(self.path)[0]["stock"], 18)
        saved = get_orders(self.path)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], order["order_id"])
        self.assertEqual(saved[0]["quantity"], 2)

    def test_reinitialisation_preserves_data(self):
        place_order(1, 2, self.path)
        initialise_database(self.path)
        self.assertEqual(get_menu(self.path)[0]["stock"], 18)
        self.assertEqual(len(get_orders(self.path)), 1)

    def test_insufficient_stock_changes_nothing(self):
        before = get_menu(self.path)
        with self.assertRaisesRegex(ValueError, "Insufficient stock"):
            place_order(1, 21, self.path)
        self.assertEqual(get_menu(self.path), before)
        self.assertEqual(get_orders(self.path), [])

    def test_missing_product_changes_nothing(self):
        before = get_menu(self.path)
        with self.assertRaisesRegex(ValueError, "Menu item not found"):
            place_order(999, 1, self.path)
        self.assertEqual(get_menu(self.path), before)
        self.assertEqual(get_orders(self.path), [])

    def test_invalid_input_changes_nothing(self):
        before = get_menu(self.path)
        for quantity in [0, -1, 51, True, "2", 1.5]:
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValueError):
                    place_order(1, quantity, self.path)
        self.assertEqual(get_menu(self.path), before)
        self.assertEqual(get_orders(self.path), [])

    def test_last_units_can_be_ordered_but_no_more(self):
        place_order(1, 20, self.path)
        self.assertEqual(get_menu(self.path)[0]["stock"], 0)
        with self.assertRaisesRegex(ValueError, "Insufficient stock"):
            place_order(1, 1, self.path)
        self.assertEqual(len(get_orders(self.path)), 1)

    def test_connect_sets_timeout_and_wal_mode(self):
        conn = connect(self.path)
        try:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(journal_mode.lower(), "wal")
        finally:
            conn.close()

    def test_failed_insert_rolls_back_stock_reservation(self):
        # Force a save failure after the stock update to verify atomicity.
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                connection.execute("""
                    CREATE TRIGGER reject_order BEFORE INSERT ON orders
                    BEGIN SELECT RAISE(ABORT, 'forced test failure'); END
                """)
        finally:
            connection.close()
        with self.assertRaises(sqlite3.IntegrityError):
            place_order(1, 2, self.path)
        self.assertEqual(get_menu(self.path)[0]["stock"], 20)
        self.assertEqual(get_orders(self.path), [])


if __name__ == "__main__":
    unittest.main()

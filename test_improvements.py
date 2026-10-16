"""Tests for new improvements: menu categories, cancellation & stock restoration, SJF queue comparison, and checkout deduplication."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api import create_app
from database import checkout, get_menu, get_orders, place_order, update_order_status
from kitchen import simulate_queue, simulate_queue_comparison
from test_support import STAFF_AUTH, configure_staff


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        configure_staff(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "test_improvements.db"
        self.client = self.enterContext(TestClient(create_app(self.path)))
        self.client.auth = STAFF_AUTH

    def test_menu_contains_categories(self):
        menu = get_menu(self.path)
        self.assertTrue(all("category" in item for item in menu))
        categories = {item["category"] for item in menu}
        self.assertIn("Burgers", categories)
        self.assertIn("Sides", categories)
        self.assertIn("Drinks", categories)

    def test_order_cancellation_restores_stock(self):
        # Initial stock of Cheeseburger (id 1) is 20
        initial_stock = get_menu(self.path)[0]["stock"]
        self.assertEqual(initial_stock, 20)

        # Place order for 5 Cheeseburgers
        order = place_order(1, 5, self.path)
        self.assertEqual(get_menu(self.path)[0]["stock"], 15)

        # Cancel the order
        update_order_status(order["order_id"], "cancelled", self.path)

        # Stock should be restored back to 20
        self.assertEqual(get_menu(self.path)[0]["stock"], 20)
        orders = get_orders(self.path)
        self.assertEqual(orders[0]["status"], "cancelled")

    def test_unauthenticated_cancellation_is_rejected(self):
        order = place_order(1, 1, self.path)
        unauth_client = TestClient(create_app(self.path))
        res = unauth_client.patch(f"/orders/{order['order_id']}/status", json={"status": "cancelled"})
        self.assertEqual(res.status_code, 401)

    def test_sjf_queue_simulation_and_comparison(self):
        # Order 1: 10 Cheeseburgers (10 * 3 = 30 min)
        # Order 2: 1 Fries (1 * 2 = 2 min)
        place_order(1, 10, self.path)
        place_order(2, 1, self.path)

        fifo = simulate_queue(get_orders(self.path), stations=1, strategy="fifo")
        sjf = simulate_queue(get_orders(self.path), stations=1, strategy="sjf")

        # In FIFO, Order 1 is processed first, Order 2 waits 30 min. Avg wait = (0 + 30)/2 = 15 min
        self.assertEqual(fifo["schedule"][0]["order_id"], 1)
        self.assertEqual(fifo["average_waiting_minutes"], 15.0)

        # In SJF, Order 2 (2 min) is processed first, Order 1 waits 2 min. Avg wait = (0 + 2)/2 = 1 min
        self.assertEqual(sjf["schedule"][0]["order_id"], 2)
        self.assertEqual(sjf["average_waiting_minutes"], 1.0)

        # API comparison endpoint test
        res = self.client.get("/queue?stations=1&compare=true")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["wait_saved_minutes"], 14.0)

    def test_checkout_idempotency_deduplicates_orders(self):
        items = [{"item_id": 1, "quantity": 2}]
        token = "test-dedup-token-123"

        # First checkout submission
        order1 = checkout(items, self.path, idempotency_key=token)
        self.assertEqual(get_menu(self.path)[0]["stock"], 18)
        self.assertEqual(len(get_orders(self.path)), 1)

        # Second checkout submission with same idempotency token
        order2 = checkout(items, self.path, idempotency_key=token)
        self.assertEqual(order2["order_id"], order1["order_id"])

        # Stock should NOT decrease again and order count should remain 1
        self.assertEqual(get_menu(self.path)[0]["stock"], 18)
        self.assertEqual(len(get_orders(self.path)), 1)

        # API checkout idempotency test
        res1 = self.client.post("/checkout", json={"items": items, "idempotency_key": "api-token-456"})
        self.assertEqual(res1.status_code, 201)
        res2 = self.client.post("/checkout", json={"items": items, "idempotency_key": "api-token-456"})
        self.assertEqual(res2.status_code, 201)
        self.assertEqual(res1.json()["order_id"], res2.json()["order_id"])


if __name__ == "__main__":
    unittest.main()

"""Test HTTP behaviour against an isolated temporary SQLite database."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api import create_app
from test_support import STAFF_AUTH, configure_staff


class APITests(unittest.TestCase):
    def setUp(self):
        configure_staff(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "api.db"
        self.client = self.enterContext(TestClient(create_app(self.path)))
        self.client.auth = STAFF_AUTH

    def test_menu_can_be_read(self):
        response = self.client.get("/menu")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["stock"], 20)

    def test_post_saves_order_and_updates_stock(self):
        response = self.client.post("/orders", json={"item_id": 1, "quantity": 2})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["total_pence"], 798)
        self.assertEqual(self.client.get("/menu").json()[0]["stock"], 18)
        self.assertEqual(len(self.client.get("/orders").json()), 1)

    def test_missing_item_returns_404_without_changes(self):
        response = self.client.post("/orders", json={"item_id": 999, "quantity": 1})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Menu item not found.")
        self.assertEqual(self.client.get("/orders").json(), [])
        self.assertEqual(self.client.get("/menu").json()[0]["stock"], 20)

    def test_unavailable_stock_returns_409_without_changes(self):
        response = self.client.post("/orders", json={"item_id": 1, "quantity": 21})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get("/orders").json(), [])
        self.assertEqual(self.client.get("/menu").json()[0]["stock"], 20)

    def test_invalid_json_fields_return_422(self):
        bodies = [
            {"item_id": 1, "quantity": 0},
            {"item_id": 1, "quantity": 51},
            {"item_id": 1, "quantity": "2"},
            {"item_id": 1, "quantity": True},
            {"item_id": 1, "quantity": 1.5},
            {"item_id": -1, "quantity": 1},
            {"item_id": 1},
            {"item_id": 1, "quantity": 1, "unexpected": "field"},
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/orders", json=body).status_code, 422)
        self.assertEqual(self.client.get("/orders").json(), [])
        self.assertEqual(self.client.get("/menu").json()[0]["stock"], 20)

    def test_get_requests_do_not_create_orders(self):
        self.client.get("/orders")
        self.client.get("/menu")
        self.assertEqual(self.client.get("/orders").json(), [])

    def test_orders_survive_a_new_application(self):
        self.client.post("/orders", json={"item_id": 3, "quantity": 4})
        with TestClient(create_app(self.path)) as restarted:
            restarted.auth = STAFF_AUTH
            self.assertEqual(restarted.get("/menu").json()[2]["stock"], 11)
            self.assertEqual(restarted.get("/orders").json()[0]["total_pence"], 1796)

    def test_documentation_is_available(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("post", schema["paths"]["/orders"])

    def test_queue_calculates_without_database_changes(self):
        self.client.post("/orders", json={"item_id": 1, "quantity": 2})
        self.client.post("/orders", json={"item_id": 2, "quantity": 1})
        self.client.post("/orders", json={"item_id": 3, "quantity": 1})
        before_menu = self.client.get("/menu").json()
        before_orders = self.client.get("/orders").json()
        response = self.client.get("/queue?stations=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["all_ready_after_minutes"], 6)
        self.assertEqual(response.json()["average_waiting_minutes"], 0.67)
        self.assertEqual(self.client.get("/queue?stations=1").json()["all_ready_after_minutes"], 12)
        self.assertEqual(self.client.get("/menu").json(), before_menu)
        self.assertEqual(self.client.get("/orders").json(), before_orders)

    def test_invalid_station_query_returns_422(self):
        for stations in ["0", "11", "hello", "1.5"]:
            with self.subTest(stations=stations):
                self.assertEqual(self.client.get(f"/queue?stations={stations}").status_code, 422)


if __name__ == "__main__":
    unittest.main()

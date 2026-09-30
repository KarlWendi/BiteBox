import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api import create_app
from test_support import STAFF_AUTH, configure_staff


class StatusApiTests(unittest.TestCase):
    def setUp(self):
        configure_staff(self)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "test.db"
        self.client_context = TestClient(create_app(self.path))
        self.client = self.client_context.__enter__()
        self.client.auth = STAFF_AUTH
        self.addCleanup(self.client_context.__exit__, None, None, None)

        response = self.client.post(
            "/orders",
            json={"item_id": 1, "quantity": 2},
        )
        self.assertEqual(response.status_code, 201)
        self.order_id = response.json()["order_id"]

    def test_valid_status_change(self):
        response = self.client.patch(
            f"/orders/{self.order_id}/status",
            json={"status": "preparing"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"order_id": self.order_id, "status": "preparing"},
        )
        self.assertEqual(self.client.get("/orders").json()[0]["status"], "preparing")

    def test_skipped_status_is_rejected(self):
        response = self.client.patch(
            f"/orders/{self.order_id}/status",
            json={"status": "ready"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get("/orders").json()[0]["status"], "queued")

    def test_missing_order_returns_not_found(self):
        response = self.client.patch(
            "/orders/999/status",
            json={"status": "preparing"},
        )

        self.assertEqual(response.status_code, 404)

    def test_unexpected_request_field_is_rejected(self):
        response = self.client.patch(
            f"/orders/{self.order_id}/status",
            json={"status": "preparing", "admin": True},
        )

        self.assertEqual(response.status_code, 422)

    def test_api_poll_marks_elapsed_order_ready(self):
        response = self.client.patch(
            f"/orders/{self.order_id}/status",
            json={"status": "preparing"},
        )
        self.assertEqual(response.status_code, 200)

        import sqlite3
        connection = sqlite3.connect(self.path)
        with connection:
            connection.execute(
                "UPDATE orders SET estimated_ready_at = '2000-01-01 00:00:00' "
                "WHERE id = ?",
                (self.order_id,),
            )
        connection.close()

        self.assertEqual(
            self.client.get("/orders").json()[0]["status"],
            "ready",
        )


if __name__ == "__main__":
    unittest.main()

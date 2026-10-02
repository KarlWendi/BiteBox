import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

import web_client
from test_support import STAFF_AUTH, configure_staff


class WebClientRetryTests(unittest.TestCase):
    def tearDown(self):
        web_client._close_embedded_client()

    @patch("web_client.time.sleep")
    @patch("web_client.httpx.request")
    def test_get_retries_while_service_wakes(self, request, sleep):
        waking = Mock(status_code=503, is_error=True)
        ready = Mock(status_code=200, is_error=False)
        ready.json.return_value = {"status": "ready"}
        request.side_effect = [waking, ready]

        result = web_client.request_api("GET", "/")

        self.assertEqual(result, {"status": "ready"})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(web_client.READ_RETRY_SECONDS)

    @patch("web_client.time.sleep")
    @patch("web_client.httpx.request")
    def test_post_is_never_retried(self, request, sleep):
        request.side_effect = httpx.ConnectError("connection lost")

        with self.assertRaises(web_client.APIError):
            web_client.request_api("POST", "/checkout", json={"items": []})

        request.assert_called_once()
        sleep.assert_not_called()

    @patch("web_client.httpx.request")
    def test_public_demo_uses_embedded_api(self, remote_request):
        configure_staff(self)
        from api import create_app
        from database import initialise_database

        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = os.path.join(temporary_directory, "demo.db")
            with (
                patch.dict(os.environ, {"TAKEAWAY_TEMPORARY_DEMO": "1"}),
                patch(
                    "web_client._create_embedded_app",
                    return_value=create_app(database_path),
                ),
                patch(
                    "web_client._initialise_embedded_database",
                    side_effect=lambda: initialise_database(database_path),
                ),
            ):
                result = web_client.request_api("GET", "/menu")
                self.assertEqual(web_client.request_api("GET", "/orders", auth=STAFF_AUTH), [])
                with self.assertRaises(web_client.APIError):
                    web_client.request_api("GET", "/orders")
                web_client._close_embedded_client()

        self.assertGreater(len(result), 3)
        self.assertEqual(result[0]["name"], "Cheeseburger")
        remote_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()

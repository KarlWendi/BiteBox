"""HTTP boundary: the website talks to the API, never directly to SQLite."""
import os
import time
import sqlite3
import httpx

API_URL = os.environ.get("TAKEAWAY_API_URL", "http://127.0.0.1:8000").rstrip("/")
READ_ATTEMPTS = 12
READ_RETRY_SECONDS = 5
TEMPORARY_STATUS_CODES = {502, 503, 504}
_embedded_client = None


class APIError(Exception):
    """A message suitable for displaying beside the form."""


def request_api(method, path, **kwargs):
    method = method.upper()
    if os.environ.get("TAKEAWAY_EMBEDDED_API") == "1" or os.environ.get("TAKEAWAY_TEMPORARY_DEMO") == "1":
        try:
            return _response_data(_request_embedded(method, path, **kwargs))
        except sqlite3.OperationalError:
            raise APIError('Saved data is temporarily unavailable. Please try again shortly.') from None

    attempts = READ_ATTEMPTS if method == "GET" else 1

    for attempt in range(attempts):
        try:
            response = httpx.request(method, API_URL + path, timeout=10, **kwargs)
        except httpx.RequestError as error:
            if method == "GET" and attempt < attempts - 1:
                time.sleep(READ_RETRY_SECONDS)
                continue
            if method == "GET":
                raise APIError(
                    "The free ordering service is still waking up. Please try again shortly."
                ) from error
            raise APIError(
                "Could not reach the ordering service. If you submitted an order, "
                "check saved orders before trying again."
            ) from error

        if (
            method == "GET"
            and response.status_code in TEMPORARY_STATUS_CODES
            and attempt < attempts - 1
        ):
            time.sleep(READ_RETRY_SECONDS)
            continue
        break

    return _response_data(response)


def _request_embedded(method, path, **kwargs):
    """Run the same FastAPI routes in-process for the self-contained public demo."""
    global _embedded_client
    if _embedded_client is None:
        from fastapi.testclient import TestClient

        _initialise_embedded_database()
        _embedded_client = TestClient(_create_embedded_app())
    return _embedded_client.request(method, path, **kwargs)


def _create_embedded_app():
    from api import create_app

    return create_app()


def _initialise_embedded_database():
    from database import DATABASE_PATH, initialise_database

    initialise_database(DATABASE_PATH)


def _close_embedded_client():
    """Close and reset the in-process client (mainly used by tests)."""
    global _embedded_client
    if _embedded_client is not None:
        _embedded_client.close()
        _embedded_client = None


def _response_data(response):
    if response.is_error:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        message = detail if isinstance(detail, str) else "The service could not accept this request."
        raise APIError(message)
    return response.json()

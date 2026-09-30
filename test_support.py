"""Explicit test-only staff credentials; never used by the application."""
import os
from unittest.mock import patch

STAFF_AUTH = ("test-staff", "test-only-password-please-change")


def configure_staff(test):
    test.enterContext(patch.dict(os.environ, {
        "TAKEAWAY_STAFF_USERNAME": STAFF_AUTH[0],
        "TAKEAWAY_STAFF_PASSWORD": STAFF_AUTH[1],
    }))

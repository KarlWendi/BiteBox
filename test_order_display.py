import unittest
from datetime import datetime, timezone

from order_display import ready_label


class OrderDisplayTests(unittest.TestCase):
    def test_countdown_boundaries_and_timezones(self):
        now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
        cases = [
            ("2026-09-30 12:02:00", "Ready in 2 minutes"),
            ("2026-09-30 12:01:01", "Ready in 2 minutes"),
            ("2026-09-30 12:01:00", "Ready in 1 minute"),
            ("2026-09-30 12:00:01", "Ready in 1 minute"),
            ("2026-09-30 12:00:00", "Ready now"),
            ("2026-09-30 11:59:00", "Ready now"),
            ("2026-09-30T13:02:00+01:00", "Ready in 2 minutes"),
            (None, "Being prepared"),
            ("invalid", "Being prepared"),
        ]
        for estimate, expected in cases:
            with self.subTest(estimate=estimate):
                self.assertEqual(ready_label({"status": "preparing", "estimated_ready_at": estimate}, now), expected)

    def test_status_takes_precedence_over_old_estimate(self):
        for status, expected in [("queued", "Waiting to start"), ("ready", "Ready now"), ("collected", "Collected")]:
            with self.subTest(status=status):
                self.assertEqual(ready_label({"status": status, "estimated_ready_at": "2000-01-01 00:00:00"}), expected)

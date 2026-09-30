import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import create_app
from test_support import STAFF_AUTH, configure_staff


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        configure_staff(self)
        folder = self.enterContext(TemporaryDirectory())
        self.path = Path(folder) / 'privacy.db'
        self.client = self.enterContext(TestClient(create_app(self.path)))
        self.first = self.client.post('/checkout', json={'items': [{'item_id': 1, 'quantity': 1}]}).json()
        self.second = self.client.post('/orders', json={'item_id': 2, 'quantity': 1}).json()

    def test_public_cannot_read_orders_queue_or_change_status(self):
        for auth in [None, ('wrong', 'wrong'), ('test-staff', 'wrong')]:
            for method, path, body in [
                ('GET', '/orders', None), ('GET', '/queue', None),
                ('GET', '/staff/session', None),
                ('PATCH', '/orders/1/status', {'status': 'preparing'}),
            ]:
                with self.subTest(auth=auth, path=path):
                    response = self.client.request(method, path, auth=auth, json=body)
                    self.assertEqual(response.status_code, 401)
        orders = self.client.get('/orders', auth=STAFF_AUTH).json()
        self.assertEqual(orders[0]['status'], 'queued')

    def test_codes_are_private_and_survive_restart(self):
        self.assertNotEqual(self.first['tracking_code'], self.second['tracking_code'])
        with TestClient(create_app(self.path)) as restarted:
            for placed in [self.first, self.second]:
                response = restarted.post('/track', json={'tracking_code': placed['tracking_code']})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['id'], placed['order_id'])
                self.assertNotIn('tracking_hash', response.json())
                self.assertNotIn('tracking_code', response.json())
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with closing(sqlite3.connect(self.path)) as connection:
            hashes = [row[0] for row in connection.execute('SELECT tracking_hash FROM orders')]
        self.assertTrue(all(len(value) == 64 for value in hashes))
        self.assertNotIn(self.first['tracking_code'], hashes)
        staff_orders = self.client.get('/orders', auth=STAFF_AUTH).json()
        self.assertTrue(all('tracking_hash' not in order and 'tracking_code' not in order for order in staff_orders))

    def test_wrong_codes_and_order_numbers_cannot_track(self):
        for code in ['1', '2', 'unknown', self.first['tracking_code'] + 'x']:
            self.assertEqual(self.client.post('/track', json={'tracking_code': code}).status_code, 404)
        self.assertEqual(self.client.post('/track', json={}).status_code, 422)
        self.assertEqual(self.client.post('/track', json={'tracking_code': 'x' * 129}).status_code, 422)

    def test_customer_code_does_not_grant_staff_access(self):
        self.assertEqual(self.client.get('/orders', auth=('test-staff', self.first['tracking_code'])).status_code, 401)

    def test_missing_or_short_credentials_fail_closed(self):
        for password in ['', 'short']:
            with patch.dict(os.environ, {'TAKEAWAY_STAFF_PASSWORD': password}):
                self.assertEqual(self.client.get('/orders', auth=STAFF_AUTH).status_code, 403)
                self.assertEqual(self.client.get('/staff/session', auth=STAFF_AUTH).status_code, 403)
        with patch.dict(os.environ, {'TAKEAWAY_STAFF_USERNAME': ''}):
            self.assertEqual(self.client.get('/orders', auth=STAFF_AUTH).status_code, 403)

    def test_authenticated_staff_and_customer_see_status_progress(self):
        self.assertEqual(self.client.get('/staff/session', auth=STAFF_AUTH).status_code, 200)
        self.assertEqual(self.client.patch('/orders/1/status', auth=STAFF_AUTH, json={'status': 'preparing'}).status_code, 200)
        self.assertEqual(self.client.post('/track', json={'tracking_code': self.first['tracking_code']}).json()['status'], 'preparing')
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE orders SET estimated_ready_at = '2000-01-01 00:00:00' WHERE id = 1")
        self.assertEqual(self.client.post('/track', json={'tracking_code': self.first['tracking_code']}).json()['status'], 'ready')
        self.assertEqual(self.client.patch('/orders/1/status', auth=STAFF_AUTH, json={'status': 'collected'}).status_code, 200)

    def test_pre_tracking_database_migrates_without_exposing_old_orders(self):
        old_path = self.path.with_name('old.db')
        with closing(sqlite3.connect(old_path)) as connection, connection:
            connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, total_pence INTEGER NOT NULL, status TEXT DEFAULT 'queued', created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            connection.execute('INSERT INTO orders (total_pence) VALUES (399)')
        with TestClient(create_app(old_path)) as client:
            self.assertEqual(len(client.get('/orders', auth=STAFF_AUTH).json()), 1)
            self.assertEqual(client.post('/track', json={'tracking_code': '1'}).status_code, 404)
            placed = client.post('/orders', json={'item_id': 1, 'quantity': 1}).json()
            self.assertEqual(client.post('/track', json={'tracking_code': placed['tracking_code']}).json()['id'], 2)

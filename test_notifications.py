"""Tests for email verification and order ready email notifications."""
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import create_app
from notifications import clear_sent_emails, get_sent_emails

PASSWORD = 'test-notification-password-123'


class EmailNotificationTests(unittest.TestCase):
    def setUp(self):
        clear_sent_emails()
        self.enterContext(patch.dict(os.environ, {
            'TAKEAWAY_ADMIN_USERNAME': 'owner',
            'TAKEAWAY_ADMIN_PASSWORD': PASSWORD,
        }))
        folder = self.enterContext(TemporaryDirectory())
        self.path = Path(folder) / 'notifications.db'
        self.client = self.enterContext(TestClient(create_app(self.path)))
        self.admin = self.login('owner')

    def login(self, username, password=PASSWORD):
        response = self.client.post('/auth/login', json={'username': username, 'password': password})
        self.assertEqual(response.status_code, 200, response.text)
        return {'Authorization': 'Bearer ' + response.json()['token']}

    def test_registration_verification_and_login_flow(self):
        # 1. Register with email
        reg_response = self.client.post('/auth/register', json={
            'username': 'emailuser',
            'email': 'user@example.com',
            'password': PASSWORD,
        })
        self.assertEqual(reg_response.status_code, 201, reg_response.text)
        data = reg_response.json()
        self.assertEqual(data['email'], 'user@example.com')
        self.assertFalse(data['email_verified'])
        self.assertIn('verification_token', data)
        token = data['verification_token']

        # Check that email was recorded in sent emails
        sent = get_sent_emails()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['to'], 'user@example.com')
        self.assertIn('Verify your BiteBox account email', sent[0]['subject'])
        self.assertIn(token, sent[0]['body'])

        # 2. Login before verification fails with 403
        login_fail = self.client.post('/auth/login', json={'username': 'emailuser', 'password': PASSWORD})
        self.assertEqual(login_fail.status_code, 403)
        self.assertIn('not verified', login_fail.json()['detail'])

        # 3. Verify email with token
        verify_resp = self.client.post('/auth/verify-email', json={'token': token})
        self.assertEqual(verify_resp.status_code, 200)
        self.assertTrue(verify_resp.json()['verified'])

        # Re-using token fails
        self.assertEqual(self.client.post('/auth/verify-email', json={'token': token}).status_code, 400)

        # 4. Login after verification with username succeeds
        login_user = self.login('emailuser')
        self.assertIsNotNone(login_user)

        # 5. Login with email also succeeds
        login_email = self.login('user@example.com')
        self.assertIsNotNone(login_email)

    def test_resend_verification_token(self):
        clear_sent_emails()
        self.client.post('/auth/register', json={
            'username': 'resenduser',
            'email': 'resend@example.com',
            'password': PASSWORD,
        })
        self.assertEqual(len(get_sent_emails()), 1)

        # Resend token
        resend_resp = self.client.post('/auth/resend-verification', json={'email': 'resend@example.com'})
        self.assertEqual(resend_resp.status_code, 200)
        self.assertTrue(resend_resp.json()['sent'])
        self.assertEqual(len(get_sent_emails()), 2)
        new_token = resend_resp.json()['token']

        # Verify with new token
        verify_resp = self.client.post('/auth/verify-email', json={'token': new_token})
        self.assertEqual(verify_resp.status_code, 200)

    def test_order_ready_email_notification_manual_status(self):
        clear_sent_emails()
        # Create staff account
        self.client.post('/admin/staff', headers=self.admin, json={'username': 'staff1', 'password': PASSWORD})
        staff = self.login('staff1')

        # Place order with email
        order = self.client.post('/checkout', json={
            'items': [{'item_id': 1, 'quantity': 1}],
            'email': 'customer@example.com',
        }).json()
        order_id = order['order_id']

        # Advance status to preparing then ready
        self.client.patch(f'/orders/{order_id}/status', headers=staff, json={'status': 'preparing'})

        clear_sent_emails()
        self.client.patch(f'/orders/{order_id}/status', headers=staff, json={'status': 'ready'})

        # Verify ready notification email sent
        sent = get_sent_emails()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['to'], 'customer@example.com')
        self.assertIn(f'Order #{order_id} is Ready', sent[0]['subject'])
        self.assertIn('Cheeseburger', sent[0]['body'])

    def test_order_ready_email_notification_automatic_timer(self):
        clear_sent_emails()
        # Place order with email
        order = self.client.post('/checkout', json={
            'items': [{'item_id': 2, 'quantity': 1}],
            'email': 'timer@example.com',
        }).json()
        order_id = order['order_id']

        self.client.post('/admin/staff', headers=self.admin, json={'username': 'staff2', 'password': PASSWORD})
        staff = self.login('staff2')

        self.client.patch(f'/orders/{order_id}/status', headers=staff, json={'status': 'preparing'})

        clear_sent_emails()

        # Simulate time passing by setting estimated_ready_at in the past
        from database import connect
        with connect(self.path) as connection, connection:
            connection.execute("UPDATE orders SET estimated_ready_at = '2000-01-01 00:00:00' WHERE id = ?", (order_id,))

        # Polling / checking tracking code or orders triggers _mark_elapsed_orders_ready
        track_resp = self.client.post('/track', json={'tracking_code': order['tracking_code']})
        self.assertEqual(track_resp.status_code, 200)
        self.assertEqual(track_resp.json()['status'], 'ready')

        # Verify automatic timer order ready email sent
        sent = get_sent_emails()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['to'], 'timer@example.com')
        self.assertIn(f'Order #{order_id} is Ready', sent[0]['subject'])


if __name__ == '__main__':
    unittest.main()

"""Account ownership, permissions and session lifecycle regression tests."""
import os
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import create_app
from database import connect, initialise_database

PASSWORD = 'Pass123!word_12345'
ADMIN_PASSCODE = 'AdminPass123!'


class AccountTests(unittest.TestCase):
    def test_invitation_permissions_single_use_and_private_storage(self):
        self.register('customer')
        customer = self.login('customer')
        for headers, status in [({}, 401), (customer, 403)]:
            self.assertEqual(self.client.post('/admin/invitations', headers=headers).status_code, status)
        invitation = self.client.post('/admin/invitations', headers=self.admin).json()
        self.assertNotIn('token', self.client.get('/admin/invitations', headers=self.admin).json()[0])
        with closing(connect(self.path)) as connection:
            stored = connection.execute('SELECT token_hash FROM admin_invitations').fetchone()[0]
        self.assertNotEqual(stored, invitation['token'])
        body = {
            'token': invitation['token'], 'username': 'newadmin', 'password': PASSWORD,
            'name': 'New', 'surname': 'Admin', 'email': 'newadmin@example.com',
            'phone_number': '+1234567890', 'admin_passcode': ADMIN_PASSCODE
        }
        response = self.client.post('/auth/accept-invitation', json=body)
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data['role'], 'admin')
        self.client.post('/auth/verify-email', json={'username_or_email': 'newadmin', 'code': data['verification_code']})
        self.assertEqual(self.client.get('/admin/users', headers=self.login('newadmin')).status_code, 200)
        body['username'] = 'anotheradmin'
        self.assertEqual(self.client.post('/auth/accept-invitation', json=body).status_code, 400)

    def test_expired_revoked_and_duplicate_username_invitations(self):
        for condition in ('expired', 'revoked'):
            invite = self.client.post('/admin/invitations', headers=self.admin).json()
            if condition == 'expired':
                with closing(connect(self.path)) as connection, connection:
                    connection.execute('UPDATE admin_invitations SET expires_at = 0 WHERE id = ?', (invite['id'],))
            else:
                self.assertEqual(self.client.delete(f"/admin/invitations/{invite['id']}", headers=self.admin).status_code, 200)
            self.assertEqual(self.client.post('/auth/accept-invitation', json={
                'token': invite['token'], 'username': 'newadmin', 'password': PASSWORD,
                'name': 'New', 'surname': 'Admin', 'email': 'newadmin@example.com',
                'phone_number': '+1234567890', 'admin_passcode': ADMIN_PASSCODE}).status_code, 400)
        invite = self.client.post('/admin/invitations', headers=self.admin).json()
        body = {
            'token': invite['token'], 'username': 'owner', 'password': PASSWORD,
            'name': 'New', 'surname': 'Admin', 'email': 'owner@example.com',
            'phone_number': '+1234567890', 'admin_passcode': ADMIN_PASSCODE
        }
        self.assertEqual(self.client.post('/auth/accept-invitation', json=body).status_code, 409)
        body['username'] = 'newadmin'
        body['email'] = 'newadmin@example.com'
        res = self.client.post('/auth/accept-invitation', json=body)
        self.assertEqual(res.status_code, 201)

    def test_concurrent_acceptance_creates_only_one_admin(self):
        from concurrent.futures import ThreadPoolExecutor
        invite = self.client.post('/admin/invitations', headers=self.admin).json()
        def accept(username):
            return self.client.post('/auth/accept-invitation', json={
                'token': invite['token'], 'username': username, 'password': PASSWORD,
                'name': 'New', 'surname': 'Admin', 'email': f'{username}@example.com',
                'phone_number': '+1234567890', 'admin_passcode': ADMIN_PASSCODE}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(accept, ['firstadmin', 'secondadmin']))
        self.assertEqual(sorted(results), [201, 400])

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            'TAKEAWAY_ADMIN_USERNAME': 'owner', 'TAKEAWAY_ADMIN_PASSWORD': PASSWORD,
            'TAKEAWAY_ADMIN_PASSCODE': ADMIN_PASSCODE,
        }))
        folder = self.enterContext(TemporaryDirectory())
        self.path = Path(folder) / 'accounts.db'
        self.client = self.enterContext(TestClient(create_app(self.path)))
        self.admin = self.login('owner')

    def login(self, username_or_email, password=PASSWORD):
        response = self.client.post('/auth/login', json={'username': username_or_email, 'password': password})
        self.assertEqual(response.status_code, 200, response.text)
        return {'Authorization': 'Bearer ' + response.json()['token']}

    def register(self, username, verify=True):
        response = self.client.post('/auth/register', json={
            'username': username, 'password': PASSWORD,
            'name': 'Test', 'surname': 'User',
            'email': f'{username}@example.com', 'phone_number': '+1234567890'
        })
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        if verify and 'verification_code' in data:
            self.client.post('/auth/verify-email', json={
                'username_or_email': username, 'code': data['verification_code']
            })
        return data

    def test_registration_normalisation_hashing_and_no_role_escalation(self):
        user = self.register('Alice')
        self.assertEqual(user['username'], 'alice')
        self.assertEqual(user['role'], 'customer')
        self.assertEqual(user['name'], 'Test')
        self.assertEqual(user['surname'], 'User')
        self.assertEqual(user['email'], 'alice@example.com')
        self.assertEqual(user['phone_number'], '+1234567890')
        self.assertNotIn('password_hash', user)
        self.assertEqual(self.client.post('/auth/register', json={
            'username': 'ALICE', 'password': PASSWORD,
            'name': 'Test', 'surname': 'User',
            'email': 'alice@example.com', 'phone_number': '+1234567890'
        }).status_code, 409)
        self.assertEqual(self.client.post('/auth/register', json={
            'username': 'hacker', 'password': PASSWORD, 'role': 'admin',
            'name': 'Test', 'surname': 'User',
            'email': 'hacker@example.com', 'phone_number': '+1234567890'
        }).status_code, 422)
        self.assertEqual(self.client.post('/auth/register', json={
            'username': 'short', 'password': '123',
            'name': 'Test', 'surname': 'User',
            'email': 'short@example.com', 'phone_number': '+1234567890'
        }).status_code, 422)
        with closing(connect(self.path)) as connection:
            stored = connection.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()[0]
        self.assertNotIn(PASSWORD, stored)
        self.assertNotEqual(stored, PASSWORD)
        self.assertEqual(self.client.get('/auth/me', headers=self.login('ALICE')).json()['id'], user['id'])
        # Also test login with email
        self.assertEqual(self.client.get('/auth/me', headers=self.login('alice@example.com')).json()['id'], user['id'])

    def test_order_history_is_owned_and_persistent(self):
        self.register('alice')
        self.register('bob')
        alice, bob = self.login('alice'), self.login('bob')
        self.client.post('/orders', headers=alice, json={'item_id': 1, 'quantity': 1})
        self.client.post('/checkout', headers=bob, json={'items': [{'item_id': 2, 'quantity': 1}]})
        self.client.post('/orders', json={'item_id': 3, 'quantity': 1})
        self.assertEqual([o['id'] for o in self.client.get('/me/orders', headers=alice).json()], [1])
        self.assertEqual([o['id'] for o in self.client.get('/me/orders', headers=bob).json()], [2])
        self.assertEqual(self.client.get('/me/orders').status_code, 401)
        self.assertEqual(self.client.post('/checkout', headers=alice, json={'items': [{'item_id': 1, 'quantity': 1}], 'customer_id': 3}).status_code, 422)
        with TestClient(create_app(self.path)) as restarted:
            self.assertEqual(len(restarted.get('/me/orders', headers=alice).json()), 1)

    def test_customers_cannot_access_staff_or_admin_controls(self):
        self.register('alice')
        alice = self.login('alice')
        for method, url, body in [
            ('GET', '/orders', None), ('GET', '/queue', None), ('GET', '/staff/session', None),
            ('PATCH', '/orders/1/status', {'status': 'preparing'}),
            ('GET', '/admin/users', None),
            ('POST', '/admin/staff', {'username': 'helper', 'password': PASSWORD, 'name': 'Help', 'surname': 'Er', 'email': 'helper@example.com', 'phone_number': '+1234567890'}),
            ('PATCH', '/admin/menu/1', {'stock': 999}),
            ('PATCH', '/admin/users/1', {'active': False}),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.request(method, url, headers=alice, json=body).status_code, 403)

    def test_admin_creates_staff_and_staff_has_only_kitchen_controls(self):
        response = self.client.post('/admin/staff', headers=self.admin, json={
            'username': 'helper', 'password': PASSWORD,
            'name': 'Help', 'surname': 'Er', 'email': 'helper@example.com', 'phone_number': '+1234567890'
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['role'], 'staff')
        self.client.post('/auth/verify-email', json={'username_or_email': 'helper', 'code': data['verification_code']})
        staff = self.login('helper')
        self.client.post('/orders', json={'item_id': 1, 'quantity': 1})
        self.assertEqual(self.client.get('/orders', headers=staff).status_code, 200)
        self.assertEqual(self.client.get('/queue', headers=staff).status_code, 200)
        self.assertEqual(self.client.patch('/orders/1/status', headers=staff, json={'status': 'preparing'}).status_code, 200)
        self.assertEqual(self.client.get('/admin/users', headers=staff).status_code, 403)
        self.assertEqual(self.client.patch('/admin/menu/1', headers=staff, json={'stock': 30}).status_code, 403)
        self.assertEqual(self.client.post('/admin/staff', headers=staff, json={'username': 'another', 'password': PASSWORD, 'name': 'A', 'surname': 'B', 'email': 'another@example.com', 'phone_number': '+1234567890'}).status_code, 403)
        self.assertEqual(self.client.patch('/admin/menu/1', headers=self.admin, json={'stock': 30}).status_code, 200)
        self.assertEqual(self.client.get('/menu').json()[0]['stock'], 30)
        self.assertEqual(self.client.patch('/admin/menu/1', headers=self.admin, json={'stock': -1}).status_code, 422)

    def test_disable_revokes_sessions_and_cannot_disable_admin(self):
        user = self.register('alice')
        alice = self.login('alice')
        url = f"/admin/users/{user['id']}"
        self.assertEqual(self.client.patch(url, headers=self.admin, json={'active': False}).status_code, 200)
        self.assertEqual(self.client.get('/auth/me', headers=alice).status_code, 401)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code, 401)
        self.client.patch(url, headers=self.admin, json={'active': True})
        self.assertEqual(self.client.get('/auth/me', headers=alice).status_code, 401)
        self.login('alice')
        self.assertEqual(self.client.patch('/admin/users/1', headers=self.admin, json={'active': False}).status_code, 409)

    def test_logout_expiry_and_invalid_tokens(self):
        self.register('alice')
        alice = self.login('alice')
        self.assertEqual(self.client.post('/auth/logout', headers=alice).status_code, 200)
        self.assertEqual(self.client.get('/auth/me', headers=alice).status_code, 401)
        alice = self.login('alice')
        with closing(connect(self.path)) as connection, connection:
            connection.execute('UPDATE sessions SET expires_at = 0')
        for headers in [alice, {'Authorization': 'Bearer invalid'}]:
            self.assertEqual(self.client.get('/auth/me', headers=headers).status_code, 401)
            self.assertEqual(self.client.post('/orders', headers=headers, json={'item_id': 1, 'quantity': 1}).status_code, 401)

    def test_password_change_revokes_all_sessions(self):
        self.register('alice')
        first, second = self.login('alice'), self.login('alice')
        new_pass = PASSWORD + 'New1!'
        self.assertEqual(self.client.post('/auth/password', headers=first, json={'current_password': 'wrong', 'new_password': new_pass}).status_code, 401)
        self.assertEqual(self.client.post('/auth/password', headers=first, json={'current_password': PASSWORD, 'new_password': new_pass}).status_code, 200)
        for headers in [first, second]:
            self.assertEqual(self.client.get('/auth/me', headers=headers).status_code, 401)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code, 401)
        self.login('alice', new_pass)

    def test_login_is_rate_limited(self):
        for _ in range(10):
            self.assertEqual(self.client.post('/auth/login', json={'username': 'unknown', 'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'unknown', 'password': 'wrong'}).status_code, 429)

    def test_bootstrap_does_not_overwrite_password_or_promote_customer(self):
        self.register('alice')
        with patch.dict(os.environ, {'TAKEAWAY_ADMIN_USERNAME': 'alice'}):
            with self.assertRaisesRegex(ValueError, 'non-admin'):
                initialise_database(self.path)
        with patch.dict(os.environ, {'TAKEAWAY_ADMIN_PASSWORD': PASSWORD + 'different'}):
            initialise_database(self.path)
        self.login('owner')
        with closing(connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT role FROM users WHERE username = 'alice'").fetchone()[0], 'customer')

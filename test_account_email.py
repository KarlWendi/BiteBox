"""Real API and website journeys with email delivery captured in memory."""
import os
import smtplib
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from api import create_app
from database import connect
import test_accounts
import test_account_ui
PASSWORD = test_accounts.PASSWORD
UI_PASSWORD = test_account_ui.PASSWORD


class EmailAccountTests(unittest.TestCase):
    login = test_accounts.AccountTests.login

    def setUp(self):
        test_accounts.AccountTests.setUp(self)
        self.enterContext(patch.dict(os.environ, {
            'TAKEAWAY_EMAIL_ENABLED': '1', 'SMTP_HOST': 'smtp.example.test',
            'SMTP_FROM': 'bitebox@example.test', 'TAKEAWAY_WEBSITE_URL': 'https://bitebox.example.test',
        }))
        self.mail = self.enterContext(patch('account_email.send_email'))

    def register(self, username='alice', email='alice@example.test'):
        result = self.client.post('/auth/register', json={'username': username, 'email': email, 'password': PASSWORD})
        self.assertEqual(result.status_code, 201, result.text)
        return self.mail.call_args.args[2]

    def verify(self, token):
        return self.client.post('/auth/verify-email', json={'token': token})

    def test_verified_email_login_and_restart_persistence(self):
        token = self.register(email='Alice@Example.Test')
        self.assertEqual(self.client.post('/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code, 403)
        self.assertEqual(self.verify(token).status_code, 200)
        self.assertEqual(self.verify(token).status_code, 400)
        headers = self.login('ALICE@example.test')
        self.assertEqual(self.client.get('/auth/me', headers=headers).json()['email'], 'alice@example.test')
        with TestClient(create_app(self.path)) as restarted:
            self.assertEqual(restarted.post('/auth/login', json={'username': 'alice@example.test', 'password': PASSWORD}).status_code, 200)

    def test_reset_is_single_use_and_revokes_all_sessions(self):
        self.verify(self.register())
        first, second = self.login('alice'), self.login('alice@example.test')
        self.client.post('/auth/forgot-password', json={'email': 'alice@example.test'})
        token = self.mail.call_args.args[2]
        body = {'token': token, 'password': PASSWORD + '-new'}
        self.assertEqual(self.client.post('/auth/reset-password', json=body).status_code, 200)
        self.assertEqual(self.client.post('/auth/reset-password', json=body).status_code, 400)
        for headers in (first, second):
            self.assertEqual(self.client.get('/auth/me', headers=headers).status_code, 401)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code, 401)
        self.login('alice@example.test', PASSWORD + '-new')

    def test_required_email_duplicate_address_and_no_role_escalation(self):
        for email in (None, '', 'not-an-email', 'alice@example.test\nBcc: someone@example.test'):
            result = self.client.post('/auth/register', json={'username': 'alice', 'password': PASSWORD, 'email': email})
            self.assertEqual(result.status_code, 422)
        self.register()
        result = self.client.post('/auth/register', json={'username': 'bob', 'password': PASSWORD, 'email': 'ALICE@example.test'})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.post('/auth/register', json={'username': 'bob', 'password': PASSWORD, 'email': 'bob@example.test', 'role': 'admin'}).status_code, 422)

    def test_expired_wrong_kind_and_disabled_account_links(self):
        token = self.register()
        self.assertEqual(self.client.post('/auth/reset-password', json={'token': token, 'password': PASSWORD}).status_code, 400)
        with closing(connect(self.path)) as db, db:
            db.execute('UPDATE account_links SET expires_at = 0')
        self.assertEqual(self.verify(token).status_code, 400)
        self.client.post('/auth/resend-verification', json={'email': 'alice@example.test'})
        token = self.mail.call_args.args[2]
        with closing(connect(self.path)) as db, db:
            db.execute("UPDATE users SET active = 0 WHERE username = 'alice'")
        self.assertEqual(self.verify(token).status_code, 400)

    def test_failed_delivery_can_be_recovered_and_tokens_are_hashed(self):
        self.mail.side_effect = HTTPException(503, 'Email delivery failed.')
        result = self.client.post('/auth/register', json={'username': 'alice', 'email': 'alice@example.test', 'password': PASSWORD})
        self.assertEqual(result.status_code, 503)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM account_links').fetchone()[0], 0)
        self.mail.side_effect = None
        self.assertEqual(self.client.post('/auth/resend-verification', json={'email': 'alice@example.test'}).status_code, 200)
        token = self.mail.call_args.args[2]
        with closing(connect(self.path)) as db:
            self.assertNotEqual(db.execute('SELECT token_hash FROM account_links').fetchone()[0], token)
        self.assertEqual(self.verify(token).status_code, 200)

    def test_recovery_responses_do_not_reveal_accounts_and_are_limited(self):
        self.verify(self.register())
        known = self.client.post('/auth/forgot-password', json={'email': 'alice@example.test'})
        unknown = self.client.post('/auth/forgot-password', json={'email': 'unknown@example.test'})
        self.assertEqual(known.json(), unknown.json())
        for _ in range(4):
            self.client.post('/auth/forgot-password', json={'email': 'unknown@example.test'})
        self.assertEqual(self.client.post('/auth/forgot-password', json={'email': 'unknown@example.test'}).status_code, 429)

    def test_admin_invitation_requires_email_verification(self):
        invitation = self.client.post('/admin/invitations', headers=self.admin).json()
        body = {'token': invitation['token'], 'username': 'newadmin', 'email': 'admin@example.test', 'password': PASSWORD}
        self.assertEqual(self.client.post('/auth/accept-invitation', json=body).status_code, 201)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'newadmin', 'password': PASSWORD}).status_code, 403)
        self.verify(self.mail.call_args.args[2])
        self.assertEqual(self.client.get('/admin/users', headers=self.login('admin@example.test')).status_code, 200)

    def test_legacy_admin_can_attach_recovery_address_without_role_change(self):
        body = {'email': 'owner@example.test', 'password': 'wrong-password'}
        self.assertEqual(self.client.post('/auth/email', headers=self.admin, json=body).status_code, 401)
        body['password'] = PASSWORD
        self.assertEqual(self.client.post('/auth/email', headers=self.admin, json=body).status_code, 200)
        self.verify(self.mail.call_args.args[2])
        self.assertEqual(self.client.get('/auth/me', headers=self.login('owner@example.test')).json()['role'], 'admin')

    def test_old_database_migrates_without_replacing_accounts(self):
        from accounts import password_hash
        legacy_path = self.path.with_name('legacy.db')
        with closing(sqlite3.connect(legacy_path)) as db, db:
            db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)')
            db.execute('INSERT INTO users VALUES (42, ?, ?, ?, 1)', ('legacycustomer', password_hash(PASSWORD), 'customer'))
        with TestClient(create_app(legacy_path)) as migrated:
            response = migrated.post('/auth/login', json={'username': 'legacycustomer', 'password': PASSWORD})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['user']['id'], 42)
            self.assertIsNone(response.json()['user']['email'])
            self.assertEqual(response.json()['user']['role'], 'customer')


class EmailWebsiteTests(unittest.TestCase):
    fill = test_account_ui.AccountWebsiteTests.fill
    click = test_account_ui.AccountWebsiteTests.click
    open_account = test_account_ui.AccountWebsiteTests.open_account
    open_registration = test_account_ui.AccountWebsiteTests.open_registration
    login = test_account_ui.AccountWebsiteTests.login

    def setUp(self):
        test_account_ui.AccountWebsiteTests.setUp(self)
        self.enterContext(patch.dict(os.environ, {'TAKEAWAY_EMAIL_ENABLED': '1', 'SMTP_HOST': 'smtp.example.test',
            'SMTP_FROM': 'bitebox@example.test', 'TAKEAWAY_WEBSITE_URL': 'https://bitebox.example.test'}))
        self.mail = self.enterContext(patch('account_email.send_email'))

    def test_customer_register_verify_login_reset_and_return_to_order(self):
        self.click('Add to trolley')
        self.open_registration()
        self.fill('Choose a username', 'emailcustomer')
        self.fill('Email address', 'customer@example.test')
        self.fill('Choose a password', UI_PASSWORD)
        self.fill('Confirm password', UI_PASSWORD)
        self.click('Create account')
        self.assertIn('verify your address', self.app.success[0].value)
        self.app.query_params['verify_account'] = self.mail.call_args.args[2]
        self.app.run()
        self.assertNotIn('verify_account', self.app.query_params)
        self.click('Verify email')
        self.login('customer@example.test')
        self.click('← Back to your order')
        self.assertEqual(self.app.session_state['trolley'], {1: 1})
        self.click('Checkout')
        self.open_account()
        self.click('Sign out')
        self.fill('Your email address', 'customer@example.test')
        self.click('Send password reset email')
        self.app.query_params['reset_account'] = self.mail.call_args.args[2]
        self.app.run()
        self.fill('New password', UI_PASSWORD + '-new')
        self.fill('Confirm new password', UI_PASSWORD + '-new')
        self.click('Reset password')
        self.login('customer@example.test', UI_PASSWORD + '-new')
        self.click('← Back to your order')
        self.assertEqual(self.app.dataframe[0].value['Order'].tolist(), ['#1'])


class SMTPTests(unittest.TestCase):
    def test_email_uses_configured_public_url_and_tls(self):
        from account_email import send_email
        with patch.dict(os.environ, {'SMTP_HOST': 'smtp.example.test', 'SMTP_FROM': 'box@example.test',
                                    'SMTP_PORT': '465', 'TAKEAWAY_WEBSITE_URL': 'https://bitebox.example.test'}), \
                patch('account_email.smtplib.SMTP_SSL') as smtp:
            send_email('customer@example.test', 'verify', 'test-token')
            message = smtp.return_value.send_message.call_args.args[0]
            self.assertIn('https://bitebox.example.test/?verify_account=test-token', message.get_content())
            self.assertIn('context', smtp.call_args.kwargs)

    def test_delivery_failure_is_actionable(self):
        from account_email import send_email
        with patch.dict(os.environ, {'SMTP_HOST': 'smtp.example.test', 'SMTP_FROM': 'box@example.test',
                                    'SMTP_PORT': '465', 'TAKEAWAY_WEBSITE_URL': 'https://bitebox.example.test'}), \
                patch('account_email.smtplib.SMTP_SSL', side_effect=smtplib.SMTPException('Unavailable')):
            with self.assertRaises(HTTPException) as raised:
                send_email('customer@example.test', 'reset', 'test-token')
            self.assertEqual(raised.exception.status_code, 503)

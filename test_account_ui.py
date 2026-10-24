"""Exercise account controls through the rendered website and real API routes."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from api import create_app
from web_client import APIError

from contextlib import closing
from database import connect

PASSWORD = 'Pass123!word_12345'
ADMIN_PASSCODE = 'AdminPass123!'


class AccountWebsiteTests(unittest.TestCase):
    def test_admin_invitation_registration_and_login(self):
        self.login('owner')
        self.click('Create admin invitation')
        invitation = self.app.session_state['created_invitation']
        self.assertTrue(any('admin_invite=' in code.value for code in self.app.code))
        self.click('Sign out')
        self.app.query_params['admin_invite'] = invitation['token']
        self.app.run()
        self.assertNotIn('admin_invite', self.app.query_params)
        self.fill('First name', 'New')
        self.fill('Surname', 'Admin')
        self.fill('Email address', 'newadmin@example.com')
        self.fill('Phone number', '+1234567890')
        self.fill('Admin username', 'invitedadmin')
        self.fill('Admin passcode', ADMIN_PASSCODE)
        self.fill('Admin password', PASSWORD)
        self.fill('Confirm admin password', PASSWORD)
        self.click('Create administrator account')
        self.click('Next (Send verification code)')
        with closing(connect(self.client.app.state.database_path)) as connection:
            code = connection.execute('SELECT code FROM email_verifications ORDER BY id DESC LIMIT 1').fetchone()[0]
        self.fill('Verification code', code)
        self.click('Verify Email')
        self.assertTrue(any('verified' in notice.value.lower() for notice in self.app.success))
        self.login('invitedadmin')
        self.assertTrue(any(b.label == 'Create admin invitation' for b in self.app.button))

    def test_signed_in_invitation_keeps_link_after_logout(self):
        self.login('owner')
        self.click('Create admin invitation')
        token = self.app.session_state['created_invitation']['token']
        self.app.query_params['admin_invite'] = token
        self.app.run()
        self.click('Sign out and continue with invitation')
        self.assertEqual(self.app.session_state['admin_invite_token'], token)
        self.fill('First name', 'Second')
        self.fill('Surname', 'Admin')
        self.fill('Email address', 'secondadmin@example.com')
        self.fill('Phone number', '+1234567890')
        self.fill('Admin username', 'secondadmin')
        self.fill('Admin passcode', ADMIN_PASSCODE)
        self.fill('Admin password', PASSWORD)
        self.fill('Confirm admin password', PASSWORD)
        self.click('Create administrator account')
        self.click('Next (Send verification code)')
        with closing(connect(self.client.app.state.database_path)) as connection:
            code = connection.execute('SELECT code FROM email_verifications ORDER BY id DESC LIMIT 1').fetchone()[0]
        self.fill('Verification code', code)
        self.click('Verify Email')
        self.login('secondadmin')
        self.assertTrue(any(b.label == 'Create admin invitation' for b in self.app.button))

    def test_registration_errors_preserve_details_for_correction(self):
        self.open_registration()
        self.fill('First name', 'Test')
        self.fill('Surname', 'User')
        self.fill('Email address', 'bademail')
        self.fill('Phone number', '+1234567890')
        self.fill('Choose a username', 'bad name')
        self.fill('Choose a password', PASSWORD)
        self.fill('Confirm password', PASSWORD)
        self.click('Create account')
        self.assertIn('username', self.app.error[0].value.lower())
        self.assertEqual(next(f.value for f in self.app.text_input if f.label == 'Choose a username'), 'bad name')
        self.fill('Choose a username', 'validuser')
        self.click('Create account')
        self.assertIn('email', self.app.error[0].value.lower())
        self.fill('Email address', 'valid@example.com')
        self.click('Create account')
        self.click('Next (Send verification code)')
        with closing(connect(self.client.app.state.database_path)) as connection:
            code = connection.execute('SELECT code FROM email_verifications ORDER BY id DESC LIMIT 1').fetchone()[0]
        self.fill('Verification code', code)
        self.click('Verify Email')
        self.login('validuser')
        self.assertTrue(any(b.label == 'Sign out' for b in self.app.button))

    def test_invitation_error_can_be_corrected_and_used_link_disappears(self):
        self.login('owner')
        self.click('Create admin invitation')
        token = self.app.session_state['created_invitation']['token']
        self.app.query_params['admin_invite'] = token
        self.app.run()
        self.click('Sign out and continue with invitation')
        self.fill('First name', 'Owner')
        self.fill('Surname', 'Admin')
        self.fill('Email address', 'owner@example.com')
        self.fill('Phone number', '+1234567890')
        self.fill('Admin username', 'owner')
        self.fill('Admin passcode', ADMIN_PASSCODE)
        self.fill('Admin password', PASSWORD)
        self.fill('Confirm admin password', PASSWORD)
        self.click('Create administrator account')
        self.assertIn('unavailable', self.app.error[0].value)
        self.fill('Admin username', 'correctedadmin')
        self.fill('Email address', 'correctedadmin@example.com')
        self.click('Create administrator account')
        self.click('Next (Send verification code)')
        with closing(connect(self.client.app.state.database_path)) as connection:
            code = connection.execute('SELECT code FROM email_verifications ORDER BY id DESC LIMIT 1').fetchone()[0]
        self.fill('Verification code', code)
        self.click('Verify Email')
        self.login('correctedadmin')
        self.click('Create admin invitation')
        invitation = self.app.session_state['created_invitation']
        self.client.post('/auth/accept-invitation', json={
            'token': invitation['token'], 'username': 'anotheradmin', 'password': PASSWORD,
            'name': 'A', 'surname': 'B', 'email': 'another@example.com',
            'phone_number': '+1234567890', 'admin_passcode': ADMIN_PASSCODE})
        self.app.run()
        self.assertFalse(any('admin_invite=' in code.value for code in self.app.code))

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            'TAKEAWAY_ADMIN_USERNAME': 'owner',
            'TAKEAWAY_ADMIN_PASSWORD': PASSWORD,
            'TAKEAWAY_ADMIN_PASSCODE': ADMIN_PASSCODE,
        }))
        folder = self.enterContext(TemporaryDirectory())
        self.client = self.enterContext(TestClient(create_app(Path(folder) / 'test.db')))

        def request(method, path, **kwargs):
            response = self.client.request(method, path, **kwargs)
            if response.is_error:
                raise APIError(response.json()['detail'])
            return response.json()

        self.enterContext(patch('web_client.request_api', side_effect=request))
        self.app = AppTest.from_file(str(Path(__file__).with_name('website.py')), default_timeout=20).run()

    def fill(self, label, value):
        next(field for field in self.app.text_input if field.label == label).set_value(value)

    def click(self, label):
        next(button for button in self.app.button if button.label == label).click().run()
        self.assertFalse(self.app.exception)

    def open_account(self):
        if not ('account_page' in self.app.session_state and self.app.session_state['account_page']):
            self.app.button(key='open_account').click().run()

    def login(self, username, password=PASSWORD):
        self.open_account()
        self.fill('Account username or email', username)
        self.fill('Account password', password)
        self.click('Sign in')

    def open_registration(self):
        self.open_account()
        if self.app.session_state['account_page'] != 'register':
            self.click("Don't have an account? Create a customer account")

    def register(self, username):
        self.open_registration()
        self.fill('Choose a username', username)
        self.fill('Email address', f'{username}@example.com')
        self.fill('First name', 'Test')
        self.fill('Surname', 'User')
        self.fill('Phone number', '+1234567890')
        self.fill('Choose a password', PASSWORD)
        self.fill('Confirm password', PASSWORD)
        self.click('Create account')
        self.click('Next (Send verification code)')
        with closing(connect(self.client.app.state.database_path)) as connection:
            code = connection.execute('SELECT code FROM email_verifications ORDER BY id DESC LIMIT 1').fetchone()[0]
        self.fill('Verification code', code)
        self.click('Verify Email')

    def test_customer_registration_checkout_history_and_logout(self):
        self.register('alice')
        self.login('alice')
        self.assertFalse(any(button.label == 'Create staff account' for button in self.app.button))
        self.click('← Back to your order')
        self.click('Add to trolley')
        self.click('Checkout')
        self.assertEqual(self.app.dataframe[0].value['Order'].tolist(), ['#1'])
        self.assertFalse(any('enter your private tracking code' in info.value for info in self.app.info))
        self.open_account()
        self.click('Sign out')
        self.assertEqual(len(self.app.dataframe), 0)
        self.register('bob')
        self.login('bob')
        self.assertEqual(len(self.app.dataframe), 0)
        self.open_account()
        self.click('Sign out')
        self.login('alice')
        self.click('← Back to your order')
        self.assertEqual(self.app.dataframe[0].value['Order'].tolist(), ['#1'])

    def test_admin_stock_staff_creation_and_access_control(self):
        self.login('owner')
        stock = next(field for field in self.app.number_input if field.label == 'New available stock')
        self.assertEqual(stock.value, 20)
        next(field for field in self.app.selectbox if field.label == 'Product to update').select(2).run()
        stock = next(field for field in self.app.number_input if field.label == 'New available stock')
        self.assertEqual(stock.value, 30)
        stock.set_value(45)
        self.click('Update stock')
        self.assertEqual(self.client.get('/menu').json()[1]['stock'], 45)
        self.fill('First name', 'Help')
        self.fill('Surname', 'Er')
        self.fill('Email address', 'helper@example.com')
        self.fill('Phone number', '+1234567890')
        self.fill('New staff username', 'helper')
        self.fill('Temporary staff password', PASSWORD)
        self.fill('Confirm staff password', PASSWORD)
        self.click('Create staff account')
        users = self.client.get('/admin/users', headers={'Authorization': 'Bearer ' + self.app.session_state['account_session']['token']}).json()
        helper_user = next(u for u in users if u['username'] == 'helper')
        with closing(connect(self.client.app.state.database_path)) as connection:
            vcode = connection.execute('SELECT code FROM email_verifications WHERE user_id = ?', (helper_user['id'],)).fetchone()[0]
        self.client.post('/auth/verify-email', json={'username_or_email': 'helper', 'code': vcode})
        self.click('Disable helper')
        self.assertEqual(self.client.post('/auth/login', json={'username': 'helper', 'password': PASSWORD}).status_code, 401)
        self.click('Enable helper')
        self.client.post('/orders', json={'item_id': 1, 'quantity': 1})
        self.open_account()
        self.click('Sign out')
        self.login('helper')
        self.assertFalse(any(button.label == 'Create staff account' for button in self.app.button))
        self.click('← Back to your order')
        self.click('Kitchen controls')
        self.click('Order #1: mark as preparing')

    def test_registration_has_its_own_page(self):
        self.open_account()
        self.assertFalse(any(f.label == 'Choose a username' for f in self.app.text_input))
        self.open_registration()
        self.assertTrue(any(f.label == 'Choose a username' for f in self.app.text_input))
        self.assertFalse(any(f.label == 'Account username or email' for f in self.app.text_input))
        self.click('Already have an account? Sign in')
        self.assertTrue(any(f.label == 'Account username or email' for f in self.app.text_input))
        self.assertFalse(any(f.label == 'Choose a username' for f in self.app.text_input))

    def test_account_navigation_preserves_trolley(self):
        self.click('Add to trolley')
        self.assertEqual(self.app.session_state['trolley'], {1: 1})
        self.register('alice')
        self.assertFalse(any(b.label == 'Checkout' for b in self.app.button))
        self.login('alice')
        self.click('← Back to your order')
        self.assertEqual(self.app.session_state['trolley'], {1: 1})
        self.click('Checkout')
        self.assertEqual(self.app.dataframe[0].value['Order'].tolist(), ['#1'])

    def test_password_validation_and_change(self):
        self.open_registration()
        self.fill('First name', 'Alice')
        self.fill('Surname', 'User')
        self.fill('Email address', 'alice@example.com')
        self.fill('Phone number', '+1234567890')
        self.fill('Choose a username', 'alice')
        self.fill('Choose a password', 'short')
        self.fill('Confirm password', 'short')
        self.click('Create account')
        self.assertEqual(self.app.error[0].value, 'Use a password between 8 and 128 characters.')
        self.register('alice')
        self.login('alice')
        old_token = self.app.session_state['account_session']['token']
        new_pass = PASSWORD + 'New1!'
        self.fill('Current password', PASSWORD)
        self.fill('New password', new_pass)
        self.fill('Confirm new password', new_pass)
        self.click('Update password')
        self.assertEqual(self.client.get('/auth/me', headers={'Authorization': 'Bearer ' + old_token}).status_code, 401)
        self.assertTrue(any(button.label == 'Sign in' for button in self.app.button))
        self.login('alice', new_pass)
        self.assertTrue(any(button.label == 'Sign out' for button in self.app.button))


if __name__ == '__main__':
    unittest.main()

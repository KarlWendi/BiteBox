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

PASSWORD = 'account-ui-test-password'


class AccountWebsiteTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            'TAKEAWAY_ADMIN_USERNAME': 'owner',
            'TAKEAWAY_ADMIN_PASSWORD': PASSWORD,
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
        self.fill('Account username', username)
        self.fill('Account password', password)
        self.click('Sign in')

    def open_registration(self):
        self.open_account()
        if self.app.session_state['account_page'] != 'register':
            self.click("Don't have an account? Create a customer account")

    def register(self, username):
        self.open_registration()
        self.fill('Choose a username', username)
        self.fill('Choose a password', PASSWORD)
        self.fill('Confirm password', PASSWORD)
        self.click('Create account')

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
        self.fill('New staff username', 'helper')
        self.fill('Temporary staff password', PASSWORD)
        self.click('Create staff account')
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
        self.assertFalse(any(f.label == 'Account username' for f in self.app.text_input))
        self.click('Already have an account? Sign in')
        self.assertTrue(any(f.label == 'Account username' for f in self.app.text_input))
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
        self.fill('Choose a username', 'alice')
        self.fill('Choose a password', 'short')
        self.fill('Confirm password', 'short')
        self.click('Create account')
        self.assertEqual(self.app.error[0].value, 'Use a password between 12 and 128 characters.')
        self.register('alice')
        self.login('alice')
        old_token = self.app.session_state['account_session']['token']
        self.fill('Current password', PASSWORD)
        self.fill('New password', PASSWORD + '-new')
        self.fill('Confirm new password', PASSWORD + '-new')
        self.click('Update password')
        self.assertEqual(self.client.get('/auth/me', headers={'Authorization': 'Bearer ' + old_token}).status_code, 401)
        self.assertTrue(any(button.label == 'Sign in' for button in self.app.button))
        self.login('alice', PASSWORD + '-new')
        self.assertTrue(any(button.label == 'Sign out' for button in self.app.button))


if __name__ == '__main__':
    unittest.main()

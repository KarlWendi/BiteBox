import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest
from api import create_app
from web_client import APIError
from test_support import STAFF_AUTH, configure_staff

class WebsiteTests(unittest.TestCase):
    def setUp(self):
        configure_staff(self)
        self.directory = TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.directory.name) / 'test.db'))
        self.client.__enter__()
        self.client.auth = STAFF_AUTH
        def request(method, path, **kwargs):
            kwargs.setdefault('auth', None)
            response = self.client.request(method, path, **kwargs)
            if response.is_error:
                raise APIError(response.json()['detail'])
            return response.json()
        self.mock = patch('web_client.request_api', side_effect=request)
        self.request_mock = self.mock.start()
        self.app = AppTest.from_file(str(Path(__file__).with_name('website.py')), default_timeout=20).run()
    def login(self):
        next(field for field in self.app.text_input if field.label == 'Staff username').set_value(STAFF_AUTH[0])
        next(field for field in self.app.text_input if field.label == 'Staff password').set_value(STAFF_AUTH[1])
        next(button for button in self.app.button if button.label == 'Log in').click().run()
        self.assertFalse(self.app.exception)
    def tearDown(self):
        self.mock.stop()
        self.client.__exit__(None, None, None)
        self.directory.cleanup()
    def test_submit_refresh_and_station_changes(self):
        self.assertFalse(self.app.exception)
        self.app.number_input[0].set_value(2)
        self.app.button[1].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.client.get('/menu').json()[0]['stock'], 20)

        checkout_button = next(
            button for button in self.app.button
            if button.label == 'Checkout'
        )
        checkout_button.click().run()

        self.assertIn('£7.98', self.app.success[0].value)
        self.assertEqual(self.client.get('/menu').json()[0]['stock'], 18)
        self.app.button[0].click().run()
        self.login()
        self.app.slider[0].set_value(3).run()
        self.assertEqual(len(self.client.get('/orders').json()), 1)
        self.assertEqual(self.client.get('/menu').json()[0]['stock'], 18)
    def test_insufficient_stock_does_not_create_order(self):
        self.app.number_input[0].set_value(21)
        self.app.button[1].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(
            self.app.error[0].value,
            'Only 20 × Burger are currently available.',
        )
        self.assertEqual(self.client.get('/orders').json(), [])
        self.assertEqual(self.client.get('/menu').json()[0]['stock'], 20)

    def test_staff_can_advance_order_status(self):
        self.app.button[1].click().run()
        checkout_button = next(
            button for button in self.app.button
            if button.label == 'Checkout'
        )
        checkout_button.click().run()
        self.assertFalse(self.app.exception)

        self.login()
        status_button = next(
            button for button in self.app.button
            if button.label == 'Order #1: mark as preparing'
        )
        status_button.click().run()

        self.assertFalse(self.app.exception)
        self.assertEqual(self.client.get('/orders').json()[0]['status'], 'preparing')
        self.assertIn('Order #1 is now preparing.', self.app.success[0].value)
        self.assertEqual(self.app.dataframe[0].value.iloc[0]['Collection'], 'Ready in 3 minutes')

    def test_collection_labels_render_for_order_states(self):
        self.login()
        orders = [
            dict(id=index, name='Fries', quantity=1, total_pence=199,
                 status=status, estimated_ready_at=estimate)
            for index, (status, estimate) in enumerate([
                ('queued', None),
                ('preparing', '2026-09-30 12:02:00'),
                ('ready', '2026-09-30 11:59:00'),
                ('collected', '2026-09-30 11:59:00'),
            ], start=1)
        ]
        from datetime import datetime, timezone
        original_request = self.request_mock.side_effect
        def request(method, path, **kwargs):
            return orders if path == '/orders' else original_request(method, path, **kwargs)
        with patch('web_client.request_api', side_effect=request), patch('order_display.datetime') as clock:
            clock.fromisoformat.side_effect = datetime.fromisoformat
            clock.now.return_value = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
            self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.dataframe[0].value['Collection'].tolist(),
                         ['Waiting to start', 'Ready in 2 minutes', 'Ready now', 'Collected'])

    def test_customer_can_checkout_multiple_products(self):
        self.app.button[1].click().run()
        self.app.selectbox[0].select(2).run()
        self.app.number_input[0].set_value(2)
        add_button = next(
            button for button in self.app.button
            if button.label == 'Add to trolley'
        )
        add_button.click().run()

        checkout_button = next(
            button for button in self.app.button
            if button.label == 'Checkout'
        )
        checkout_button.click().run()

        order = self.client.get('/orders').json()[0]
        self.assertEqual(len(order['items']), 2)
        self.assertEqual(order['total_pence'], 797)
        self.assertEqual(self.client.get('/menu').json()[0]['stock'], 19)
        self.assertEqual(self.client.get('/menu').json()[1]['stock'], 28)

    def test_unavailable_service_displays_help(self):
        with patch('web_client.request_api', side_effect=APIError('Service unavailable')):
            app = AppTest.from_file(str(Path(__file__).with_name('website.py'))).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.error[0].value, 'Service unavailable')

    def test_customers_only_see_their_own_orders_and_can_recover(self):
        self.client.post('/orders', json={'item_id': 2, 'quantity': 1})
        self.app.run()
        self.assertEqual(len(self.app.dataframe), 0)
        self.assertEqual(len(self.app.slider), 0)
        self.assertFalse(any('mark as' in button.label for button in self.app.button))
        self.app.button[1].click().run()
        next(button for button in self.app.button if button.label == 'Checkout').click().run()
        self.assertEqual(self.app.dataframe[0].value['Order'].tolist(), ['#2'])
        code = next(iter(self.app.session_state['tracking_codes']))
        fresh = AppTest.from_file(str(Path(__file__).with_name('website.py'))).run()
        self.assertEqual(len(fresh.dataframe), 0)
        next(field for field in fresh.text_input if field.label == 'Private tracking code').set_value(code)
        next(button for button in fresh.button if button.label == 'Track order').click().run()
        self.assertFalse(fresh.exception)
        self.assertEqual(fresh.dataframe[0].value['Order'].tolist(), ['#2'])
        next(button for button in fresh.button if button.label == 'Forget order #2').click().run()
        self.assertEqual(len(fresh.dataframe), 0)

    def test_staff_login_failure_logout_and_expiry(self):
        self.client.post('/orders', json={'item_id': 1, 'quantity': 1})
        next(field for field in self.app.text_input if field.label == 'Staff username').set_value(STAFF_AUTH[0])
        next(field for field in self.app.text_input if field.label == 'Staff password').set_value('wrong')
        next(button for button in self.app.button if button.label == 'Log in').click().run()
        self.assertEqual(len(self.app.dataframe), 0)
        self.assertTrue(self.app.error)
        self.login()
        self.assertTrue(any('mark as preparing' in button.label for button in self.app.button))
        next(button for button in self.app.button if button.label == 'Log out').click().run()
        self.assertEqual(len(self.app.dataframe), 0)
        self.assertEqual(len(self.app.slider), 0)
        self.login()
        self.app.session_state['staff_expires'] = 0
        self.app.run()
        self.assertEqual(len(self.app.dataframe), 0)
        self.assertTrue(any(button.label == 'Log in' for button in self.app.button))

if __name__ == '__main__':
    unittest.main()

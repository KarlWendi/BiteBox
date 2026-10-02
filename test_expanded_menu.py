"""Verify the expanded catalogue works through stock and queue operations."""
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from api import create_app
from test_support import STAFF_AUTH, configure_staff
from database import initialise_database, get_menu, place_order
from menu import MENU
from kitchen import PREP_MINUTES

class ExpandedMenuTests(unittest.TestCase):
    def test_replacement_preserves_receipts_and_retires_duplicate(self):
        from database import connect, get_orders, ItemNotFoundError
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'migration.db'
            initialise_database(path)
            with closing(connect(path)) as connection, connection:
                connection.execute("UPDATE products SET name = 'Burger' WHERE id = 1")
                connection.execute("INSERT INTO products VALUES (4, 'Cheeseburger', 449, 20)")
            old = place_order(1, 1, path)
            with closing(connect(path)) as connection, connection:
                connection.execute('UPDATE order_items SET product_name = NULL')
            initialise_database(path)
            initialise_database(path)
            catalogue = get_menu(path)
            self.assertEqual(len(catalogue), 12)
            self.assertEqual(sum(item['name'] == 'Cheeseburger' for item in catalogue), 1)
            self.assertEqual(get_orders(path)[0]['items'][0]['name'], 'Burger')
            self.assertEqual(get_orders(path)[0]['total_pence'], old['total_pence'])
            self.assertEqual(catalogue[0]['stock'], 19)
            with self.assertRaises(ItemNotFoundError):
                place_order(4, 1, path)
            replacement = place_order(13, 1, path)
            self.assertEqual(replacement['name'], 'Mozzarella Sticks')
            self.assertEqual(replacement['total_pence'], 499)

    def test_new_items_can_be_ordered_and_scheduled(self):
        configure_staff(self)
        with TemporaryDirectory() as folder, TestClient(create_app(Path(folder) / 'menu.db')) as client:
            client.auth = STAFF_AUTH
            catalogue = client.get('/menu').json()
            self.assertEqual(len(catalogue), 12)
            for item in catalogue[3:]:
                with self.subTest(food=item['name']):
                    response = client.post('/orders', json={'item_id': item['id'], 'quantity': 2})
                    self.assertEqual(response.status_code, 201)
                    self.assertEqual(response.json()['total_pence'], item['price_pence'] * 2)
                    updated = next(row for row in client.get('/menu').json() if row['id'] == item['id'])
                    self.assertEqual(updated['stock'], item['stock'] - 2)
            queue = client.get('/queue').json()
            self.assertEqual(queue['order_count'], 9)
            self.assertEqual([row['prep_minutes'] for row in queue['schedule']], [PREP_MINUTES[item['id']] * 2 for item in catalogue[3:]])
    def test_adding_products_preserves_existing_stock_and_orders(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'existing.db'
            initialise_database(path)
            place_order(1, 2, path)
            from database import connect, get_orders
            with closing(connect(path)) as connection:
                connection.execute('DELETE FROM products WHERE id > 3')
                connection.commit()
            initialise_database(path)
            self.assertEqual(len(get_menu(path)), len(MENU))
            self.assertEqual(get_menu(path)[0]['stock'], 18)
            self.assertEqual(len(get_orders(path)), 1)


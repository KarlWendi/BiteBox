"""Run with: python -m unittest -v"""

import unittest
from unittest.mock import patch

from ordering import calculate_order, find_item


class OrderingTests(unittest.TestCase):
    def test_two_burgers_total_798_pence(self):
        order = calculate_order(1, 2)
        self.assertEqual(order["total_pence"], 798)
        self.assertEqual(order["name"], "Cheeseburger")
        self.assertEqual(order["quantity"], 2)

    def test_different_product_uses_its_own_price(self):
        self.assertEqual(calculate_order(2, 3)["total_pence"], 597)

    def test_quantity_boundaries_are_accepted(self):
        self.assertEqual(calculate_order(1, 1)["total_pence"], 399)
        self.assertEqual(calculate_order(1, 50)["total_pence"], 19950)

    def test_invalid_quantities_are_rejected(self):
        for quantity in [0, -1, 51, 1.5, "2", True]:
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValueError):
                    calculate_order(1, quantity)

    def test_invalid_ids_are_rejected(self):
        for item_id in [0, -1, 1.5, "1", True, 999]:
            with self.subTest(item_id=item_id):
                with self.assertRaises(ValueError):
                    calculate_order(item_id, 1)

    def test_lookup_uses_id_rather_than_list_position(self):
        with patch("ordering.MENU", [
            {"id": 42, "name": "Drink", "price_pence": 150},
        ]):
            self.assertEqual(find_item(42)["name"], "Drink")
            self.assertEqual(calculate_order(42, 2)["total_pence"], 300)


if __name__ == "__main__":
    unittest.main()

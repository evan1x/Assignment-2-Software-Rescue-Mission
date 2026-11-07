
"""
Campus Supply Desk - Additional Automated Tests
COMP3415 Assignment 2 - Task 2

"""

from pathlib import Path
import tempfile
import unittest

from supplydesk.service import OrderService


class OrderServiceSafetyNetTests(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state_path = Path(temporary.name) / "state.json"
        self.service = OrderService(self.state_path)

    @staticmethod
    def item(product_id, quantity):
        return {
            "product_id": product_id,
            "quantity": quantity
        }

    @staticmethod
    def stock_of(products, product_id):
        return next(
            p["stock"]
            for p in products
            if p["product_id"] == product_id
        )

    # CATEGORY 1: NORMAL BEHAVIOR

    # Test 1: Multiple-product quote
    def test_multi_item_regular_pickup_quote(self):
        result = self.service.quote(
            "regular",
            [
                self.item("notebook", 2),
                self.item("pen-pack", 1)
            ]
        )

        self.assertEqual(result["subtotal_cents"], 1750)
        self.assertEqual(result["discount_cents"], 0)
        self.assertEqual(result["delivery_cents"], 0)
        self.assertEqual(result["total_cents"], 1750)

        self.assertEqual(
            [
                line["line_total_cents"]
                for line in result["items"]
            ],
            [1000, 750]
        )

    # Test 2: Order updates stock and saves history
    def test_placing_order_deducts_stock_and_persists_history(self):
        order = self.service.place_order(
            "regular",
            [self.item("bag", 2)]
        )

        self.assertEqual(order["order_id"], "ORD-0001")
        self.assertEqual(order["status"], "placed")

        self.assertEqual(
            self.stock_of(self.service.catalog(), "bag"),
            2
        )

        reopened = OrderService(self.state_path)

        self.assertEqual(reopened.list_orders(), [order])

        self.assertEqual(
            self.stock_of(reopened.catalog(), "bag"),
            2
        )

    # Test 3: Quotes should not change inventory
    def test_quote_does_not_reserve_stock_or_create_save_file(self):
        before = self.service.catalog()

        quote = self.service.quote(
            "regular",
            [self.item("hoodie", 1)]
        )

        self.assertEqual(quote["total_cents"], 4000)
        self.assertEqual(self.service.catalog(), before)
        self.assertEqual(self.service.list_orders(), [])
        self.assertFalse(self.state_path.exists())

    # CATEGORY 2: BOUNDARY BEHAVIOR

    # Test 4: Student discount at exactly $50
    def test_student_discount_applies_at_exactly_5000_cents(self):
        result = self.service.quote(
            "student",
            [
                self.item("hoodie", 1),
                self.item("notebook", 2)
            ]
        )

        self.assertEqual(result["subtotal_cents"], 5000)

        # Expected 10% discount at exactly $50
        self.assertEqual(result["discount_cents"], 500)
        self.assertEqual(result["total_cents"], 4500)

    # Test 5: Purchasing all remaining stock
    def test_order_can_use_exactly_remaining_stock(self):
        order = self.service.place_order(
            "regular",
            [self.item("bag", 4)]
        )

        self.assertEqual(order["subtotal_cents"], 10000)

        self.assertEqual(
            self.stock_of(self.service.catalog(), "bag"),
            0
        )

        self.assertEqual(self.service.list_orders(), [order])

    # CATEGORY 3: INVALID OR EXCEPTIONAL INPUT

    # Test 6: Invalid quantities are rejected
    def test_invalid_quantities_rejected_without_mutating_state(self):
        self.service.place_order(
            "regular",
            [self.item("mug", 1)]
        )

        before = self.state_path.read_bytes()

        invalid_quantities = (0, -1, 100, 1.5, "2", True)

        for quantity in invalid_quantities:
            for operation in (
                self.service.quote,
                self.service.place_order
            ):

                with self.subTest(
                    quantity=quantity,
                    operation=operation.__name__
                ):

                    with self.assertRaises(ValueError):
                        operation(
                            "regular",
                            [self.item("notebook", quantity)]
                        )

                    self.assertEqual(
                        self.state_path.read_bytes(),
                        before
                    )

    # Test 7: Invalid products and options
    def test_unknown_product_or_unsupported_options_do_not_mutate_state(self):
        self.service.place_order(
            "regular",
            [self.item("mug", 1)]
        )

        before = self.state_path.read_bytes()

        cases = (
            ("regular", [self.item("missing", 1)], "pickup"),
            ("staff", [self.item("notebook", 1)], "pickup"),
            ("regular", [self.item("notebook", 1)], "drone"),
            ("regular", [], "pickup")
        )

        for operation in (
            self.service.quote,
            self.service.place_order
        ):

            for customer, items, fulfillment in cases:

                with self.subTest(
                    operation=operation.__name__,
                    customer=customer,
                    items=items,
                    fulfillment=fulfillment
                ):

                    with self.assertRaises(ValueError):
                        operation(
                            customer,
                            items,
                            fulfillment
                        )

                    self.assertEqual(
                        self.state_path.read_bytes(),
                        before
                    )

    # Test 8: Duplicate product lines in quote
    def test_duplicate_product_lines_above_stock_rejected_in_quote(self):
        # Bag stock = 4
        # Requested = 3 + 2 = 5
        # Expected: ValueError

        with self.assertRaises(ValueError):
            self.service.quote(
                "regular",
                [
                    self.item("bag", 3),
                    self.item("bag", 2)
                ]
            )

        self.assertFalse(self.state_path.exists())

    # Test 9: Duplicate product lines in order
    def test_duplicate_product_lines_above_stock_rejected_in_placement(self):
        with self.assertRaises(ValueError):
            self.service.place_order(
                "regular",
                [
                    self.item("bag", 3),
                    self.item("bag", 2)
                ]
            )

        self.assertFalse(self.state_path.exists())

    # CATEGORY 4: IMPORTANT BEHAVIOR TO PRESERVE

    # Test 10: Quote and placed order totals match
    def test_quoted_items_and_prices_match_placed_order(self):
        items = [
            self.item("hoodie", 2),
            self.item("notebook", 1)
        ]

        quote = self.service.quote(
            "student",
            items,
            "delivery"
        )

        order = self.service.place_order(
            "student",
            items,
            "delivery"
        )

        keys = (
            "items",
            "subtotal_cents",
            "discount_cents",
            "delivery_cents",
            "total_cents",
            "customer_type",
            "fulfillment"
        )

        for key in keys:
            with self.subTest(field=key):
                self.assertEqual(order[key], quote[key])

        self.assertEqual(quote["subtotal_cents"], 8500)
        self.assertEqual(quote["discount_cents"], 850)
        self.assertEqual(quote["delivery_cents"], 600)
        self.assertEqual(quote["total_cents"], 8250)

    # Test 11: Repeated cancellation restores stock once
    def test_cancelling_twice_does_not_restore_stock_twice(self):
        order = self.service.place_order(
            "regular",
            [self.item("mug", 2)]
        )

        first = self.service.cancel_order(order["order_id"])

        self.assertEqual(first["status"], "cancelled")

        self.assertEqual(
            self.stock_of(self.service.catalog(), "mug"),
            8
        )

        second = self.service.cancel_order(order["order_id"])

        self.assertEqual(second["status"], "cancelled")

        # Inventory must not exceed original stock
        self.assertEqual(
            self.stock_of(self.service.catalog(), "mug"),
            8
        )

        self.assertEqual(len(self.service.list_orders()), 1)

    # Test 12: Order history and unique IDs
    def test_cancelled_orders_remain_in_history_and_ids_are_not_reused(self):
        first = self.service.place_order(
            "regular",
            [self.item("notebook", 1)]
        )

        self.service.cancel_order(first["order_id"])

        second = self.service.place_order(
            "regular",
            [self.item("pen-pack", 1)]
        )

        history = OrderService(self.state_path).list_orders()

        self.assertEqual(
            [o["order_id"] for o in history],
            ["ORD-0001", "ORD-0002"]
        )

        self.assertEqual(
            [o["status"] for o in history],
            ["cancelled", "placed"]
        )


if __name__ == "__main__":
    unittest.main()

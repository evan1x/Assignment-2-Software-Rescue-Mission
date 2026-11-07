"""CR-01 express delivery. Pickup and standard delivery stay covered by the other suites."""

from pathlib import Path
import contextlib
import io
import tempfile
import unittest
from unittest.mock import patch

from supplydesk.cli import main
from supplydesk.menu import handle_quote
from supplydesk.service import OrderService


class ExpressDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.service = OrderService(self.path)

    def test_regular_express_two_notebooks(self):
        quote = self.service.quote(
            "regular",
            [{"product_id": "notebook", "quantity": 2}],
            "express",
        )

        self.assertEqual(quote["fulfillment"], "express")
        self.assertEqual(quote["subtotal_cents"], 1000)
        self.assertEqual(quote["discount_cents"], 0)
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 2200)
        self.assertFalse(self.path.exists())

    def test_student_express_two_hoodies(self):
        quote = self.service.quote(
            "student",
            [{"product_id": "hoodie", "quantity": 2}],
            "express",
        )

        self.assertEqual(quote["subtotal_cents"], 8000)
        self.assertEqual(quote["discount_cents"], 800)
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 8400)

    def test_express_fee_is_not_waived_when_standard_delivery_is_free(self):
        items = [{"product_id": "hoodie", "quantity": 3}]

        standard = self.service.quote("regular", items, "delivery")
        express = self.service.quote("regular", items, "express")

        self.assertEqual(standard["subtotal_cents"], 12000)
        self.assertEqual(standard["discount_cents"], 0)
        self.assertEqual(standard["delivery_cents"], 0)
        self.assertEqual(standard["total_cents"], 12000)
        self.assertEqual(express["discount_cents"], 0)
        self.assertEqual(express["delivery_cents"], 1200)
        self.assertEqual(express["total_cents"], 13200)

    def test_express_quote_matches_order_after_reopen_and_cancel(self):
        items = [{"product_id": "hoodie", "quantity": 2}]
        quote = self.service.quote("student", items, "express")
        order = self.service.place_order("student", items, "express")

        keys = (
            "items",
            "subtotal_cents",
            "discount_cents",
            "delivery_cents",
            "total_cents",
            "customer_type",
            "fulfillment",
        )
        for key in keys:
            self.assertEqual(order[key], quote[key])

        self.assertEqual(order["status"], "placed")
        self.assertEqual(order["delivery_cents"], 1200)
        self.assertEqual(order["total_cents"], 8400)

        reopened = OrderService(self.path).get_order(order["order_id"])
        self.assertEqual(reopened, order)

        cancelled = self.service.cancel_order(order["order_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        for key in keys:
            self.assertEqual(cancelled[key], order[key])

        hoodie_stock = next(
            product["stock"]
            for product in self.service.catalog()
            if product["product_id"] == "hoodie"
        )
        self.assertEqual(hoodie_stock, 5)

        saved = OrderService(self.path).get_order(order["order_id"])
        self.assertEqual(saved["status"], "cancelled")
        self.assertEqual(saved["fulfillment"], "express")
        self.assertEqual(saved["delivery_cents"], 1200)
        self.assertEqual(saved["discount_cents"], 800)
        self.assertEqual(saved["total_cents"], 8400)

    def test_other_fulfillment_values_still_rejected(self):
        item = [{"product_id": "notebook", "quantity": 1}]
        for fulfillment in ("drone", "Express", "shipping", ""):
            with self.subTest(fulfillment=fulfillment):
                with self.assertRaises(ValueError):
                    self.service.quote("regular", item, fulfillment)
                self.assertFalse(self.path.exists())

    def test_cli_express_quote_reports_8400(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main([
                "--data", str(self.path),
                "quote",
                "--customer", "student",
                "--fulfillment", "express",
                "--item", "hoodie:2",
            ])

        self.assertEqual(code, 0)
        self.assertIn('"total_cents": 8400', buffer.getvalue())
        self.assertIn('"delivery_cents": 1200', buffer.getvalue())
        self.assertFalse(self.path.exists())

    def test_cli_place_express_order_saves_fee_and_stock(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main([
                "--data", str(self.path),
                "place",
                "--customer", "regular",
                "--fulfillment", "express",
                "--item", "notebook:2",
            ])

        self.assertEqual(code, 0)
        self.assertIn('"order_id": "ORD-0001"', buffer.getvalue())
        self.assertIn('"fulfillment": "express"', buffer.getvalue())
        self.assertIn('"delivery_cents": 1200', buffer.getvalue())
        self.assertIn('"total_cents": 2200', buffer.getvalue())

        reopened = OrderService(self.path)
        order = reopened.get_order("ORD-0001")
        self.assertEqual(order["status"], "placed")
        self.assertEqual(order["total_cents"], 2200)
        notebook_stock = next(
            product["stock"]
            for product in reopened.catalog()
            if product["product_id"] == "notebook"
        )
        self.assertEqual(notebook_stock, 18)

    def test_cli_omitted_options_stay_regular_pickup(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main([
                "--data", str(self.path),
                "quote",
                "--item", "notebook:2",
            ])

        self.assertEqual(code, 0)
        text = buffer.getvalue()
        self.assertIn('"customer_type": "regular"', text)
        self.assertIn('"fulfillment": "pickup"', text)
        self.assertIn('"delivery_cents": 0', text)
        self.assertIn('"total_cents": 1000', text)
        self.assertFalse(self.path.exists())

    def test_menu_accepts_express_and_blank_fulfillment_stays_pickup(self):
        express_output = io.StringIO()
        with patch("builtins.input", side_effect=["regular", "notebook", "2", "", "express"]) as prompts:
            with contextlib.redirect_stdout(express_output):
                handle_quote(self.service)

        fulfillment_prompt = prompts.call_args_list[-1].args[0]
        self.assertEqual(
            fulfillment_prompt,
            "Fulfillment [pickup/delivery/express] (Enter = pickup): ",
        )
        express_text = express_output.getvalue()
        self.assertIn("Fulfillment: express", express_text)
        self.assertIn("Delivery: $12.00", express_text)
        self.assertIn("Total: $22.00", express_text)
        self.assertFalse(self.path.exists())

        pickup_output = io.StringIO()
        with patch("builtins.input", side_effect=["", "notebook", "2", "", ""]):
            with contextlib.redirect_stdout(pickup_output):
                handle_quote(self.service)

        pickup_text = pickup_output.getvalue()
        self.assertIn("Customer: regular | Fulfillment: pickup", pickup_text)
        self.assertIn("Delivery: $0.00", pickup_text)
        self.assertIn("Total: $10.00", pickup_text)

    def test_quote_help_lists_express(self):
        buffer = io.StringIO()
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stdout(buffer):
                main(["quote", "--help"])

        self.assertEqual(caught.exception.code, 0)
        self.assertIn("express", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()

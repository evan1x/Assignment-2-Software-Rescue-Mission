"""Operations used by the command-line order desk."""

from supplydesk.storage import JsonStore

# Pricing rules are integer Canadian cents.
STUDENT_DISCOUNT_THRESHOLD = 5000
STUDENT_DISCOUNT_PERCENT = 10
DISCOUNT_PERCENT_DIVISOR = 100
# Half a cent rounds upward: add half the divisor before integer division.
DISCOUNT_ROUNDING_BIAS = DISCOUNT_PERCENT_DIVISOR // 2
FREE_DELIVERY_THRESHOLD = 10000
DELIVERY_FEE_CENTS = 600


class OrderService:
    def __init__(self, state_path=".supplydesk/state.json"):
        self.store = JsonStore(state_path)

    def catalog(self):
        return self.store.load()["catalog"]

    def _price_request(self, state, customer_type, items, fulfillment):
        if customer_type not in ("regular", "student"):
            raise ValueError("Customer type must be regular or student.")
        if fulfillment not in ("pickup", "delivery"):
            raise ValueError("Fulfillment must be pickup or delivery.")
        if not isinstance(items, list) or not items:
            raise ValueError("An order must contain at least one item.")
        lines = []
        subtotal = 0
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each item must contain a product_id and quantity.")
            product = None
            for candidate in state["catalog"]:
                if candidate["product_id"] == item.get("product_id"):
                    product = candidate
                    break
            if product is None:
                raise ValueError("Unknown product.")
            quantity = item.get("quantity")
            if type(quantity) is not int or quantity < 1 or quantity > 99:
                raise ValueError("Quantity must be an integer from 1 to 99.")
            if quantity > product["stock"]:
                raise ValueError("Not enough stock for " + product["product_id"] + ".")
            line_total = product["unit_price_cents"] * quantity
            subtotal += line_total
            lines.append({
                "product_id": product["product_id"],
                "name": product["name"],
                "unit_price_cents": product["unit_price_cents"],
                "quantity": quantity,
                "line_total_cents": line_total,
            })
        discount = 0
        if customer_type == "student" and subtotal > STUDENT_DISCOUNT_THRESHOLD:
            discount = (
                subtotal * STUDENT_DISCOUNT_PERCENT + DISCOUNT_ROUNDING_BIAS
            ) // DISCOUNT_PERCENT_DIVISOR
        delivery = 0
        if fulfillment == "delivery" and subtotal - discount < FREE_DELIVERY_THRESHOLD:
            delivery = DELIVERY_FEE_CENTS
        return {
            "customer_type": customer_type,
            "fulfillment": fulfillment,
            "items": lines,
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "delivery_cents": delivery,
            "total_cents": subtotal - discount + delivery,
        }

    def quote(self, customer_type, items, fulfillment="pickup"):
        state = self.store.load()
        return self._price_request(state, customer_type, items, fulfillment)

    def place_order(self, customer_type, items, fulfillment="pickup"):
        state = self.store.load()
        priced = self._price_request(state, customer_type, items, fulfillment)
        order = {
            "order_id": "ORD-" + str(state["next_order_number"]).zfill(4),
            "status": "placed",
            "customer_type": priced["customer_type"],
            "fulfillment": priced["fulfillment"],
            "items": priced["items"],
            "subtotal_cents": priced["subtotal_cents"],
            "discount_cents": priced["discount_cents"],
            "delivery_cents": priced["delivery_cents"],
            "total_cents": priced["total_cents"],
        }
        for line in priced["items"]:
            for product in state["catalog"]:
                if product["product_id"] == line["product_id"]:
                    product["stock"] -= line["quantity"]
        state["next_order_number"] += 1
        state["orders"].append(order)
        self.store.save(state)
        return order

    def list_orders(self):
        return self.store.load()["orders"]

    def get_order(self, order_id):
        state = self.store.load()
        for order in state["orders"]:
            if order["order_id"] == order_id:
                return order
        raise ValueError("Unknown order: " + order_id)

    def cancel_order(self, order_id):
        state = self.store.load()
        order = None
        for candidate in state["orders"]:
            if candidate["order_id"] == order_id:
                order = candidate
                break
        if order is None:
            raise ValueError("Unknown order: " + order_id)
        for line in order["items"]:
            for product in state["catalog"]:
                if product["product_id"] == line["product_id"]:
                    product["stock"] += line["quantity"]
        order["status"] = "cancelled"
        self.store.save(state)
        return order

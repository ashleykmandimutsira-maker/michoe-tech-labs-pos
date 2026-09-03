"""Focused Phase 3 persistence and checkout regression tests."""
import shutil
import tempfile
import unittest
from pathlib import Path

from database.db import configure_database
from models.product import Product
from services.product_service import ProductService
from services.sales_service import SalesService


class Phase3Tests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="pos_phase3_"))
        configure_database(str(self.directory / "phase3.db"))
        self.products = ProductService()
        self.sales = SalesService()
        self.product_id = self.products.create_product(Product(part_no="P3-001", description="Phase 3 Part", selling_price=25, cost_price=10, quantity_on_hand=10))
        self.cart = {self.product_id: {"product_id": self.product_id, "part_no": "P3-001", "description": "Phase 3 Part", "brand": "", "vehicle_make": None, "vehicle_model": None, "unit_price": 25, "quantity": 2}}
        self.customer = {"name": "Phase Customer", "phone": "0770000000", "email": "phase@example.test", "city": "Harare"}

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_split_payments_complete_once_total_is_covered(self):
        sale = self.sales.create_sale(user_id=1, cashier_name="Administrator")
        self.sales.add_item_to_sale(sale, self.product_id, 2)
        self.sales.add_payment(sale, "CASH_USD", 20, "USD", 20)
        self.sales.add_payment(sale, "CARD", sale.total - 20, "USD", sale.total - 20)
        self.assertGreater(self.sales.complete_sale(sale), 0)
        self.assertEqual(2, len(self.sales.db.execute_query("SELECT id FROM payments WHERE sale_id=?", (sale.id,))))

    def test_hold_round_trips_without_inventory_change(self):
        held = self.sales.hold_sale(self.cart, self.customer, 1)
        self.assertEqual(10, self.products.get_product_by_id(self.product_id).quantity_on_hand)
        resumed = self.sales.release_held_sale(held['id'])
        self.assertEqual(self.cart, resumed['cart'])
        self.assertEqual(self.customer, resumed['customer'])
        self.assertFalse(self.sales.list_held_sales())

    def test_quote_persists_and_converts_to_paid_sale(self):
        quote = self.sales.create_quotation(self.cart, self.customer, 1)
        loaded = self.sales.get_quotation(quote['id'])
        self.assertEqual('DRAFT', loaded['status'])
        self.assertEqual(2, loaded['items'][0]['quantity'])
        self.sales.change_quotation_status(quote['id'], 'ISSUED', user_id=1)
        sale = self.sales.sale_from_quotation(quote['id'], 1, 'Administrator')
        self.sales.add_payment(sale, 'CARD', sale.total, 'USD', sale.total)
        self.sales.complete_sale(sale)
        self.sales.mark_quotation_converted(quote['id'], sale.id)
        converted = self.sales.get_quotation(quote['id'])
        self.assertEqual('CONVERTED', converted['status'])
        self.assertEqual(sale.id, converted['converted_sale_id'])


if __name__ == '__main__':
    unittest.main()
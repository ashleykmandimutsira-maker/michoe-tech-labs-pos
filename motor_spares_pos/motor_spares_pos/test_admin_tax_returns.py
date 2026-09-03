"""Isolated regression coverage for cleanup, tax reporting, and return invoice lookup."""

import shutil
import tempfile
import unittest
from pathlib import Path

from database.db import configure_database
from models.product import Product
from services.admin_cleanup_service import AdminCleanupService
from services.auth_service import AuthenticationService
from services.product_service import ProductService
from services.returns_service import ReturnsService
from services.sales_service import SalesService
from services.tax_report_service import TaxReportService


class AdminTaxReturnsTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="pos_admin_tax_"))
        configure_database(str(self.directory / "admin.db"))
        self.products = ProductService()
        self.sales = SalesService()
        self.product_id = self.products.create_product(
            Product(
                part_no="TAX-001",
                description="Tax part",
                cost_price=10,
                selling_price=20,
                quantity_on_hand=4,
            )
        )
        self.sale = self.sales.create_sale(
            customer_name="Tax Customer",
            customer_phone="0770000000",
            vehicle_registration="TAX-123",
            user_id=1,
            cashier_name="Administrator",
        )
        self.sales.add_item_to_sale(self.sale, self.product_id, 1)
        self.sales.add_payment(
            self.sale, "CARD", self.sale.total, "USD", self.sale.total
        )
        self.sales.complete_sale(self.sale)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_tax_summary_and_return_invoice_search_use_real_data(self):
        report = TaxReportService().summary("2000-01-01", "2100-01-01")
        self.assertEqual(1, report["sales"]["invoices"])
        self.assertGreater(report["sales"]["output_vat"], 0)
        matches = ReturnsService().search_original_invoices("0770000000")
        self.assertEqual(
            self.sale.invoice_number, matches[0]["invoice_number"]
        )
        export_path = self.directory / "tax_report.xlsx"
        self.assertEqual(
            1,
            TaxReportService().export_xlsx(
                str(export_path), "2000-01-01", "2100-01-01"
            ),
        )
        self.assertTrue(export_path.exists())

    def test_cleanup_creates_backup_archives_inventory_and_denies_cashier(
        self,
    ):
        cleanup = AdminCleanupService()
        result = cleanup.cleanup("inventory", 1)
        self.assertTrue(Path(result["backup"]).exists())
        self.assertEqual(1, result["archived_products"])
        self.assertEqual(
            0,
            self.products.db.execute_query(
                "SELECT COUNT(*) count FROM products WHERE active=1"
            )[0]["count"],
        )
        cashier_id = AuthenticationService().create_user(
            "cleanup_cashier", "cash123", "Cleanup Cashier", 3
        )
        with self.assertRaises(PermissionError):
            cleanup.cleanup("inventory", cashier_id)

    def test_sales_cleanup_voids_not_deletes_financial_records(self):
        result = AdminCleanupService().cleanup("sales_invoices", 1)
        self.assertEqual(1, result["voided_invoices"])
        self.assertEqual(
            "VOIDED",
            self.sales.db.execute_query(
                "SELECT status FROM invoices WHERE invoice_number=?",
                (self.sale.invoice_number,),
            )[0]["status"],
        )
        self.assertTrue(
            self.sales.db.execute_query(
                "SELECT 1 FROM payments WHERE sale_id=?", (self.sale.id,)
            )
        )


if __name__ == "__main__":
    unittest.main()

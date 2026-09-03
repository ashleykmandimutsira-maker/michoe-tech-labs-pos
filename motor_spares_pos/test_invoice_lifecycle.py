"""Isolated regression tests for immutable paid invoices and invoice voids."""
import shutil
import tempfile
import unittest
from pathlib import Path
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QPushButton

from database.db import configure_database
from models.product import Product
from services.product_service import ProductService
from services.sales_service import SalesService
from ui.test_window import POSPage


class InvoiceLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pos_invoice_'))
        configure_database(str(self.directory / 'invoice.db'))
        self.products = ProductService()
        self.sales = SalesService()
        self.product_id = self.products.create_product(Product(part_no='INV-LIFE', description='Invoice part', cost_price=5, selling_price=10, quantity_on_hand=5))
        self.sale = self.sales.create_sale(customer_name='Invoice Customer', user_id=1, cashier_name='Administrator')
        self.sales.add_item_to_sale(self.sale, self.product_id, 1)
        self.sales.add_payment(self.sale, 'CARD', self.sale.total, 'USD', self.sale.total)
        self.sales.complete_sale(self.sale)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_paid_invoice_is_voided_but_preserved_with_audit(self):
        self.assertTrue(self.sales.void_invoice(self.sale.invoice_number, 1, 'Customer cancellation'))
        invoice = self.sales.db.execute_query('SELECT * FROM invoices WHERE invoice_number=?', (self.sale.invoice_number,))[0]
        self.assertEqual('VOIDED', invoice['status'])
        self.assertEqual(1, invoice['voided_by'])
        self.assertIsNotNone(invoice['voided_at'])
        self.assertEqual('VOIDED', self.sales.get_sale_by_id(self.sale.id).status)
        self.assertEqual(5, self.products.get_product_by_id(self.product_id).quantity_on_hand)
        self.assertEqual(1, self.sales.db.execute_query("SELECT COUNT(*) count FROM payments WHERE sale_id=?", (self.sale.id,))[0]['count'])
        self.assertTrue(self.sales.db.execute_query("SELECT 1 FROM audit_logs WHERE action='INVOICE_VOIDED' AND entity_type='INVOICE'"))

    def test_paid_invoice_cannot_be_deleted_as_draft(self):
        with self.assertRaises(ValueError):
            self.sales.delete_draft_invoice(self.sale.invoice_number, 1)
        self.assertTrue(self.sales.db.execute_query('SELECT 1 FROM invoices WHERE invoice_number=?', (self.sale.invoice_number,)))

    def test_draft_invoice_can_be_deleted_without_deleting_sale(self):
        draft = 'DRAFT-TEST-001'
        self.sales.db.execute_update("INSERT INTO invoices(invoice_number,sale_id,customer_name,subtotal,vat_amount,total,status) VALUES(?,?,?,?,?,?, 'DRAFT')", (draft, self.sale.id, 'Invoice Customer', 0, 0, 0))
        self.assertTrue(self.sales.delete_draft_invoice(draft, 1))
        self.assertFalse(self.sales.db.execute_query('SELECT 1 FROM invoices WHERE invoice_number=?', (draft,)))
        self.assertTrue(self.sales.get_sale_by_id(self.sale.id))

    def test_pos_has_one_quotation_history_button(self):
        page = POSPage(self.products, None, None)
        self.assertEqual(1, sum(button.text() == 'QUOTATION HISTORY' for button in page.findChildren(QPushButton)))
        page.deleteLater()


if __name__ == '__main__': unittest.main()
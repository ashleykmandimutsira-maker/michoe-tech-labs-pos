"""Regression coverage for atomic, non-blocking bulk product archiving."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database.db import configure_database
from services.product_service import ProductService


class BulkArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pos_bulk_archive_'))
        self.path = self.directory / 'bulk.db'
        configure_database(str(self.path))

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _seed(self, count):
        service = ProductService()
        with service.db.transaction() as conn:
            conn.executemany(
                'INSERT INTO products(part_no,description,cost_price,selling_price,quantity_on_hand,active) VALUES(?,?,?,?,?,1)',
                [(f'BULK-{index:05d}', f'Bulk product {index}', 1.0, 2.0, 5) for index in range(count)],
            )
        return service

    def _archive_and_assert(self, count):
        service = self._seed(count)
        with patch.object(service.sync, 'request_background_sync') as request_sync, patch('services.product_service.emit_change') as emit:
            self.assertEqual(count, service.archive_all_active_products(1, 'catalogue maintenance'))
        self.assertEqual(0, service.db.execute_query('SELECT COUNT(*) count FROM products WHERE active=1')[0]['count'])
        self.assertEqual(count, service.db.execute_query("SELECT COUNT(*) count FROM sync_queue WHERE entity_type='PRODUCT' AND operation='UPDATE'")[0]['count'])
        self.assertEqual(count, service.db.execute_query("SELECT COUNT(*) count FROM (SELECT entity_id FROM sync_queue WHERE entity_type='PRODUCT' AND operation='UPDATE' GROUP BY entity_id)")[0]['count'])
        self.assertEqual(1, service.db.execute_query("SELECT COUNT(*) count FROM audit_logs WHERE action='PRODUCTS_BULK_ARCHIVED'")[0]['count'])
        request_sync.assert_called_once(); emit.assert_called_once()
        configure_database(str(self.path))
        self.assertEqual(count, ProductService().db.execute_query('SELECT COUNT(*) count FROM products WHERE active=0')[0]['count'])

    def test_archives_100_products_once(self): self._archive_and_assert(100)
    def test_archives_1000_products_once(self): self._archive_and_assert(1000)

    def test_physical_delete_with_history_remains_blocked(self):
        service = self._seed(1)
        product_id = service.db.execute_query("SELECT id FROM products WHERE part_no='BULK-00000'")[0]['id']
        service.db.execute_update('INSERT INTO stock_movements(product_id,movement_type,quantity,previous_quantity,new_quantity) VALUES(?,?,?,?,?)', (product_id, 'PURCHASE', 1, 0, 1))
        with self.assertRaises(ValueError): service.delete_product(product_id, 1)

    def test_clear_catalog_deletes_unreferenced_and_archives_history(self):
        service = self._seed(2)
        historical_id = service.db.execute_query("SELECT id FROM products WHERE part_no='BULK-00000'")[0]['id']
        service.db.execute_update('INSERT INTO stock_movements(product_id,movement_type,quantity,previous_quantity,new_quantity) VALUES(?,?,?,?,?)', (historical_id, 'PURCHASE', 1, 0, 1))
        with patch.object(service.sync, 'request_background_sync') as request_sync, patch('services.product_service.emit_change') as emit:
            result = service.clear_active_catalog(1)
        self.assertEqual({'deleted': 1, 'archived': 1}, result)
        self.assertEqual(0, service.db.execute_query('SELECT COUNT(*) count FROM products WHERE active=1')[0]['count'])
        self.assertEqual(1, service.db.execute_query("SELECT COUNT(*) count FROM products WHERE part_no='BULK-00000' AND active=0")[0]['count'])
        self.assertEqual(1, service.db.execute_query("SELECT COUNT(*) count FROM product_tombstones WHERE part_no='BULK-00001'")[0]['count'])
        self.assertEqual(1, service.db.execute_query("SELECT COUNT(*) count FROM audit_logs WHERE action='PRODUCTS_CATALOG_CLEARED'")[0]['count'])
        request_sync.assert_called_once(); emit.assert_called_once()


if __name__ == '__main__': unittest.main()
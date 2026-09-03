"""Offscreen regression tests for dashboard access and graph removal."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QMessageBox
from database.db import configure_database
from services.auth_service import AuthenticationService
from ui.test_window import MotorSparesPOSTestWindow


class DashboardAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pos_dashboard_'))
        configure_database(str(self.directory / 'dashboard.db'))
        auth = AuthenticationService()
        self.admin = auth.authenticate('admin', 'admin123')
        cashier_id = auth.create_user('dash_cashier', 'cash123', 'Dashboard Cashier', 3)
        self.cashier = auth.authenticate('dash_cashier', 'cash123')
        self.auth = auth
        self.cashier_id = cashier_id

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_admin_sees_dashboard_without_sales_overview_chart(self):
        window = MotorSparesPOSTestWindow(self.admin)
        self.assertIn('Dashboard', window.pages)
        dashboard = window.pages['Dashboard']
        self.assertFalse(hasattr(dashboard, 'chart_view'))
        window.close()

    def test_cashier_cannot_see_or_route_to_dashboard(self):
        window = MotorSparesPOSTestWindow(self.cashier)
        self.assertNotIn('Dashboard', window.pages)
        self.assertEqual('POS', window.header.text())
        with patch.object(QMessageBox, 'warning') as warning:
            self.assertTrue(window.go('Dashboard'))
            warning.assert_called_once_with(window, 'Access denied', 'Access denied.')
        self.assertEqual('POS', window.header.text())
        window.close()

    def test_explicit_dashboard_permission_allows_dashboard(self):
        permission_id = self.auth.db.execute_query("SELECT id FROM permissions WHERE code='dashboard.view'")[0]['id']
        self.auth.grant_permission(self.cashier_id, permission_id, self.admin.id)
        user = self.auth.authenticate('dash_cashier', 'cash123')
        window = MotorSparesPOSTestWindow(user)
        self.assertIn('Dashboard', window.pages)
        self.assertTrue(window.go('Dashboard'))
        window.close()


if __name__ == '__main__':
    unittest.main()
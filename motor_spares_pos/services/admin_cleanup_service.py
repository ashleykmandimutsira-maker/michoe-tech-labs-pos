"""Admin-only, backup-first operational data cleanup."""
from datetime import datetime
from pathlib import Path

from database.db import get_database_manager
from services.audit_service import AuditService
from services.permission_service import PermissionService
from services.product_service import ProductService
from services.sales_service import SalesService


class AdminCleanupService:
    def __init__(self):
        self.db = get_database_manager()

    def backup(self) -> str:
        target = Path(self.db.db_path)
        backup = target.with_name(f"{target.stem}_before_cleanup_{datetime.now():%Y%m%d_%H%M%S}{target.suffix}")
        self.db.backup(str(backup))
        return str(backup)

    def cleanup(self, option: str, user_id: int) -> dict:
        permissions = PermissionService()
        if not permissions.is_admin(user_id) or not permissions.has_permission(user_id, 'system.reset'):
            raise PermissionError('Only an administrator can run system cleanup')
        valid = {'inventory', 'customers', 'quotations', 'sales_invoices', 'full'}
        if option not in valid:
            raise ValueError('Invalid cleanup option')
        backup = self.backup()
        results = {'backup': backup, 'archived_products': 0, 'archived_customers': 0, 'cancelled_quotes': 0, 'voided_invoices': 0}
        if option in {'inventory', 'full'}:
            results['archived_products'] = ProductService().archive_all_active_products(user_id, 'Administrative data cleanup', request_sync=False)
        with self.db.transaction() as conn:
            if option in {'customers', 'full'}:
                results['archived_customers'] = conn.execute('UPDATE customers SET active=0,updated_at=CURRENT_TIMESTAMP WHERE active=1').rowcount
                conn.execute('UPDATE vehicles SET active=0,updated_at=CURRENT_TIMESTAMP WHERE active=1')
            if option in {'quotations', 'full'}:
                results['cancelled_quotes'] = conn.execute("UPDATE quotations SET status='CANCELLED',updated_at=CURRENT_TIMESTAMP WHERE status IN ('DRAFT','ISSUED')").rowcount
        if option in {'sales_invoices', 'full'}:
            invoices = self.db.execute_query("SELECT invoice_number FROM invoices WHERE status NOT IN ('VOIDED','DRAFT')")
            for invoice in invoices:
                SalesService().void_invoice(invoice['invoice_number'], user_id, 'Administrative data cleanup')
            results['voided_invoices'] = len(invoices)
        AuditService().log_action('SYSTEM_DATA_CLEANUP', 'SYSTEM', None, user_id, details=f'{option}; backup: {backup}; {results}')
        return results
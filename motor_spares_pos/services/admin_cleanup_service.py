"""Admin-only, backup-first permanent operational data reset."""
from datetime import datetime
from pathlib import Path

from database.db import get_database_manager
from services.audit_service import AuditService
from services.permission_service import PermissionService
from core.events import emit_change


class AdminCleanupService:
    """Permanently removes selected operational data while retaining access control."""
    ALL_OPTIONS = frozenset({'inventory', 'customers', 'quotations', 'sales_invoices', 'returns', 'stock_movements', 'analytics', 'reports', 'users', 'settings'})
    def __init__(self):
        self.db = get_database_manager()

    def backup(self) -> str:
        target = Path(self.db.db_path)
        backup = target.with_name(f"{target.stem}_before_reset_{datetime.now():%Y%m%d_%H%M%S}{target.suffix}")
        self.db.backup(str(backup))
        return str(backup)

    @staticmethod
    def _delete(conn, table: str, where: str = '', params: tuple = ()) -> int:
        return conn.execute(f'DELETE FROM {table}' + (f' WHERE {where}' if where else ''), params).rowcount

    def reset(self, selections: set[str] | list[str] | tuple[str, ...], user_id: int) -> dict:
        """Back up and permanently delete selected data groups.

        The calling administrator, roles, and permission definitions are kept
        so that a reset never locks the active administrator out of the POS.
        """
        permissions = PermissionService()
        if not permissions.is_admin(user_id) or not permissions.has_permission(user_id, 'system.reset'):
            raise PermissionError('Only an authorized administrator can reset system data')
        selected = set(selections)
        if 'full' in selected:
            selected = set(self.ALL_OPTIONS)
        if not selected or not selected <= self.ALL_OPTIONS:
            raise ValueError('Select one or more valid data groups to reset')
        backup = self.backup()
        results = {'backup': backup, 'selected': sorted(selected)}
        with self.db.transaction() as conn:
            if 'inventory' in selected:
                results['inventory_import_items'] = self._delete(conn, 'inventory_import_items')
                results['inventory_imports'] = self._delete(conn, 'inventory_imports')
                results['quotation_items'] = self._delete(conn, 'quotation_items')
                results['return_items'] = self._delete(conn, 'return_items')
                results['sale_items'] = self._delete(conn, 'sale_items')
                results['stock_movements'] = self._delete(conn, 'stock_movements')
                results['product_tombstones'] = self._delete(conn, 'product_tombstones')
                # The normal product rule protects day-to-day history by
                # prohibiting physical deletes. A confirmed administrative
                # reset has already removed every dependent record, so it can
                # temporarily lift that rule inside this transaction.
                conn.execute('DROP TRIGGER IF EXISTS prevent_product_physical_delete')
                results['products'] = self._delete(conn, 'products')
                conn.execute("""CREATE TRIGGER prevent_product_physical_delete
                    BEFORE DELETE ON products BEGIN
                    SELECT RAISE(ABORT, 'Products must be archived, not physically deleted');
                    END""")
                results['categories'] = self._delete(conn, 'categories')
                results['vehicle_models'] = self._delete(conn, 'vehicle_models')
            if 'customers' in selected:
                # Transaction records retain their saved customer snapshot.
                conn.execute('UPDATE sales SET customer_id=NULL, vehicle_id=NULL')
                conn.execute('UPDATE invoices SET customer_id=NULL, vehicle_id=NULL')
                conn.execute('UPDATE returns SET customer_id=NULL, vehicle_id=NULL')
                conn.execute('UPDATE quotations SET vehicle_id=NULL')
                results['vehicles'] = self._delete(conn, 'vehicles')
                results['customers'] = self._delete(conn, 'customers')
            if 'returns' in selected:
                results['refunds'] = self._delete(conn, 'refunds')
                results['return_items'] = results.get('return_items', 0) + self._delete(conn, 'return_items')
                results['returns'] = self._delete(conn, 'returns')
            if 'sales_invoices' in selected:
                conn.execute('UPDATE quotations SET converted_sale_id=NULL')
                results['refunds'] = results.get('refunds', 0) + self._delete(conn, 'refunds')
                results['return_items'] = results.get('return_items', 0) + self._delete(conn, 'return_items')
                results['returns'] = results.get('returns', 0) + self._delete(conn, 'returns')
                results['invoices'] = self._delete(conn, 'invoices')
                results['payments'] = self._delete(conn, 'payments')
                results['sale_items'] = results.get('sale_items', 0) + self._delete(conn, 'sale_items')
                results['sales'] = self._delete(conn, 'sales')
                results['held_sales'] = self._delete(conn, 'held_sales')
            if 'quotations' in selected:
                results['quotation_items'] = results.get('quotation_items', 0) + self._delete(conn, 'quotation_items')
                results['quotations'] = self._delete(conn, 'quotations')
            if 'stock_movements' in selected and 'inventory' not in selected:
                results['stock_movements'] = self._delete(conn, 'stock_movements')
            if 'analytics' in selected or 'reports' in selected:
                results['sync_log'] = self._delete(conn, 'sync_log')
                results['sync_queue'] = self._delete(conn, 'sync_queue')
            if 'settings' in selected:
                results['settings'] = self._delete(conn, 'settings')
            if 'users' in selected:
                conn.execute('UPDATE sales SET user_id=?', (user_id,))
                conn.execute('UPDATE returns SET user_id=?, authorized_by=NULL', (user_id,))
                conn.execute('UPDATE invoices SET voided_by=NULL')
                conn.execute('UPDATE held_sales SET user_id=NULL')
                conn.execute('UPDATE quotations SET user_id=NULL')
                conn.execute('UPDATE inventory_imports SET imported_by=NULL')
                conn.execute('UPDATE stock_movements SET user_id=NULL')
                conn.execute('UPDATE audit_logs SET requesting_user_id=NULL, approving_user_id=NULL WHERE requesting_user_id != ? OR approving_user_id != ?', (user_id, user_id))
                results['user_permissions'] = self._delete(conn, 'user_permissions', 'user_id != ?', (user_id,))
                results['users'] = self._delete(conn, 'users', 'id != ?', (user_id,))
            if selected == self.ALL_OPTIONS:
                results['audit_logs'] = self._delete(conn, 'audit_logs')
        AuditService().log_action('SYSTEM_DATA_RESET', 'SYSTEM', None, user_id, details=f"Selected: {', '.join(sorted(selected))}; backup: {backup}; results: {results}")
        emit_change('SYSTEM_RESET', {'selected': sorted(selected), 'results': results})
        return results

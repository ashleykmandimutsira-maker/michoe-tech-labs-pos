"""
Audit logging service for tracking sensitive operations.
PHASE 2: Audit trail and compliance.
"""

import logging
from typing import Optional
from datetime import datetime

from database.db import get_database_manager
from models.user import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """Service for audit logging and compliance tracking."""

    def __init__(self):
        """Initialize audit service."""
        self.db = get_database_manager()

    def log_action(self, action: str, entity_type: Optional[str] = None, 
                  entity_id: Optional[int] = None, requesting_user_id: int = 0, 
                  reason: Optional[str] = None, details: Optional[str] = None,
                  approving_user_id: Optional[int] = None) -> int:
        """
        Log a general action.
        
        Args:
            action: Action performed (RETURN_CREATED, REFUND_PROCESSED, etc.)
            entity_type: Type of entity affected (RETURN, SALE, etc.)
            entity_id: ID of entity affected
            requesting_user_id: User performing the action
            reason: Reason for the action
            details: Additional details
            
        Returns:
            Audit log ID
        """
        query = """
            INSERT INTO audit_logs (action, entity_type, entity_id, requesting_user_id,
                                   approving_user_id, reason, details, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'COMPLETED')
        """
        
        try:
            params = (action, entity_type, entity_id, requesting_user_id, approving_user_id, reason, details)
            self.db.execute_update(query, params)
            log_id = self.db.get_last_insert_id()
            
            logger.info(
                f"Audit logged: {action} by user {requesting_user_id} "
                f"on {entity_type}#{entity_id}"
            )
            return log_id
        except Exception as e:
            logger.error(f"Failed to log audit: {e}")
            raise

    def log_authorization(self, requesting_user_id: int, approving_user_id: int,
                         action: str, entity_id: int, entity_type: Optional[str] = None,
                         reason: Optional[str] = None) -> int:
        """
        Log an authorization action (approval workflow).
        
        Args:
            requesting_user_id: User requesting the action
            approving_user_id: User approving the action
            action: Action being authorized
            entity_id: ID of entity being authorized
            entity_type: Type of entity
            reason: Reason for authorization
            
        Returns:
            Audit log ID
        """
        query = """
            INSERT INTO audit_logs (action, entity_type, entity_id, requesting_user_id, 
                                   approving_user_id, reason, status)
            VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED')
        """
        
        try:
            params = (
                f"AUTHORIZED_{action}",
                entity_type,
                entity_id,
                requesting_user_id,
                approving_user_id,
                reason,
            )
            self.db.execute_update(query, params)
            log_id = self.db.get_last_insert_id()
            
            logger.info(
                f"Authorization logged: {action} by user {requesting_user_id} "
                f"approved by {approving_user_id}"
            )
            return log_id
        except Exception as e:
            logger.error(f"Failed to log authorization: {e}")
            raise

    def log_return_creation(self, return_id: int, user_id: int, reason: str) -> int:
        """Log return creation."""
        return self.log_action(
            action='RETURN_CREATED',
            entity_type='RETURN',
            entity_id=return_id,
            requesting_user_id=user_id,
            reason=reason,
        )

    def log_return_approval(self, return_id: int, user_id: int, approved_by: int) -> int:
        """Log return approval."""
        return self.log_authorization(
            requesting_user_id=user_id,
            approving_user_id=approved_by,
            action='RETURN_APPROVAL',
            entity_id=return_id,
            entity_type='RETURN',
        )

    def log_refund_processing(self, return_id: int, refund_id: int, user_id: int, 
                            refund_amount: float, refund_method: str) -> int:
        """Log refund processing."""
        details = f"Refund ID: {refund_id}, Amount: {refund_amount}, Method: {refund_method}"
        return self.log_action(
            action='REFUND_PROCESSED',
            entity_type='RETURN',
            entity_id=return_id,
            requesting_user_id=user_id,
            details=details,
        )

    def log_sale_void(self, sale_id: int, invoice_number: str, user_id: int, 
                     reason: Optional[str] = None) -> int:
        """Log sale void."""
        return self.log_action(
            action='SALE_VOIDED',
            entity_type='SALE',
            entity_id=sale_id,
            requesting_user_id=user_id,
            reason=reason,
            details=f"Invoice: {invoice_number}",
        )

    def log_price_change(self, product_id: int, user_id: Optional[int], old_price: float, 
                        new_price: float, reason: Optional[str] = None) -> int:
        """Log price change."""
        details = f"Old price: {old_price}, New price: {new_price}"
        return self.log_action(
            action='PRICE_CHANGED',
            entity_type='PRODUCT',
            entity_id=product_id,
            requesting_user_id=user_id,
            reason=reason,
            details=details,
        )

    def log_product_archive(self, product_id: int, requesting_user_id: int,
                            approving_admin_id: int, reason: Optional[str] = None) -> int:
        """Record a product archive with both requester and approver."""
        query = """
            INSERT INTO audit_logs (action, entity_type, entity_id,
                                    requesting_user_id, approving_user_id,
                                    reason, status)
            VALUES ('PRODUCT_ARCHIVED', 'PRODUCT', ?, ?, ?, ?, 'COMPLETED')
        """
        self.db.execute_update(query, (product_id, requesting_user_id,
                                       approving_admin_id, reason))
        return self.db.get_last_insert_id()

    def log_product_restore(self, product_id: int, requesting_user_id: int,
                            approving_admin_id: int, reason: Optional[str] = None) -> int:
        """Record a product restore with both requester and approver."""
        query = """
            INSERT INTO audit_logs (action, entity_type, entity_id,
                                    requesting_user_id, approving_user_id,
                                    reason, status)
            VALUES ('PRODUCT_RESTORED', 'PRODUCT', ?, ?, ?, ?, 'COMPLETED')
        """
        self.db.execute_update(query, (product_id, requesting_user_id,
                                       approving_admin_id, reason))
        return self.db.get_last_insert_id()

    def log_user_creation(self, new_user_id: int, created_by_user_id: int) -> int:
        """Log user creation."""
        return self.log_action(
            action='USER_CREATED',
            entity_type='USER',
            entity_id=new_user_id,
            requesting_user_id=created_by_user_id,
        )

    def log_permission_grant(self, user_id: int, permission_id: int, 
                           granted_by_user_id: int, permission_code: str) -> int:
        """Log permission grant."""
        details = f"Permission: {permission_code}"
        return self.log_action(
            action='PERMISSION_GRANTED',
            entity_type='USER',
            entity_id=user_id,
            requesting_user_id=granted_by_user_id,
            details=details,
        )

    def log_system_setting_change(self, user_id: int, setting_name: str, 
                                 old_value: str, new_value: str) -> int:
        """Log system setting change."""
        details = f"Setting: {setting_name}, Old: {old_value}, New: {new_value}"
        return self.log_action(
            action='SYSTEM_SETTING_CHANGED',
            entity_type='SETTING',
            requesting_user_id=user_id,
            details=details,
        )

    def get_audit_log(self, log_id: int) -> Optional[AuditLog]:
        """Get audit log entry by ID."""
        query = "SELECT * FROM audit_logs WHERE id = ?"
        results = self.db.execute_query(query, (log_id,))
        
        if not results:
            return None
        
        return self._row_to_audit_log(results[0])

    def get_action_history(self, entity_type: str, entity_id: int, limit: int = 50) -> list:
        """
        Get audit history for an entity.
        
        Args:
            entity_type: Type of entity (RETURN, SALE, PRODUCT, etc.)
            entity_id: ID of entity
            limit: Maximum number of entries
            
        Returns:
            List of audit log entries
        """
        query = """
            SELECT * FROM audit_logs 
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        
        results = self.db.execute_query(query, (entity_type, entity_id, limit))
        return [self._row_to_audit_log(row) for row in results]

    def get_user_activity(self, user_id: int, limit: int = 50) -> list:
        """
        Get activity log for a user.
        
        Args:
            user_id: User ID
            limit: Maximum number of entries
            
        Returns:
            List of audit log entries
        """
        query = """
            SELECT * FROM audit_logs 
            WHERE requesting_user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        
        results = self.db.execute_query(query, (user_id, limit))
        return [self._row_to_audit_log(row) for row in results]

    def get_sensitive_actions(self, limit: int = 100) -> list:
        """
        Get all sensitive actions (approvals, deletions, voids, etc.).
        
        Args:
            limit: Maximum number of entries
            
        Returns:
            List of sensitive audit log entries
        """
        sensitive_actions = [
            'AUTHORIZED_%', 'DELETED_%', 'VOIDED', 'PERMISSION_GRANTED', 
            'SYSTEM_SETTING_CHANGED', 'USER_CREATED'
        ]
        
        placeholders = ','.join(['?' for _ in sensitive_actions])
        
        query = f"""
            SELECT * FROM audit_logs 
            WHERE {' OR '.join([f'action LIKE ?' for _ in sensitive_actions])}
            ORDER BY created_at DESC
            LIMIT ?
        """
        
        results = self.db.execute_query(query, sensitive_actions + [limit])
        return [self._row_to_audit_log(row) for row in results]

    def search_audit_logs(self, search_term: str, limit: int = 100) -> list:
        """Search audit logs by action, reason, or details."""
        query = """
            SELECT * FROM audit_logs 
            WHERE action LIKE ? OR reason LIKE ? OR details LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        
        pattern = f"%{search_term}%"
        results = self.db.execute_query(query, (pattern, pattern, pattern, limit))
        return [self._row_to_audit_log(row) for row in results]

    @staticmethod
    def _row_to_audit_log(row) -> AuditLog:
        """Convert database row to AuditLog object."""
        return AuditLog(
            id=row['id'],
            action=row['action'],
            entity_type=row['entity_type'],
            entity_id=row['entity_id'],
            requesting_user_id=row['requesting_user_id'],
            approving_user_id=row['approving_user_id'],
            reason=row['reason'],
            details=row['details'],
            status=row['status'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
        )

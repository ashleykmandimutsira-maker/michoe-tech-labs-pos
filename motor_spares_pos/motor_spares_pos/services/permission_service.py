"""
Permission checking and authorization service.
PHASE 2: Permissions and authorization.
"""

import logging
from typing import Optional, List

from database.db import get_database_manager
from models.user import Permission

logger = logging.getLogger(__name__)


class PermissionService:
    """Service for permission checking and authorization."""

    # Define permission requirements for sensitive operations
    PERMISSION_REQUIREMENTS = {
        'CREATE_RETURN': ['CREATE_RETURN'],
        'APPROVE_RETURN': ['APPROVE_RETURN'],
        'PROCESS_REFUND': ['PROCESS_REFUND'],
        'PROCESS_CASH_REFUND': ['PROCESS_CASH_REFUND'],
        'PROCESS_LARGE_REFUND': ['PROCESS_LARGE_REFUND'],  # Over 500 USD
        'PROCESS_EXCHANGE': ['PROCESS_EXCHANGE'],
        'VOID_RETURN': ['VOID_RETURN'],
        'VOID_SALE': ['VOID_SALE'],
        'CHANGE_PRICE': ['CHANGE_PRICE'],
        'DELETE_PRODUCT': ['DELETE_PRODUCT'],
        'RESTORE_PRODUCT': ['RESTORE_PRODUCT'],
        'MANAGE_USERS': ['MANAGE_USERS'],
    }

    def __init__(self):
        """Initialize permission service."""
        self.db = get_database_manager()

    def has_permission(self, user_id: int, permission_code: str) -> bool:
        """
        Check if a user has a specific permission.
        
        Args:
            user_id: User ID
            permission_code: Permission code to check
            
        Returns:
            True if user has permission
        """
        query = """
            SELECT COUNT(*) as count FROM user_permissions up
            INNER JOIN permissions p ON up.permission_id = p.id
            WHERE up.user_id = ? AND p.code = ?
        """
        
        results = self.db.execute_query(query, (user_id, permission_code))
        if results:
            return results[0]['count'] > 0
        return False

    def has_any_permission(self, user_id: int, permission_codes: List[str]) -> bool:
        """
        Check if user has any of the specified permissions.
        
        Args:
            user_id: User ID
            permission_codes: List of permission codes
            
        Returns:
            True if user has any of the permissions
        """
        return any(self.has_permission(user_id, code) for code in permission_codes)

    def has_all_permissions(self, user_id: int, permission_codes: List[str]) -> bool:
        """
        Check if user has all specified permissions.
        
        Args:
            user_id: User ID
            permission_codes: List of permission codes
            
        Returns:
            True if user has all permissions
        """
        return all(self.has_permission(user_id, code) for code in permission_codes)

    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin."""
        query = """
            SELECT r.name FROM users u
            INNER JOIN roles r ON u.role_id = r.id
            WHERE u.id = ? AND u.is_active = 1
        """
        
        results = self.db.execute_query(query, (user_id,))
        if results:
            return results[0]['name'] == 'ADMIN'
        return False

    def is_manager(self, user_id: int) -> bool:
        """Check if user is a manager."""
        query = """
            SELECT r.name FROM users u
            INNER JOIN roles r ON u.role_id = r.id
            WHERE u.id = ? AND u.is_active = 1
        """
        
        results = self.db.execute_query(query, (user_id,))
        if results:
            return results[0]['name'] == 'MANAGER'
        return False

    def can_archive_product(self, user_id: int) -> bool:
        """Only an active ADMIN with the explicit permission may archive."""
        return self.is_admin(user_id) and self.has_permission(user_id, 'DELETE_PRODUCT')

    def can_restore_product(self, user_id: int) -> bool:
        """Only an active ADMIN with the explicit permission may restore."""
        return self.is_admin(user_id) and self.has_permission(user_id, 'RESTORE_PRODUCT')

    def check_permission_or_raise(self, user_id: int, permission_code: str):
        """
        Check permission and raise exception if not permitted.
        
        Args:
            user_id: User ID
            permission_code: Permission code
            
        Raises:
            PermissionError if user doesn't have permission
        """
        if not self.has_permission(user_id, permission_code):
            raise PermissionError(
                f"User {user_id} does not have permission: {permission_code}"
            )

    def check_operation_allowed(self, user_id: int, operation: str) -> bool:
        """
        Check if an operation is allowed for a user.
        
        Args:
            user_id: User ID
            operation: Operation code
            
        Returns:
            True if operation is allowed
        """
        # Product archive/restore are deliberately ADMIN-only even if an
        # explicit permission was manually granted to another role.
        if operation == 'DELETE_PRODUCT':
            return self.can_archive_product(user_id)
        if operation == 'RESTORE_PRODUCT':
            return self.can_restore_product(user_id)
        required_perms = self.PERMISSION_REQUIREMENTS.get(operation, [])
        if not required_perms:
            # If operation not in requirements, allow it
            return True
        
        return self.has_any_permission(user_id, required_perms)

    def get_all_permissions(self) -> List[Permission]:
        """Get all available permissions in the system."""
        query = "SELECT * FROM permissions ORDER BY category, code"
        results = self.db.execute_query(query)
        
        permissions = []
        for row in results:
            perm = Permission(
                id=row['id'],
                code=row['code'],
                description=row['description'],
                category=row['category'],
            )
            permissions.append(perm)
        
        return permissions

    def get_role_permissions(self, role_id: int) -> List[Permission]:
        """Get permissions materialized for users assigned to a role."""
        query = """
            SELECT DISTINCT p.* FROM permissions p
            INNER JOIN user_permissions up ON p.id = up.permission_id
            INNER JOIN users u ON u.id = up.user_id
            WHERE u.role_id = ?
            ORDER BY p.category, p.code
        """
        
        results = self.db.execute_query(query, (role_id,))
        
        permissions = []
        for row in results:
            perm = Permission(
                id=row['id'],
                code=row['code'],
                description=row['description'],
                category=row['category'],
            )
            permissions.append(perm)
        
        return permissions

    def grant_role_permission(self, role_id: int, permission_id: int) -> bool:
        """Grant a permission to a role."""
        query = """
            INSERT OR IGNORE INTO user_permissions (user_id, permission_id)
            SELECT u.id, ? FROM users u WHERE u.role_id = ?
        """
        
        try:
            self.db.execute_update(query, (permission_id, role_id))
            logger.info(f"Permission {permission_id} granted to role {role_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to grant role permission: {e}")
            return False

    def revoke_role_permission(self, role_id: int, permission_id: int) -> bool:
        """Revoke a permission from a role."""
        query = """
            DELETE FROM user_permissions
            WHERE permission_id = ? AND user_id IN (SELECT id FROM users WHERE role_id = ?)
        """
        
        try:
            self.db.execute_update(query, (permission_id, role_id))
            logger.info(f"Permission {permission_id} revoked from role {role_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to revoke role permission: {e}")
            return False

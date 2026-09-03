"""
Authentication and user management service.
PHASE 2: User authentication.
"""

import logging
from typing import Optional, List
from datetime import datetime

from types import ModuleType
bcrypt: Optional[ModuleType] = None
try:
    import bcrypt as _bcrypt
    bcrypt = _bcrypt
except ImportError:
    bcrypt = None

from database.db import get_database_manager
from models.user import User, Role, Permission, AuditLog
from services.audit_service import AuditService

logger = logging.getLogger(__name__)


class AuthenticationService:
    """Service for user authentication and management."""

    def __init__(self):
        """Initialize authentication service."""
        self.db = get_database_manager()
        
        if bcrypt is None:
            logger.warning("bcrypt not installed - password hashing unavailable")

    def hash_password(self, password: str) -> str:
        """
        Hash a password securely using bcrypt.
        
        Args:
            password: Plain text password
            
        Returns:
            Bcrypt hashed password
        """
        if not bcrypt:
            logger.error("bcrypt not installed - cannot hash password")
            raise RuntimeError("Password hashing library not available")
        
        # Use salt rounds of 12 for security
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def verify_password(self, password: str, password_hash: str) -> bool:
        """
        Verify a password against its hash.
        
        Args:
            password: Plain text password to verify
            password_hash: Bcrypt hash to verify against
            
        Returns:
            True if password matches, False otherwise
        """
        if not bcrypt:
            logger.error("bcrypt not installed - cannot verify password")
            return False
        
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False

    def authenticate(self, username: str, password: str) -> Optional[User]:
        """
        Authenticate a user and return user object with permissions.
        
        Args:
            username: Username
            password: Password (plain text)
            
        Returns:
            User object if authentication successful, None otherwise
        """
        try:
            # Get user by username
            user = self.get_user_by_username(username)
            if not user:
                logger.warning(f"Login attempt for non-existent user: {username}")
                return None
            
            # Check if account is active
            if not user.is_active:
                logger.warning(f"Login attempt for inactive user: {username}")
                return None
            
            # Verify password
            if not self.verify_password(password, user.password_hash):
                logger.warning(f"Failed login attempt for user: {username}")
                return None
            
            # Update last login time
            self.update_last_login(user.id)
            
            # Load permissions
            user.permissions = self.get_user_permissions(user.id)
            AuditService().log_action('LOGIN', 'USER', user.id, user.id, details='Successful authentication')
            
            logger.info(f"User authenticated: {username}")
            return user
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None

    def create_user(
        self,
        username: str,
        password: str,
        full_name: str,
        role_id: int,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> int:
        """
        Create a new user.
        
        Args:
            username: Unique username
            password: Plain text password (will be hashed)
            full_name: User's full name
            role_id: Role ID
            email: User email
            phone: User phone
            
        Returns:
            User ID of created user
        """
        # Check if username exists
        existing = self.get_user_by_username(username)
        if existing:
            raise ValueError(f"Username already exists: {username}")
        
        # Hash password
        password_hash = self.hash_password(password)
        
        query = """
            INSERT INTO users (username, password_hash, full_name, email, phone, role_id, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """
        
        params = (username, password_hash, full_name, email, phone, role_id)
        
        try:
            self.db.execute_update(query, params)
            user_id = self.db.get_last_insert_id()
            self._assign_default_role_permissions(user_id, role_id)
            logger.info(f"Created user: {username} (ID: {user_id})")
            return user_id
        except Exception as e:
            logger.error(f"Failed to create user: {e}")
            raise

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID with role and permissions."""
        query = """
            SELECT u.*, r.id as role_id, r.name as role_name, r.description as role_desc
            FROM users u
            LEFT JOIN roles r ON u.role_id = r.id
            WHERE u.id = ?
        """
        
        results = self.db.execute_query(query, (user_id,))
        if not results:
            return None
        
        return self._row_to_user(results[0])

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        query = """
            SELECT u.*, r.id as role_id, r.name as role_name, r.description as role_desc
            FROM users u
            LEFT JOIN roles r ON u.role_id = r.id
            WHERE u.username = ?
        """
        
        results = self.db.execute_query(query, (username,))
        if not results:
            return None
        
        return self._row_to_user(results[0])

    def get_all_roles(self) -> List[Role]:
        """Return all configured roles for the admin role-management UI."""
        rows = self.db.execute_query(
            "SELECT * FROM roles ORDER BY CASE name WHEN 'ADMIN' THEN 1 WHEN 'MANAGER' THEN 2 WHEN 'CASHIER' THEN 3 WHEN 'STOCK_CLERK' THEN 4 ELSE 5 END, name"
        )
        return [
            Role(
                id=row['id'],
                name=row['name'],
                description=row['description'] or '',
                created_at=row['created_at'],
                updated_at=row['updated_at'],
            )
            for row in rows
        ]

    def change_user_role(self, admin_user_id: int, target_user_id: int, role_id: int) -> bool:
        """Change another user's role, then add the new role's baseline privileges.

        Only an active administrator with MANAGE_PERMISSIONS may change roles.
        The currently logged-in administrator cannot change their own role here.
        Existing direct privileges are preserved so an admin can fine-tune them
        afterwards, except protected product archive/restore privileges remain
        ADMIN-only by policy.
        """
        admin = self.get_user_by_id(admin_user_id)
        target = self.get_user_by_id(target_user_id)
        role = self.db.execute_query("SELECT id, name FROM roles WHERE id = ?", (role_id,))
        if not admin or not admin.is_active or not admin.is_admin():
            raise PermissionError("Only an active ADMIN can change user roles.")
        if not self._db_user_has_permission(admin_user_id, 'MANAGE_PERMISSIONS'):
            raise PermissionError("Administrator does not have MANAGE_PERMISSIONS.")
        if not target:
            raise ValueError("Target user was not found.")
        if admin_user_id == target_user_id:
            raise ValueError("Do not change the currently logged-in administrator's role.")
        if not role:
            raise ValueError("Target role was not found.")

        self.db.execute_update(
            "UPDATE users SET role_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (role_id, target_user_id),
        )

        # A role change defines a new baseline. Clear the previous direct
        # permission set first so a downgrade (for example MANAGER -> CASHIER)
        # cannot accidentally retain elevated privileges. The admin can then
        # grant any additional allowed privileges from Manage privileges.
        self.db.execute_update("DELETE FROM user_permissions WHERE user_id = ?", (target_user_id,))
        self._assign_default_role_permissions(target_user_id, role_id)

        # Product archive/restore remain ADMIN-only regardless of the role editor.
        if role[0]['name'] != 'ADMIN':
            protected = self.db.execute_query(
                "SELECT id FROM permissions WHERE code IN ('DELETE_PRODUCT','RESTORE_PRODUCT')"
            )
            for permission in protected:
                self.revoke_permission(target_user_id, permission['id'])

        AuditService().log_action(
            'ROLE_CHANGED', 'USER', target_user_id, admin_user_id,
            details=f"Role changed to {role[0]['name']}"
        )
        logger.info("Changed role for user %s to %s by admin %s", target_user_id, role[0]['name'], admin_user_id)
        return True

    def logout(self, user_id: int) -> None:
        """Record the end of a user session without changing application state."""
        AuditService().log_action('LOGOUT', 'USER', user_id, user_id, details='User session ended')

    def get_all_users(self, active_only: bool = False) -> List[User]:
        """Get all users."""
        if active_only:
            query = """
                SELECT u.*, r.id as role_id, r.name as role_name, r.description as role_desc
                FROM users u
                LEFT JOIN roles r ON u.role_id = r.id
                WHERE u.is_active = 1
                ORDER BY u.full_name
            """
        else:
            query = """
                SELECT u.*, r.id as role_id, r.name as role_name, r.description as role_desc
                FROM users u
                LEFT JOIN roles r ON u.role_id = r.id
                ORDER BY u.full_name
            """
        
        results = self.db.execute_query(query)
        return [self._row_to_user(row) for row in results]

    def change_password(self, user_id: int, old_password: str, new_password: str) -> bool:
        """
        Change user password.
        
        Args:
            user_id: User ID
            old_password: Current password (verified)
            new_password: New password
            
        Returns:
            True if successful
        """
        # Get user
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"User not found: {user_id}")
        
        # Verify old password
        if not self.verify_password(old_password, user.password_hash):
            raise ValueError("Current password is incorrect")
        
        # Hash new password
        new_hash = self.hash_password(new_password)
        
        # Update
        query = "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
        self.db.execute_update(query, (new_hash, user_id))
        
        logger.info(f"Password changed for user: {user.username}")
        return True

    def deactivate_user(self, user_id: int) -> bool:
        """Deactivate a user account."""
        query = "UPDATE users SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
        self.db.execute_update(query, (user_id,))
        logger.info(f"User deactivated: ID {user_id}")
        return True

    def delete_user(self, admin_user_id: int, target_user_id: int, reason: str) -> bool:
        """Remove a user's access while preserving historical user references."""
        admin = self.get_user_by_id(admin_user_id)
        target = self.get_user_by_id(target_user_id)
        if not admin or not admin.is_active or not admin.is_admin():
            raise PermissionError("Only an active administrator can delete users.")
        if not self._db_user_has_permission(admin_user_id, 'MANAGE_USERS'):
            raise PermissionError("Administrator does not have MANAGE_USERS.")
        if not target:
            raise ValueError("Target user was not found.")
        if admin_user_id == target_user_id:
            raise ValueError("The currently logged-in administrator cannot be deleted.")
        if not reason or not reason.strip():
            raise ValueError("A reason is required to delete a user.")
        with self.db.transaction() as conn:
            changed = conn.execute(
                "UPDATE users SET is_active=0, updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_active=1",
                (target_user_id,),
            ).rowcount
            conn.execute("DELETE FROM user_permissions WHERE user_id=?", (target_user_id,))
        if not changed:
            raise ValueError("User is already inactive.")
        AuditService().log_action(
            'USER_DELETED', 'USER', target_user_id, admin_user_id,
            reason=reason.strip(), details=f'Access disabled for {target.username}; historical records preserved.'
        )
        logger.info("User access deleted: %s by administrator %s", target.username, admin_user_id)
        return True

    def activate_user(self, user_id: int) -> bool:
        """Activate a user account."""
        query = "UPDATE users SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
        self.db.execute_update(query, (user_id,))
        logger.info(f"User activated: ID {user_id}")
        return True

    def get_user_permissions(self, user_id: Optional[int]) -> List[Permission]:
        """Get all permissions for a user."""
        query = """
            SELECT p.* FROM permissions p
            INNER JOIN user_permissions up ON p.id = up.permission_id
            WHERE up.user_id = ?
            ORDER BY p.category, p.code
        """
        
        if user_id is None:
            return []
        results = self.db.execute_query(query, (user_id,))
        return [self._row_to_permission(row) for row in results]

    DEFAULT_ROLE_PERMISSIONS = {
        'ADMIN': '*',
        'MANAGER': {
            'MAKE_SALE', 'VIEW_SALES', 'VIEW_REPORTS', 'VIEW_PROFIT', 'VIEW_INVENTORY',
            'CREATE_PRODUCT', 'EDIT_PRODUCT', 'ADD_STOCK', 'ADJUST_STOCK', 'CHANGE_PRICE',
            'CREATE_RETURN', 'APPROVE_RETURN', 'PROCESS_REFUND', 'PROCESS_CASH_REFUND',
            'PROCESS_EXCHANGE', 'VOID_SALE'
            , 'customers.view', 'customers.create', 'customers.edit', 'vehicles.view', 'vehicles.create', 'vehicles.edit', 'quotations.view', 'quotations.create', 'quotations.edit', 'quotations.print', 'quotations.convert', 'invoices.view', 'invoices.print', 'invoices.reprint'
        },
        'CASHIER': {'MAKE_SALE', 'VIEW_SALES', 'CREATE_RETURN', 'customers.view', 'customers.create', 'vehicles.view', 'vehicles.create', 'quotations.view', 'quotations.create', 'quotations.print', 'quotations.convert', 'invoices.view', 'invoices.print', 'invoices.reprint'},
        'STOCK_CLERK': {'VIEW_INVENTORY', 'CREATE_PRODUCT', 'EDIT_PRODUCT', 'ADD_STOCK', 'ADJUST_STOCK', 'customers.view', 'vehicles.view'},
    }

    def _assign_default_role_permissions(self, user_id: int, role_id: int) -> None:
        role_rows = self.db.execute_query("SELECT name FROM roles WHERE id = ?", (role_id,))
        if not role_rows:
            return
        role_name = role_rows[0]['name']
        desired = self.DEFAULT_ROLE_PERMISSIONS.get(role_name, set())
        if desired == '*':
            rows = self.db.execute_query("SELECT id FROM permissions")
        else:
            placeholders = ','.join('?' for _ in desired)
            rows = self.db.execute_query(
                f"SELECT id FROM permissions WHERE code IN ({placeholders})", tuple(desired)
            ) if desired else []
        for row in rows:
            self.grant_permission(user_id, row['id'], None)

    def set_user_permissions(self, admin_user_id: int, target_user_id: int, permission_codes: List[str]) -> dict:
        """Replace a user's direct privileges. Only an active ADMIN with MANAGE_PERMISSIONS may do this."""
        admin = self.get_user_by_id(admin_user_id)
        target = self.get_user_by_id(target_user_id)
        if not admin or not admin.is_active or not admin.is_admin():
            raise PermissionError("Only an active ADMIN can manage user privileges.")
        if not self._db_user_has_permission(admin_user_id, 'MANAGE_PERMISSIONS'):
            raise PermissionError("Administrator does not have MANAGE_PERMISSIONS.")
        if not target:
            raise ValueError("Target user was not found.")
        if admin_user_id == target_user_id:
            raise ValueError("Do not remove or replace the currently logged-in administrator's privileges.")

        requested = {code.strip().upper() for code in permission_codes if code and code.strip()}
        all_rows = self.db.execute_query("SELECT id, code FROM permissions")
        known = {row['code']: row['id'] for row in all_rows}
        invalid = requested - set(known)
        if invalid:
            raise ValueError("Unknown permissions: " + ', '.join(sorted(invalid)))

        # Product archive/restore remain ADMIN-only even if an administrator can edit other permissions.
        if target.role and target.role.name != 'ADMIN':
            requested.discard('DELETE_PRODUCT')
            requested.discard('RESTORE_PRODUCT')

        current_rows = self.db.execute_query(
            "SELECT p.code, p.id FROM user_permissions up JOIN permissions p ON p.id = up.permission_id WHERE up.user_id = ?",
            (target_user_id,),
        )
        current = {row['code']: row['id'] for row in current_rows}
        changed: dict[str, list[str]] = {'granted': [], 'revoked': []}

        for code in sorted(requested - set(current)):
            self.grant_permission(target_user_id, known[code], admin_user_id)
            AuditService().log_permission_grant(target_user_id, known[code], admin_user_id, code)
            changed['granted'].append(code)

        for code in sorted(set(current) - requested):
            if code in ('DELETE_PRODUCT', 'RESTORE_PRODUCT') and target.role and target.role.name != 'ADMIN':
                continue
            self.revoke_permission(target_user_id, current[code])
            AuditService().log_action(
                'PERMISSION_REVOKED', 'USER', target_user_id, admin_user_id,
                details=f'Permission: {code}'
            )
            changed['revoked'].append(code)
        return changed

    def _db_user_has_permission(self, user_id: int, code: str) -> bool:
        rows = self.db.execute_query(
            "SELECT 1 FROM user_permissions up JOIN permissions p ON p.id=up.permission_id WHERE up.user_id=? AND p.code=? LIMIT 1",
            (user_id, code),
        )
        return bool(rows)

    def grant_permission(self, user_id: int, permission_id: int, granted_by: Optional[int] = None) -> bool:
        """Grant a permission to a user."""
        query = """
            INSERT OR IGNORE INTO user_permissions (user_id, permission_id, granted_by)
            VALUES (?, ?, ?)
        """
        
        try:
            self.db.execute_update(query, (user_id, permission_id, granted_by))
            logger.info(f"Permission granted to user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to grant permission: {e}")
            return False

    def revoke_permission(self, user_id: int, permission_id: int) -> bool:
        """Revoke a permission from a user."""
        query = "DELETE FROM user_permissions WHERE user_id = ? AND permission_id = ?"
        
        try:
            self.db.execute_update(query, (user_id, permission_id))
            logger.info(f"Permission revoked from user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to revoke permission: {e}")
            return False

    def update_last_login(self, user_id: Optional[int]):
        """Update last login timestamp."""
        if user_id is None:
            return
        query = "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?"
        try:
            self.db.execute_update(query, (user_id,))
        except Exception as e:
            logger.error(f"Failed to update last login: {e}")

    @staticmethod
    def _row_to_user(row) -> User:
        """Convert database row to User object."""
        return User(
            id=row['id'],
            username=row['username'],
            password_hash=row['password_hash'],
            email=row['email'],
            full_name=row['full_name'],
            phone=row['phone'],
            role_id=row['role_id'],
            role=Role(
                id=row['role_id'],
                name=row['role_name'],
                description=row['role_desc'],
            ) if row['role_id'] else None,
            is_active=bool(row['is_active']),
            last_login=datetime.fromisoformat(row['last_login']) if row['last_login'] else None,
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
        )

    @staticmethod
    def _row_to_permission(row) -> Permission:
        """Convert database row to Permission object."""
        return Permission(
            id=row['id'],
            code=row['code'],
            description=row['description'],
            category=row['category'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
        )

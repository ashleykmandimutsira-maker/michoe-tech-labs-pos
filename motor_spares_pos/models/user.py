"""
User, role, and permission models for Motor Spares POS.
PHASE 2: Authentication and authorization.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class Permission:
    """Permission that can be granted to users."""

    id: Optional[int] = None
    code: str = ""
    description: str = ""
    category: str = ""
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "description": self.description,
            "category": self.category,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }


@dataclass
class Role:
    """User role (ADMIN, MANAGER, CASHIER, STOCK_CLERK)."""

    id: Optional[int] = None
    name: str = ""
    description: str = ""
    permissions: List[Permission] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permissions": [p.to_dict() for p in self.permissions],
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }


@dataclass
class User:
    """
    System user with role and permissions.

    Attributes:
        id: User ID (auto-generated)
        username: Unique username for login
        password_hash: Bcrypt hashed password (NEVER store plaintext)
        email: User email address
        full_name: Full name of user
        phone: Contact phone number
        role_id: Foreign key to role
        role: Role object (populated on demand)
        permissions: List of Permission objects
        is_active: Is user account active
        last_login: Last login timestamp
        created_at: Account creation time
        updated_at: Last update time
    """

    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""
    email: Optional[str] = None
    full_name: str = ""
    phone: Optional[str] = None
    role_id: Optional[int] = None
    role: Optional[Role] = None
    permissions: List[Permission] = field(default_factory=list)
    is_active: bool = True
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def has_permission(self, permission_code: str) -> bool:
        """Check if user has a specific permission."""
        return any(p.code == permission_code for p in self.permissions)

    def has_any_permission(self, permission_codes: List[str]) -> bool:
        """Check if user has any of the specified permissions."""
        return any(self.has_permission(code) for code in permission_codes)

    def has_all_permissions(self, permission_codes: List[str]) -> bool:
        """Check if user has all specified permissions."""
        return all(self.has_permission(code) for code in permission_codes)

    def is_admin(self) -> bool:
        """Check if user is an administrator."""
        return self.role is not None and self.role.name == "ADMIN"

    def is_manager(self) -> bool:
        """Check if user is a manager."""
        return self.role is not None and self.role.name == "MANAGER"

    def is_cashier(self) -> bool:
        """Check if user is a cashier."""
        return self.role is not None and self.role.name == "CASHIER"

    def is_stock_clerk(self) -> bool:
        """Check if user is a stock clerk."""
        return self.role is not None and self.role.name == "STOCK_CLERK"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization (excluding password hash)."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "phone": self.phone,
            "role_id": self.role_id,
            "role": self.role.to_dict() if self.role else None,
            "permissions": [p.to_dict() for p in self.permissions],
            "is_active": self.is_active,
            "last_login": (
                self.last_login.isoformat() if self.last_login else None
            ),
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }


@dataclass
class AuditLog:
    """
    Audit log entry for sensitive actions.
    Tracks who did what, when, and with what authorization.
    """

    id: Optional[int] = None
    action: str = ""
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    requesting_user_id: int = 0
    approving_user_id: Optional[int] = None
    reason: Optional[str] = None
    details: Optional[str] = None
    status: str = "COMPLETED"
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "requesting_user_id": self.requesting_user_id,
            "approving_user_id": self.approving_user_id,
            "reason": self.reason,
            "details": self.details,
            "status": self.status,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }

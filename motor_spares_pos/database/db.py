"""
Database connection and initialization module.
Handles SQLite database creation, migrations, and connection pooling.
"""

import sqlite3
import logging
import os
import threading
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, Optional

from database.schema import get_schema, get_initialization_sql
from core.clock import now_str

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

#CANONICAL_DATABASE_PATH = Path(__file__).resolve().parents[3] / "data" / "pos.db"
CANONICAL_DATABASE_PATH = (
    Path(os.getenv("LOCALAPPDATA", Path.home()))
    / "MichoeTechLabsPOS"
    / "data"
    / "pos.db"
)

class DatabaseManager:
    """Manages SQLite database connections and initialization."""

    def __init__(self, db_path: str = "data/pos.db"):
        """
        Initialize the database manager.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = str(Path(db_path).expanduser().resolve())
        self._ensure_directory_exists()
        self._initialized = False
        self._last_insert_id = threading.local()
        logger.info("Using SQLite database: %s", self.db_path)

    def _ensure_directory_exists(self) -> None:
        """Ensure the database directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            Path(db_dir).mkdir(parents=True, exist_ok=True)
            logger.info(f"Created database directory: {db_dir}")

    @staticmethod
    def _localize_timestamps(query: str) -> str:
        """Rewrite the bare CURRENT_TIMESTAMP keyword to the PC's local time.

        SQLite's built-in CURRENT_TIMESTAMP is always UTC. Every timestamp
        this POS records should reflect the machine's own clock instead, so
        any query text containing the literal keyword gets it replaced with
        the actual local time before it reaches SQLite. This runs centrally
        here so every service automatically gets consistent, local-time
        timestamps without each query having to know about it.
        """
        if "CURRENT_TIMESTAMP" in query:
            query = query.replace("CURRENT_TIMESTAMP", f"'{now_str()}'")
        return query

    @staticmethod
    def local_now_str() -> str:
        """Current local time formatted the way this database stores it."""
        return now_str()

    def get_connection(self) -> sqlite3.Connection:
        """
        Get a new SQLite database connection.
        
        Returns:
            sqlite3.Connection: Database connection with row factory
        """
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def get_db(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.
        
        Yields:
            sqlite3.Connection: Database connection
            
        Usage:
            with db_manager.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM products")
        """
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Run several statements atomically on one SQLite connection."""
        with self.get_db() as conn:
            conn.execute("BEGIN")
            yield conn

    def initialize(self) -> None:
        """
        Initialize the database with schema.
        Creates all tables if they don't exist.
        Also initializes default roles and permissions.
        """
        if self._initialized:
            return

        try:
            with self.get_db() as conn:
                cursor = conn.cursor()
                schema_sql = get_schema()
                cursor.executescript(schema_sql)
                logger.info("Database schema initialized successfully")
                
                # Initialize default roles and permissions
                init_sql = get_initialization_sql()
                cursor.executescript(init_sql)
                logger.info("Default roles and permissions initialized")
                self._apply_phase2_migrations(cursor)
                self._apply_phase3_migrations(cursor)
                self._apply_phase4_migrations(cursor)
                self._apply_phase5_migrations(cursor)
                self._apply_phase6_migrations(cursor)
                self._apply_phase7_migrations(cursor)
                self._record_migration(cursor, 1)
                
                self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def execute_query(
        self, query: str, params: tuple = None
    ) -> list[sqlite3.Row]:
        """
        Execute a SELECT query and return results.
        
        Args:
            query: SQL query string
            params: Query parameters
            
        Returns:
            list of sqlite3.Row objects
        """
        query = self._localize_timestamps(query)
        with self.get_db() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()

    def execute_update(
        self, query: str, params: tuple = None
    ) -> int:
        """
        Execute an INSERT/UPDATE/DELETE query.
        
        Args:
            query: SQL query string
            params: Query parameters
            
        Returns:
            Number of affected rows
        """
        query = self._localize_timestamps(query)
        with self.get_db() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            self._last_insert_id.value = cursor.lastrowid
            return cursor.rowcount

    def execute_many(
        self, query: str, params_list: list[tuple]
    ) -> int:
        """
        Execute multiple INSERT/UPDATE/DELETE queries.
        
        Args:
            query: SQL query string
            params_list: List of parameter tuples
            
        Returns:
            Number of affected rows
        """
        query = self._localize_timestamps(query)
        with self.get_db() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            return cursor.rowcount

    def close(self) -> None:
        """Close database connection."""
        # SQLite connections are closed in context managers
        logger.info("Database connections closed")

    def get_last_insert_id(self) -> int:
        """
        Get the ID of the last inserted row.
        
        Returns:
            Last insert rowid
        """
        insert_id = getattr(self._last_insert_id, "value", None)
        if insert_id is None:
            raise RuntimeError("No insert has been executed in this database manager")
        return insert_id

    @staticmethod
    def _apply_phase2_migrations(cursor: sqlite3.Cursor) -> None:
        """Add Phase 2 columns safely when opening an existing database."""
        additions = {
            "products": {"oem_number": "TEXT", "vehicle_year_from": "INTEGER", "vehicle_year_to": "INTEGER"},
            "sales": {"customer_name": "TEXT", "customer_phone": "TEXT", "customer_email": "TEXT", "customer_city": "TEXT", "vehicle_make": "TEXT", "vehicle_model": "TEXT", "vehicle_registration": "TEXT", "cashier_name": "TEXT"},
            "returns": {"original_invoice_number": "TEXT", "customer_name": "TEXT", "customer_phone": "TEXT"},
            "sync_queue": {"synced_at": "TIMESTAMP", "retry_count": "INTEGER DEFAULT 0"},
            "sync_log": {"queue_id": "INTEGER", "success": "BOOLEAN", "server_response": "TEXT"},
            "customers": {"email": "TEXT", "city": "TEXT", "vehicle_make": "TEXT", "vehicle_model": "TEXT", "vehicle_registration": "TEXT"},
            "invoices": {"customer_id": "INTEGER", "customer_email": "TEXT", "customer_city": "TEXT", "vehicle_make": "TEXT", "vehicle_model": "TEXT", "vehicle_registration": "TEXT"},
        }
        for table, columns in additions.items():
            existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_oem_number ON products(oem_number)")
                cursor.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)")

        cursor.execute(
            "UPDATE returns SET original_invoice_id = "
            "(SELECT id FROM invoices WHERE invoices.invoice_number = returns.original_invoice_number) "
            "WHERE original_invoice_number IS NOT NULL AND EXISTS "
            "(SELECT 1 FROM invoices WHERE invoices.invoice_number = returns.original_invoice_number)"
        )

    @staticmethod
    def _apply_phase3_migrations(cursor: sqlite3.Cursor) -> None:
        """Create Phase 3 POS draft and quotation tables for existing databases."""
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS held_sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT, hold_number TEXT NOT NULL UNIQUE,
                customer_data TEXT, cart_data TEXT NOT NULL, user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'HELD',
                created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS quotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, quote_number TEXT NOT NULL UNIQUE,
                customer_data TEXT, user_id INTEGER, subtotal REAL NOT NULL DEFAULT 0.0,
                total REAL NOT NULL DEFAULT 0.0, status TEXT NOT NULL DEFAULT 'OPEN',
                converted_sale_id INTEGER,
                created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (converted_sale_id) REFERENCES sales(id)
            );
            CREATE TABLE IF NOT EXISTS quotation_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, quotation_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL, part_no TEXT NOT NULL, description TEXT NOT NULL,
                brand TEXT, vehicle_make TEXT, vehicle_model TEXT, quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL, line_total REAL NOT NULL,
                FOREIGN KEY (quotation_id) REFERENCES quotations(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            CREATE INDEX IF NOT EXISTS idx_held_sales_status ON held_sales(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_quotations_status ON quotations(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_quotation_items_quote ON quotation_items(quotation_id);
        """)
        cursor.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)")

    @staticmethod
    def _apply_phase4_migrations(cursor: sqlite3.Cursor) -> None:
        """Add CRM fields and multi-vehicle support without altering financial history."""
        existing = {row[1] for row in cursor.execute("PRAGMA table_info(customers)")}
        for column, definition in {"customer_code": "TEXT", "company": "TEXT", "active": "BOOLEAN NOT NULL DEFAULT 1"}.items():
            if column not in existing:
                cursor.execute(f"ALTER TABLE customers ADD COLUMN {column} {definition}")
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL,
                registration_number TEXT NOT NULL, make TEXT, model TEXT, year INTEGER,
                engine TEXT, vin TEXT, color TEXT, notes TEXT, active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (customer_id) REFERENCES customers(id), UNIQUE(registration_number)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_code ON customers(customer_code);
            CREATE INDEX IF NOT EXISTS idx_customers_search ON customers(name, phone, email, customer_code, company);
            CREATE INDEX IF NOT EXISTS idx_vehicles_customer ON vehicles(customer_id, active);
            CREATE INDEX IF NOT EXISTS idx_vehicles_search ON vehicles(registration_number, vin, make, model);
        """)
        for table in ("sales", "invoices", "returns", "quotations"):
            table_columns = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
            if "vehicle_id" not in table_columns:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN vehicle_id INTEGER")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_vehicle ON {table}(vehicle_id)")
        cursor.execute("UPDATE customers SET customer_code=printf('CUS-%06d', id) WHERE customer_code IS NULL OR customer_code='' ")
        cursor.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (4)")

    @staticmethod
    def _apply_phase5_migrations(cursor: sqlite3.Cursor) -> None:
        """Add document lifecycle fields without changing existing documents."""
        for table, additions in {"quotations": {"issued_at": "TIMESTAMP", "expires_at": "TIMESTAMP"}, "sales": {"quotation_id": "INTEGER"}}.items():
            existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
            for column, definition in additions.items():
                if column not in existing:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quotations_search ON quotations(quote_number, status, created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_quotation ON sales(quotation_id)")
        cursor.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (5)")

    @staticmethod
    def _apply_phase6_migrations(cursor: sqlite3.Cursor) -> None:
        """Add non-destructive invoice void attribution to existing records."""
        existing = {row[1] for row in cursor.execute("PRAGMA table_info(invoices)")}
        for column, definition in {"voided_by": "INTEGER", "voided_at": "TIMESTAMP", "void_reason": "TEXT"}.items():
            if column not in existing:
                cursor.execute(f"ALTER TABLE invoices ADD COLUMN {column} {definition}")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)")
        cursor.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (6)")

    @staticmethod
    def _apply_phase7_migrations(cursor: sqlite3.Cursor) -> None:
        """Add nullable fiscal-readiness metadata; no FDMS response is fabricated."""
        existing = {row[1] for row in cursor.execute("PRAGMA table_info(invoices)")}
        fields = {"fiscal_device_id": "TEXT", "fiscal_day_number": "TEXT", "fdms_invoice_number": "TEXT", "fiscal_verification_code": "TEXT", "qr_code_data": "TEXT", "fiscal_submission_status": "TEXT", "fiscal_validation_status": "TEXT", "fiscalised_at": "TIMESTAMP"}
        for column, definition in fields.items():
            if column not in existing:
                cursor.execute(f"ALTER TABLE invoices ADD COLUMN {column} {definition}")
        cursor.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (7)")

    @staticmethod
    def _record_migration(cursor: sqlite3.Cursor, version: int) -> None:
        cursor.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (version,),
        )

    def health_check(self) -> dict:
        """Return development/admin diagnostics for the active database."""
        with self.get_db() as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
            migration_rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            counts = {row[0]: conn.execute(f'SELECT COUNT(*) FROM "{row[0]}"').fetchone()[0] for row in tables}
        return {
            "path": self.db_path,
            "size_bytes": os.path.getsize(self.db_path),
            "sqlite_version": sqlite3.sqlite_version,
            "schema_version": schema_version,
            "migrations": [row[0] for row in migration_rows],
            "foreign_keys": bool(foreign_keys),
            "journal_mode": journal_mode,
            "integrity_check": integrity,
            "table_counts": counts,
        }
        cursor.execute(
            "UPDATE sales SET cashier_name = (SELECT full_name FROM users WHERE users.id = sales.user_id) "
            "WHERE (cashier_name IS NULL OR cashier_name = '') AND user_id IS NOT NULL"
        )

        # Correct the original placeholder hash only; do not overwrite an
        # administrator password that has already been changed by the owner.
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE username = ? AND password_hash = ?",
            (
                "$2b$12$7o7j6bc/GMP/2Lriz27zxO0d5urBoMcMwL55tjX3baz3xsI5a0v8i",
                "admin",
                "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5YmMxSUWzFN2m",
            ),
        )

    def backup(self, backup_path: str) -> None:
        """
        Create a backup of the database.
        
        Args:
            backup_path: Path where backup should be saved
        """
        try:
            with self.get_db() as conn:
                backup_conn = sqlite3.connect(backup_path)
                conn.backup(backup_conn)
                backup_conn.close()
                logger.info(f"Database backup created: {backup_path}")
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            raise


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def get_database_manager(db_path: Optional[str] = None) -> DatabaseManager:
    """
    Get or create the global database manager instance.
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        DatabaseManager instance
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(str(Path(db_path) if db_path else CANONICAL_DATABASE_PATH))
        _db_manager.initialize()
    return _db_manager


def configure_database(db_path: str) -> DatabaseManager:
    """Use a specific database file (primarily for isolated test runs)."""
    global _db_manager
    os.environ["POS_DISABLE_BACKGROUND_SYNC"] = "1"
    _db_manager = DatabaseManager(db_path)
    _db_manager.initialize()
    return _db_manager

"""
Database schema for Motor Spares POS System.
Defines all tables and their structure for PHASE 1.
"""

SCHEMA_SQL = """
-- Categories table
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- Vehicle models table
CREATE TABLE IF NOT EXISTS vehicle_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year_from INTEGER,
    year_to INTEGER,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    UNIQUE(make, model)
);

-- Products table (main inventory)
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode TEXT UNIQUE,
    part_no TEXT NOT NULL UNIQUE,
    oem_number TEXT,
    description TEXT NOT NULL,
    brand TEXT,
    category_id INTEGER,
    vehicle_make TEXT,
    vehicle_model TEXT,
    vehicle_year_from INTEGER,
    vehicle_year_to INTEGER,
    cost_price REAL NOT NULL DEFAULT 0.0,
    selling_price REAL NOT NULL DEFAULT 0.0,
    currency TEXT DEFAULT 'ZWL',
    quantity_on_hand INTEGER DEFAULT 0,
    reorder_level INTEGER DEFAULT 5,
    vat_rate REAL DEFAULT 15.0,
    active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

-- Stock movements table (audit trail for stock changes)
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    movement_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    previous_quantity INTEGER NOT NULL,
    new_quantity INTEGER NOT NULL,
    reference TEXT,
    user_id INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Settings table (for system configuration)
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT,
    data_type TEXT DEFAULT 'string',
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- Users table (PHASE 2)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    email TEXT,
    full_name TEXT NOT NULL,
    phone TEXT,
    role_id INTEGER,
    is_active BOOLEAN DEFAULT 1,
    last_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (role_id) REFERENCES roles(id)
);

-- Roles table (PHASE 2)
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- Permissions table (PHASE 2)
CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    description TEXT,
    category TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- User Permissions table (PHASE 2)
CREATE TABLE IF NOT EXISTS user_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    permission_id INTEGER NOT NULL,
    granted_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    granted_by INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (permission_id) REFERENCES permissions(id),
    UNIQUE(user_id, permission_id)
);

-- Sales table (PHASE 2)
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE NOT NULL,
    customer_id INTEGER,
    customer_name TEXT,
    customer_phone TEXT,
    customer_email TEXT,
    customer_city TEXT,
    vehicle_id INTEGER,
    vehicle_make TEXT,
    vehicle_model TEXT,
    vehicle_registration TEXT,
    user_id INTEGER NOT NULL,
    cashier_name TEXT,
    subtotal REAL NOT NULL DEFAULT 0.0,
    vat_amount REAL NOT NULL DEFAULT 0.0,
    discount_amount REAL NOT NULL DEFAULT 0.0,
    total REAL NOT NULL DEFAULT 0.0,
    status TEXT DEFAULT 'COMPLETED',
    notes TEXT,
    quotation_id INTEGER,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
    FOREIGN KEY (quotation_id) REFERENCES quotations(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Sale Items table (PHASE 2)
CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    vat_rate REAL DEFAULT 15.0,
    line_total REAL NOT NULL,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (sale_id) REFERENCES sales(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Payments table (PHASE 2)
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    payment_method TEXT NOT NULL,
    currency TEXT DEFAULT 'ZWL',
    amount REAL NOT NULL,
    tendered REAL,
    change REAL,
    exchange_rate REAL DEFAULT 1.0,
    status TEXT DEFAULT 'COMPLETED',
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (sale_id) REFERENCES sales(id)
);

-- Parked POS carts are drafts only: inventory is not affected until checkout.
CREATE TABLE IF NOT EXISTS held_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hold_number TEXT NOT NULL UNIQUE,
    customer_data TEXT,
    cart_data TEXT NOT NULL,
    user_id INTEGER,
    status TEXT NOT NULL DEFAULT 'HELD',
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Quotations retain an immutable item snapshot and may be converted once.
CREATE TABLE IF NOT EXISTS quotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_number TEXT NOT NULL UNIQUE,
    customer_data TEXT,
    vehicle_id INTEGER,
    user_id INTEGER,
    subtotal REAL NOT NULL DEFAULT 0.0,
    total REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    converted_sale_id INTEGER,
    issued_at TIMESTAMP,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
    FOREIGN KEY (converted_sale_id) REFERENCES sales(id)
);

CREATE TABLE IF NOT EXISTS quotation_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quotation_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    part_no TEXT NOT NULL,
    description TEXT NOT NULL,
    brand TEXT,
    vehicle_make TEXT,
    vehicle_model TEXT,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    line_total REAL NOT NULL,
    FOREIGN KEY (quotation_id) REFERENCES quotations(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE INDEX IF NOT EXISTS idx_held_sales_status ON held_sales(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_quotations_status ON quotations(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quotation_items_quote ON quotation_items(quotation_id);

-- Customers table (PHASE 2)
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_code TEXT UNIQUE,
    name TEXT NOT NULL,
    company TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    city TEXT,
    country TEXT,
    id_number TEXT,
    vehicle_make TEXT,
    vehicle_model TEXT,
    vehicle_registration TEXT,
    active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    registration_number TEXT NOT NULL,
    make TEXT,
    model TEXT,
    year INTEGER,
    engine TEXT,
    vin TEXT,
    color TEXT,
    notes TEXT,
    active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    UNIQUE(registration_number)
);
CREATE INDEX IF NOT EXISTS idx_vehicles_customer ON vehicles(customer_id, active);
CREATE INDEX IF NOT EXISTS idx_vehicles_search ON vehicles(registration_number, vin, make, model);

-- Invoices table (PHASE 2)
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE NOT NULL,
    sale_id INTEGER NOT NULL,
    customer_id INTEGER,
    customer_name TEXT,
    customer_phone TEXT,
    customer_email TEXT,
    customer_city TEXT,
    vehicle_id INTEGER,
    vehicle_make TEXT,
    vehicle_model TEXT,
    vehicle_registration TEXT,
    subtotal REAL NOT NULL,
    vat_amount REAL NOT NULL,
    total REAL NOT NULL,
    payment_method TEXT,
    status TEXT DEFAULT 'ISSUED',
    voided_by INTEGER,
    voided_at TIMESTAMP,
    void_reason TEXT,
    fiscal_device_id TEXT,
    fiscal_day_number TEXT,
    fdms_invoice_number TEXT,
    fiscal_verification_code TEXT,
    qr_code_data TEXT,
    fiscal_submission_status TEXT,
    fiscal_validation_status TEXT,
    fiscalised_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (sale_id) REFERENCES sales(id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
    FOREIGN KEY (voided_by) REFERENCES users(id),
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

-- Returns table (PHASE 2)
CREATE TABLE IF NOT EXISTS returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_number TEXT UNIQUE NOT NULL,
    original_sale_id INTEGER NOT NULL,
    original_invoice_id INTEGER,
    original_invoice_number TEXT,
    customer_id INTEGER,
    customer_name TEXT,
    customer_phone TEXT,
    customer_email TEXT,
    vehicle_id INTEGER,
    vehicle_make TEXT,
    vehicle_model TEXT,
    vehicle_registration TEXT,
    user_id INTEGER NOT NULL,
    authorized_by INTEGER,
    return_type TEXT DEFAULT 'RETURN',
    refund_method TEXT,
    subtotal REAL NOT NULL DEFAULT 0.0,
    vat_amount REAL NOT NULL DEFAULT 0.0,
    total_refund REAL NOT NULL DEFAULT 0.0,
    reason TEXT,
    status TEXT DEFAULT 'PENDING',
    external_id TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (original_sale_id) REFERENCES sales(id),
    FOREIGN KEY (original_invoice_id) REFERENCES invoices(id),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (authorized_by) REFERENCES users(id)
);

-- Return Items table (PHASE 2)
CREATE TABLE IF NOT EXISTS return_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_id INTEGER NOT NULL,
    sale_item_id INTEGER,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    vat_rate REAL DEFAULT 15.0,
    line_total REAL NOT NULL,
    condition TEXT DEFAULT 'GOOD',
    return_reason TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (return_id) REFERENCES returns(id),
    FOREIGN KEY (sale_item_id) REFERENCES sale_items(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Refunds table (PHASE 2)
CREATE TABLE IF NOT EXISTS refunds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_id INTEGER NOT NULL,
    refund_amount REAL NOT NULL,
    refund_method TEXT NOT NULL,
    currency TEXT DEFAULT 'ZWL',
    exchange_rate REAL DEFAULT 1.0,
    original_payment_method TEXT,
    status TEXT DEFAULT 'PENDING',
    processed_by INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (return_id) REFERENCES returns(id),
    FOREIGN KEY (processed_by) REFERENCES users(id)
);

-- Audit Logs table (PHASE 2)
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    requesting_user_id INTEGER,
    approving_user_id INTEGER,
    reason TEXT,
    details TEXT,
    status TEXT DEFAULT 'COMPLETED',
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (requesting_user_id) REFERENCES users(id),
    FOREIGN KEY (approving_user_id) REFERENCES users(id)
);

-- Sync Queue table (PHASE 2/5)
CREATE TABLE IF NOT EXISTS sync_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    operation TEXT NOT NULL,
    payload TEXT,
    status TEXT DEFAULT 'PENDING',
    attempts INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    last_attempt TIMESTAMP,
    error_message TEXT,
    external_id TEXT,
    synced_at TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    UNIQUE(entity_type, entity_id, operation)
);

-- Sync Log table (PHASE 2/5)
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    external_id TEXT
    ,queue_id INTEGER
    ,success BOOLEAN
    ,server_response TEXT
);

CREATE TABLE IF NOT EXISTS product_tombstones (
    product_id INTEGER PRIMARY KEY,
    part_no TEXT NOT NULL UNIQUE,
    deleted_at TIMESTAMP DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS inventory_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_batch_id TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    imported_by INTEGER,
    imported_at TIMESTAMP DEFAULT (datetime('now','localtime')),
    total_rows INTEGER NOT NULL DEFAULT 0,
    created_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'COMPLETED',
    FOREIGN KEY (imported_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS inventory_import_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL,
    product_id INTEGER,
    part_no TEXT NOT NULL,
    action TEXT NOT NULL,
    before_values TEXT,
    after_values TEXT,
    FOREIGN KEY (import_id) REFERENCES inventory_imports(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_part_no ON products(part_no);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_vehicle ON products(vehicle_make, vehicle_model);
CREATE INDEX IF NOT EXISTS idx_stock_movements_product ON stock_movements(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_date ON stock_movements(created_at);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role_id);
CREATE INDEX IF NOT EXISTS idx_sales_invoice ON sales(invoice_number);
CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(created_at);
CREATE INDEX IF NOT EXISTS idx_returns_invoice ON returns(original_invoice_id);
CREATE INDEX IF NOT EXISTS idx_returns_sale ON returns(original_sale_id);
CREATE INDEX IF NOT EXISTS idx_returns_number ON returns(return_number);
CREATE INDEX IF NOT EXISTS idx_returns_status ON returns(status);
CREATE INDEX IF NOT EXISTS idx_returns_date ON returns(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(requesting_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_date ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status);
CREATE INDEX IF NOT EXISTS idx_sync_queue_date ON sync_queue(created_at);

-- Products are archived via active = 0.  Physical deletion is prohibited so
-- historical sale and invoice records always retain their product reference.
CREATE TRIGGER IF NOT EXISTS prevent_product_physical_delete
BEFORE DELETE ON products
BEGIN
    SELECT RAISE(ABORT, 'Products must be archived, not physically deleted');
END;
"""

def get_schema():
    """Returns the complete database schema SQL."""
    return SCHEMA_SQL


def get_initialization_sql():
    """Returns SQL to initialize default roles and permissions."""
    return """
-- Initialize default roles
INSERT OR IGNORE INTO roles (id, name, description) VALUES
    (1, 'ADMIN', 'Administrator with full access'),
    (2, 'MANAGER', 'Manager with elevated permissions'),
    (3, 'CASHIER', 'Cashier with POS permissions'),
    (4, 'STOCK_CLERK', 'Stock management clerk');

-- Initialize permissions
INSERT OR IGNORE INTO permissions (code, description, category) VALUES
    -- Product Management
    ('CREATE_PRODUCT', 'Create new products', 'PRODUCT'),
    ('EDIT_PRODUCT', 'Edit existing products', 'PRODUCT'),
    ('DELETE_PRODUCT', 'Delete products', 'PRODUCT'),
    ('RESTORE_PRODUCT', 'Restore archived products', 'PRODUCT'),
    ('CHANGE_PRICE', 'Change product prices', 'PRODUCT'),
    ('VIEW_COST_PRICE', 'View product cost prices', 'PRODUCT'),

    -- Dashboard access
    ('dashboard.view', 'View the administrative dashboard', 'DASHBOARD'),

    -- Administrative cleanup and tax reporting
    ('system.reset', 'Run administrative system data cleanup', 'ADMIN'),
    ('reports.tax', 'View tax and ZIMRA reports', 'REPORTS'),
    ('reports.export', 'Export tax reports', 'REPORTS'),
    ('returns.view', 'View returns', 'RETURNS'),
    ('returns.create', 'Create returns', 'RETURNS'),
    ('returns.approve', 'Approve returns', 'RETURNS'),
    ('returns.refund', 'Process return refunds', 'RETURNS'),

    -- Customer and vehicle CRM
    ('customers.view', 'View customer records', 'CUSTOMERS'),
    ('customers.create', 'Create customer records', 'CUSTOMERS'),
    ('customers.edit', 'Edit customer records', 'CUSTOMERS'),
    ('customers.archive', 'Archive customer records', 'CUSTOMERS'),
    ('customers.restore', 'Restore customer records', 'CUSTOMERS'),
    ('vehicles.view', 'View vehicle records', 'VEHICLES'),
    ('vehicles.create', 'Create vehicle records', 'VEHICLES'),
    ('vehicles.edit', 'Edit vehicle records', 'VEHICLES'),
    ('vehicles.archive', 'Archive vehicle records', 'VEHICLES'),
    ('vehicles.restore', 'Restore vehicle records', 'VEHICLES'),

    -- Quotation and invoice documents
    ('quotations.view', 'View quotations', 'QUOTATIONS'),
    ('quotations.create', 'Create quotations', 'QUOTATIONS'),
    ('quotations.edit', 'Edit quotations', 'QUOTATIONS'),
    ('quotations.print', 'Print quotations', 'QUOTATIONS'),
    ('quotations.convert', 'Convert quotations to sales', 'QUOTATIONS'),
    ('invoices.view', 'View invoices', 'INVOICES'),
    ('invoices.print', 'Print invoices', 'INVOICES'),
    ('invoices.reprint', 'Reprint invoices', 'INVOICES'),
    
    -- Stock Management
    ('ADD_STOCK', 'Add stock to inventory', 'STOCK'),
    ('ADJUST_STOCK', 'Adjust stock quantities', 'STOCK'),
    ('VIEW_INVENTORY', 'View inventory levels', 'STOCK'),
    
    -- Sales
    ('MAKE_SALE', 'Record sales transactions', 'SALES'),
    ('VOID_SALE', 'Void/cancel sales', 'SALES'),
    ('VIEW_SALES', 'View sales records', 'SALES'),
    
    -- Returns & Refunds
    ('CREATE_RETURN', 'Create product returns', 'RETURNS'),
    ('APPROVE_RETURN', 'Approve product returns', 'RETURNS'),
    ('PROCESS_REFUND', 'Process refunds', 'RETURNS'),
    ('PROCESS_CASH_REFUND', 'Process cash refunds', 'RETURNS'),
    ('PROCESS_LARGE_REFUND', 'Process large refunds', 'RETURNS'),
    ('PROCESS_EXCHANGE', 'Process product exchanges', 'RETURNS'),
    ('VOID_RETURN', 'Void returns', 'RETURNS'),
    ('DELETE_RETURN', 'Delete returns', 'RETURNS'),
    
    -- Reporting
    ('VIEW_REPORTS', 'View reports', 'REPORTS'),
    ('VIEW_PROFIT', 'View profit information', 'REPORTS'),
    
    -- User Management
    ('MANAGE_USERS', 'Create and manage users', 'ADMIN'),
    ('MANAGE_PERMISSIONS', 'Manage user permissions', 'ADMIN'),
    ('SYSTEM_SETTINGS', 'Modify system settings', 'ADMIN'),
    ('SYNC_DATA', 'Synchronize data', 'ADMIN'),
    ('AUTHORIZE_ACTION', 'Authorize sensitive actions', 'ADMIN');

-- Create default ADMIN user (password: admin123, will be changed on first login)
INSERT OR IGNORE INTO users (id, username, password_hash, full_name, role_id, is_active) VALUES
    (1, 'admin', '$2b$12$7o7j6bc/GMP/2Lriz27zxO0d5urBoMcMwL55tjX3baz3xsI5a0v8i', 'Administrator', 1, 1);

-- Assign all permissions to ADMIN role
INSERT OR IGNORE INTO user_permissions (user_id, permission_id)
SELECT 1, id FROM permissions;
"""

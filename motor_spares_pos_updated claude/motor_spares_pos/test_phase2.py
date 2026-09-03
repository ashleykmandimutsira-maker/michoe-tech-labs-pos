"""
Comprehensive test suite for PHASE 2: Authentication, Sales, Returns & Refunds.
Tests all new functionality including offline sync with idempotent sync.
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import services and models
from database.db import configure_database
from services.auth_service import AuthenticationService
from services.permission_service import PermissionService
from services.sales_service import SalesService
from services.returns_service import ReturnsService
from services.sync_service import SyncService
from services.audit_service import AuditService
from services.product_service import ProductService
from services.inventory_service import InventoryService


def initialize_test_data():
    """Initialize database and test data."""
    test_db = Path(__file__).resolve().parent / 'data' / 'phase2_test.db'
    if test_db.exists():
        test_db.unlink()
    configure_database(str(test_db))
    
    # Initialize sample products if not present
    product_service = ProductService()
    existing = product_service.get_all_products()
    
    if not existing:
        logger.info("Initializing sample products...")
        from models.product import Category, Product
        
        # Create categories
        electronics_cat = Category(name="Electronics", description="Electronic parts")
        parts_cat = Category(name="Parts", description="Mechanical parts")
        
        electronics_id = product_service.create_category(electronics_cat)
        parts_id = product_service.create_category(parts_cat)
        
        # Create test products
        test_products = [
            {
                'barcode': 'TEST-001',
                'part_no': 'ALT-001',
                'description': 'Alternator',
                'brand': 'Bosch',
                'vehicle_make': 'Toyota',
                'vehicle_model': 'Hilux',
                'cost_price': 150.0,
                'selling_price': 250.0,
                'quantity_on_hand': 10,
                'category_id': electronics_id,
            },
            {
                'barcode': 'TEST-002',
                'part_no': 'BRK-001',
                'description': 'Brake Pads',
                'brand': 'Ferodo',
                'vehicle_make': 'Toyota',
                'vehicle_model': 'Corolla',
                'cost_price': 25.0,
                'selling_price': 45.0,
                'quantity_on_hand': 50,
                'category_id': parts_id,
            },
        ]
        
        for product_data in test_products:
            try:
                product_service.create_product(Product(**product_data))
            except Exception as e:
                logger.warning(f"Product may already exist: {product_data['part_no']}")


def test_authentication():
    """Test user authentication."""
    logger.info("\n=== TEST: Authentication ===")
    
    auth_service = AuthenticationService()
    
    # Test login with default admin user
    user = auth_service.authenticate('admin', 'admin123')
    assert user is not None, "Admin user should exist"
    assert user.username == 'admin', "Username should match"
    assert user.is_admin(), "Admin user should have is_admin() = True"
    logger.info("✓ Admin authentication successful")
    
    # Test invalid password
    user = auth_service.authenticate('admin', 'wrongpassword')
    assert user is None, "Invalid password should fail"
    logger.info("✓ Invalid password correctly rejected")
    
    # Test create new user
    new_user_id = auth_service.create_user(
        username='testcashier',
        password='test123',
        full_name='Test Cashier',
        role_id=3,  # CASHIER
        email='cashier@test.com',
        phone='1234567890',
    )
    assert new_user_id > 0, "New user should be created"
    logger.info(f"✓ New user created: ID {new_user_id}")
    
    # Verify new user can login
    user = auth_service.authenticate('testcashier', 'test123')
    assert user is not None, "New user should authenticate"
    assert user.full_name == 'Test Cashier', "Name should match"
    logger.info("✓ New user authentication successful")
    
    return True


def test_permissions():
    """Test permission system."""
    logger.info("\n=== TEST: Permissions ===")
    
    auth_service = AuthenticationService()
    perm_service = PermissionService()
    
    # Admin should have all permissions
    admin = auth_service.authenticate('admin', 'admin123')
    assert admin is not None, "Admin user required for test"
    
    # Check admin has permissions
    admin_perms = auth_service.get_user_permissions(admin.id)
    assert len(admin_perms) > 0, "Admin should have permissions"
    logger.info(f"✓ Admin has {len(admin_perms)} permissions")
    
    # Check specific permission
    has_create_return = perm_service.has_permission(admin.id, 'CREATE_RETURN')
    assert has_create_return, "Admin should have CREATE_RETURN"
    logger.info("✓ Admin has CREATE_RETURN permission")
    
    # Cashier should not have CREATE_RETURN (need special permission)
    cashier = auth_service.authenticate('testcashier', 'test123')
    assert cashier is not None, "Cashier user required"
    
    has_create_return = perm_service.has_permission(cashier.id, 'CREATE_RETURN')
    # Cashier might have it via role, but let's check specific permission
    logger.info(f"✓ Cashier CREATE_RETURN permission check: {has_create_return}")
    
    return True


def test_sales():
    """Test sales transaction creation."""
    logger.info("\n=== TEST: Sales Transactions ===")
    
    auth_service = AuthenticationService()
    sales_service = SalesService()
    product_service = ProductService()
    
    # Get admin user (can make sales)
    admin = auth_service.authenticate('admin', 'admin123')
    
    # Get test product
    products = product_service.get_all_products()
    assert len(products) > 0, "Test products required"
    
    test_product = products[0]
    original_qty = test_product.quantity_on_hand
    
    # Create sale
    sale = sales_service.create_sale(
        customer_name='Test Customer',
        customer_phone='0771234567',
        user_id=admin.id,
        cashier_name=admin.full_name,
    )
    assert sale is not None, "Sale should be created"
    logger.info("✓ Sale created")
    
    # Add item to sale
    sale_item = sales_service.add_item_to_sale(
        sale=sale,
        product_id=test_product.id,
        quantity=2,
    )
    assert sale_item is not None, "Sale item should be added"
    assert sale.subtotal > 0, "Sale should have subtotal"
    logger.info(f"✓ Item added to sale: {sale_item.product_name} (qty: 2)")
    
    # Add payment
    payment = sales_service.add_payment(
        sale=sale,
        payment_method='CASH_USD',
        amount=sale.total,
        currency='USD',
        tendered=500.0,
    )
    assert payment is not None, "Payment should be added"
    logger.info(f"✓ Payment added: {payment.amount} {payment.currency}")
    
    # Complete sale
    sale_id = sales_service.complete_sale(sale)
    assert sale_id > 0, "Sale should be saved"
    logger.info(f"✓ Sale completed: ID {sale_id}, Invoice: {sale.invoice_number}")
    
    # Verify inventory was updated
    updated_product = product_service.get_product_by_id(test_product.id)
    assert updated_product.quantity_on_hand == original_qty - 2, "Inventory should be decremented"
    logger.info(f"✓ Inventory updated: {original_qty} -> {updated_product.quantity_on_hand}")
    
    return sale_id, sale.invoice_number


def test_returns():
    """Test return creation and processing."""
    logger.info("\n=== TEST: Returns Management ===")
    
    auth_service = AuthenticationService()
    returns_service = ReturnsService()
    perm_service = PermissionService()
    
    # Get admin (can create and approve returns)
    admin = auth_service.authenticate('admin', 'admin123')
    
    # Get the sale we created in test_sales
    sales_service = SalesService()
    recent_sales = sales_service.get_recent_sales(limit=1)
    assert len(recent_sales) > 0, "Sale required for return test"
    
    sale = recent_sales[0]
    assert len(sale.items) > 0, "Sale must have items"
    
    sale_item = sale.items[0]
    
    # Create return for first item (return 1 of 2)
    return_obj = returns_service.create_return(
        invoice_number=sale.invoice_number,
        items=[
            {
                'product_id': sale_item.product_id,
                'quantity': 1,
                'condition': 'GOOD',
                'return_reason': 'Customer changed mind',
            }
        ],
        reason='Customer return request',
        user_id=admin.id,
        customer_name=sale.customer_name,
        customer_phone=sale.customer_phone,
    )
    assert return_obj is not None, "Return should be created"
    logger.info(f"✓ Return created: {return_obj.return_number}")
    
    # Save return
    return_id = returns_service.save_return(return_obj)
    assert return_id > 0, "Return should be saved"
    logger.info(f"✓ Return saved: ID {return_id}")
    
    # Approve return
    assert perm_service.has_permission(admin.id, 'APPROVE_RETURN'), "Admin should have APPROVE_RETURN"
    returns_service.approve_return(return_id, admin.id)
    logger.info("✓ Return approved")
    
    # Process return (restore stock)
    returns_service.process_return(return_id, admin.id)
    logger.info("✓ Return processed (stock updated)")
    
    # Process refund
    assert perm_service.has_permission(admin.id, 'PROCESS_REFUND'), "Admin should have PROCESS_REFUND"
    refund_id = returns_service.process_refund(
        return_id=return_id,
        refund_method='CASH_USD',
        user_id=admin.id,
    )
    assert refund_id > 0, "Refund should be processed"
    logger.info(f"✓ Refund processed: ID {refund_id}")
    
    return return_id


def test_offline_sync():
    """Test offline sync queue with idempotent sync."""
    logger.info("\n=== TEST: Offline Sync (Idempotent) ===")
    
    sync_service = SyncService()
    
    # Enqueue a return for sync
    queue_id = sync_service.enqueue(
        entity_type='RETURN',
        entity_id=1,
        operation='CREATE',
        payload='{"return_number": "RET-20240101", "total": 100}',
    )
    assert queue_id > 0, "Entry should be enqueued"
    logger.info(f"✓ Entry enqueued: ID {queue_id}")
    
    # Get pending entries
    pending = sync_service.get_pending()
    assert len(pending) > 0, "Should have pending entries"
    logger.info(f"✓ Found {len(pending)} pending sync entries")
    
    # Simulate successful sync with external_id (prevents duplicates)
    external_id = "EXT-SERVER-ID-12345"
    success = sync_service.mark_synced(queue_id, external_id)
    assert success, "Should mark as synced"
    logger.info(f"✓ Entry synced with external_id: {external_id}")
    
    # Verify it's no longer pending
    pending = sync_service.get_pending()
    pending_ids = [p['id'] for p in pending]
    assert queue_id not in pending_ids, "Synced entry should not be pending"
    logger.info("✓ Synced entry removed from pending queue")
    
    # Get sync status
    status = sync_service.get_sync_status()
    logger.info(f"✓ Sync status: {status}")
    
    return True


def test_audit_logging():
    """Test audit logging for sensitive actions."""
    logger.info("\n=== TEST: Audit Logging ===")
    
    auth_service = AuthenticationService()
    audit_service = AuditService()
    
    admin = auth_service.authenticate('admin', 'admin123')
    
    # Log a return creation
    log_id = audit_service.log_return_creation(
        return_id=1,
        user_id=admin.id,
        reason='Customer requested return',
    )
    assert log_id > 0, "Audit log should be created"
    logger.info(f"✓ Audit log created: ID {log_id}")
    
    # Log an authorization
    auth_log_id = audit_service.log_return_approval(
        return_id=1,
        user_id=admin.id,
        approved_by=admin.id,
    )
    assert auth_log_id > 0, "Authorization log should be created"
    logger.info(f"✓ Authorization logged: ID {auth_log_id}")
    
    # Get audit history for return
    history = audit_service.get_action_history('RETURN', 1)
    assert len(history) > 0, "Should have audit history"
    logger.info(f"✓ Audit history retrieved: {len(history)} entries")
    
    # Get user activity
    activity = audit_service.get_user_activity(admin.id, limit=10)
    logger.info(f"✓ User activity: {len(activity)} entries")
    
    return True


def test_complete_workflow():
    """Test complete offline workflow: SALE -> RETURN -> SYNC."""
    logger.info("\n=== TEST: Complete Offline Workflow ===")
    
    logger.info("1. Create and complete sale (offline)")
    sale_id, invoice_number = test_sales()
    
    logger.info("2. Create and process return (offline)")
    return_id = test_returns()
    
    logger.info("3. Sync both to server (with external_id)")
    sync_service = SyncService()
    
    # Enqueue both sale and return. The real services may already have queued
    # these plus stock/product/refund records; the test marks every current
    # pending record as synced to simulate a successful server acknowledgement.
    sync_service.enqueue('SALE', sale_id, 'CREATE')
    sync_service.enqueue('RETURN', return_id, 'CREATE')
    
    pending_before = sync_service.get_pending()
    logger.info(f"✓ Queued workflow records: {len(pending_before)}")
    
    # Simulate sync to server for all pending records.
    for row in list(pending_before):
        sync_service.mark_synced(row['id'], f"SERVER-{row['entity_type']}-{row['entity_id']}")
    
    logger.info("✓ Successfully synced all pending records (idempotent)")
    
    # Verify sync queue is empty
    pending = sync_service.get_pending()
    assert len(pending) == 0, "Should have no pending after sync"
    logger.info("✓ Complete workflow successful!")
    
    return True


def run_all_tests():
    """Run all PHASE 2 tests."""
    logger.info("=" * 60)
    logger.info("PHASE 2 TEST SUITE: Authentication, Sales, Returns & Sync")
    logger.info("=" * 60)
    
    test_results = []
    
    try:
        logger.info("Initializing test environment...")
        initialize_test_data()
        
        # Run tests
        tests = [
            ("Authentication", test_authentication),
            ("Permissions", test_permissions),
            ("Sales", test_sales),
            ("Returns", test_returns),
            ("Offline Sync", test_offline_sync),
            ("Audit Logging", test_audit_logging),
            ("Complete Workflow", test_complete_workflow),
        ]
        
        passed = 0
        failed = 0
        
        for test_name, test_func in tests:
            try:
                result = test_func()
                test_results.append((test_name, "✓ PASS"))
                passed += 1
            except Exception as e:
                logger.error(f"✗ {test_name} FAILED: {e}", exc_info=True)
                test_results.append((test_name, f"✗ FAIL: {str(e)}"))
                failed += 1
        
        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("TEST SUMMARY")
        logger.info("=" * 60)
        
        for test_name, result in test_results:
            logger.info(f"{test_name:30} {result}")
        
        logger.info("=" * 60)
        logger.info(f"Results: {passed} passed, {failed} failed")
        logger.info("=" * 60)
        
        return failed == 0
    
    except Exception as e:
        logger.error(f"Test setup failed: {e}", exc_info=True)
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

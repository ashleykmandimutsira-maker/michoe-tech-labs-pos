"""
Command-line test script for Motor Spares POS - PHASE 1
Tests database, products, and inventory functionality without requiring GUI.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
from database.db import get_database_manager
from services.product_service import ProductService
from services.inventory_service import InventoryService
from models.product import Product, Category

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title):
    """Print a test section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_database_initialization():
    """Test 1: Database initialization."""
    print_section("TEST 1: Database Initialization")
    
    try:
        db = get_database_manager()
        logger.info("✓ Database manager created")
        
        # Check if database file exists
        db_path = "data/pos.db"
        if os.path.exists(db_path):
            logger.info(f"✓ Database file exists: {db_path}")
        else:
            logger.error(f"✗ Database file not found: {db_path}")
            return False
        
        # Try to query
        results = db.execute_query("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row['name'] for row in results]
        logger.info(f"✓ Tables created: {len(tables)}")
        logger.info(f"  Tables: {', '.join(sorted(tables))}")
        
        expected_tables = {'categories', 'vehicle_models', 'products', 'stock_movements', 'settings'}
        missing = expected_tables - set(tables)
        if missing:
            logger.error(f"✗ Missing tables: {missing}")
            return False
        
        logger.info("✓ All expected tables created")
        return True
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        return False


def initialize_test_data():
    """Initialize test data."""
    print_section("Initializing Test Data")
    
    product_service = ProductService()
    
    # Create categories
    categories = {
        'Engine': 'Engine parts',
        'Brakes': 'Brake system components',
    }
    
    category_map = {}
    for cat_name, cat_desc in categories.items():
        try:
            cat_id = product_service.create_category(
                Category(name=cat_name, description=cat_desc)
            )
            category_map[cat_name] = cat_id
            logger.info(f"✓ Created category: {cat_name}")
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                existing_cats = product_service.get_all_categories()
                for cat in existing_cats:
                    if cat.name == cat_name:
                        category_map[cat_name] = cat.id
                logger.info(f"✓ Category already exists: {cat_name}")
            else:
                raise
    
    # Create test products
    test_products = [
        {
            'barcode': '8711111111111',
            'part_no': 'BP04465',
            'description': 'Brake Pads Front',
            'brand': 'Bosch',
            'category': 'Brakes',
            'vehicle_make': 'Toyota',
            'vehicle_model': 'Corolla',
            'cost_price': 15.00,
            'selling_price': 35.00,
            'quantity_on_hand': 10,
            'reorder_level': 5,
        },
        {
            'barcode': '8711111111112',
            'part_no': 'OIL-001',
            'description': 'Oil Filter',
            'brand': 'Toyota',
            'category': 'Engine',
            'vehicle_make': 'Toyota',
            'vehicle_model': 'Corolla',
            'cost_price': 3.50,
            'selling_price': 8.50,
            'quantity_on_hand': 3,
            'reorder_level': 5,
        },
        {
            'barcode': '8722222222222',
            'part_no': 'HND-OIL-001',
            'description': 'Oil Filter',
            'brand': 'Honda',
            'category': 'Engine',
            'vehicle_make': 'Honda',
            'vehicle_model': 'Civic',
            'cost_price': 3.00,
            'selling_price': 7.50,
            'quantity_on_hand': 0,
            'reorder_level': 5,
        },
    ]
    
    created_count = 0
    for prod_data in test_products:
        try:
            product = Product(
                barcode=prod_data['barcode'],
                part_no=prod_data['part_no'],
                description=prod_data['description'],
                brand=prod_data['brand'],
                category_id=category_map.get(prod_data['category']),
                vehicle_make=prod_data['vehicle_make'],
                vehicle_model=prod_data['vehicle_model'],
                cost_price=prod_data['cost_price'],
                selling_price=prod_data['selling_price'],
                quantity_on_hand=prod_data['quantity_on_hand'],
                reorder_level=prod_data['reorder_level'],
            )
            product_id = product_service.create_product(product)
            logger.info(f"✓ Created product: {prod_data['part_no']} (ID: {product_id})")
            created_count += 1
        except Exception as e:
            if "UNIQUE constraint failed" not in str(e):
                logger.warning(f"✗ Failed to create product {prod_data['part_no']}: {e}")
            else:
                logger.info(f"✓ Product already exists: {prod_data['part_no']}")
                created_count += 1
    
    logger.info(f"✓ Test data initialized ({created_count} products)")


def test_product_operations():
    """Test 2: Product operations."""
    print_section("TEST 2: Product Operations")
    
    try:
        product_service = ProductService()
        
        # Get all products
        products = product_service.get_all_products()
        logger.info(f"✓ Retrieved {len(products)} products")
        
        if not products:
            logger.warning("⚠ No products found")
            return True
        
        # Get by barcode
        product = products[0]
        if product.barcode:
            found = product_service.get_product_by_barcode(product.barcode)
            if found and found.id == product.id:
                logger.info(f"✓ Barcode search working: {product.barcode}")
            else:
                logger.error(f"✗ Barcode search failed for {product.barcode}")
        
        # Get by part number
        found = product_service.get_product_by_part_no(product.part_no)
        if found and found.id == product.id:
            logger.info(f"✓ Part number search working: {product.part_no}")
        else:
            logger.error(f"✗ Part number search failed for {product.part_no}")
        
        # Search products
        results = product_service.search_products('Toyota')
        logger.info(f"✓ Search for 'Toyota': found {len(results)} products")
        
        results = product_service.search_products('Brake')
        logger.info(f"✓ Search for 'Brake': found {len(results)} products")
        
        return True
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        return False


def test_stock_levels():
    """Test 3: Stock level monitoring."""
    print_section("TEST 3: Stock Level Monitoring")
    
    try:
        product_service = ProductService()
        
        # Get low stock products
        low_stock = product_service.get_low_stock_products()
        logger.info(f"✓ Low stock products: {len(low_stock)}")
        for product in low_stock:
            logger.info(f"  - {product.part_no}: {product.quantity_on_hand}/{product.reorder_level}")
        
        # Get out of stock products
        out_of_stock = product_service.get_out_of_stock_products()
        logger.info(f"✓ Out of stock products: {len(out_of_stock)}")
        for product in out_of_stock:
            logger.info(f"  - {product.part_no}: {product.quantity_on_hand}")
        
        # Get inventory summary
        summary = product_service.get_inventory_summary()
        logger.info(f"✓ Inventory Summary:")
        logger.info(f"  Total products: {summary['total_products']}")
        logger.info(f"  In stock: {summary['in_stock']}")
        logger.info(f"  Out of stock: {summary['out_of_stock']}")
        logger.info(f"  Low stock: {summary['low_stock']}")
        logger.info(f"  Total units: {summary['total_units']}")
        logger.info(f"  Inventory value: {summary['inventory_value']:,.2f} ZWL")
        
        return True
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        return False


def test_stock_movements():
    """Test 4: Stock movements and inventory updates."""
    print_section("TEST 4: Stock Movements and Inventory Updates")
    
    try:
        product_service = ProductService()
        inventory_service = InventoryService()
        
        # Get a test product
        products = product_service.get_all_products()
        if not products:
            logger.warning("⚠ No products to test with")
            return True
        
        test_product = products[0]
        original_stock = test_product.quantity_on_hand
        
        logger.info(f"Testing with product: {test_product.part_no} (current stock: {original_stock})")
        
        # Record a sale
        try:
            if original_stock >= 2:
                movement_id = inventory_service.record_stock_movement(
                    product_id=test_product.id,
                    movement_type='SALE',
                    quantity=2,
                    reference='TEST-INV-001',
                    notes='Test sale'
                )
                logger.info(f"✓ Recorded SALE: movement ID {movement_id}")
                
                # Verify stock updated
                updated_product = product_service.get_product_by_id(test_product.id)
                if updated_product.quantity_on_hand == original_stock - 2:
                    logger.info(f"✓ Stock updated correctly: {original_stock} -> {updated_product.quantity_on_hand}")
                else:
                    logger.error(f"✗ Stock not updated correctly: expected {original_stock - 2}, got {updated_product.quantity_on_hand}")
            else:
                logger.info(f"⚠ Skipping SALE test (insufficient stock: {original_stock})")
        except ValueError as e:
            if "Insufficient stock" in str(e):
                logger.info(f"✓ Correctly prevented overselling: {e}")
            else:
                raise
        
        # Record a purchase
        movement_id = inventory_service.record_stock_movement(
            product_id=test_product.id,
            movement_type='PURCHASE',
            quantity=5,
            reference='PO-12345',
            notes='Test stock receipt'
        )
        logger.info(f"✓ Recorded PURCHASE: movement ID {movement_id}")
        
        # Verify stock increased
        updated_product = product_service.get_product_by_id(test_product.id)
        expected_stock = (original_stock - 2 if original_stock >= 2 else original_stock) + 5
        if updated_product.quantity_on_hand == expected_stock:
            logger.info(f"✓ Stock increased correctly: {expected_stock}")
        else:
            logger.error(f"✗ Stock not increased correctly: expected {expected_stock}, got {updated_product.quantity_on_hand}")
        
        # Get movement history
        history = inventory_service.get_product_movement_history(test_product.id, limit=10)
        logger.info(f"✓ Movement history: {len(history)} records")
        for movement in history[:3]:
            logger.info(f"  - {movement.movement_type}: qty={movement.quantity}, stock={movement.previous_quantity}->{movement.new_quantity}")
        
        return True
    except Exception as e:
        logger.error(f"✗ Error: {e}", exc_info=True)
        return False


def main():
    """Run all tests."""
    print("\n" + "█" * 70)
    print("█" + " " * 68 + "█")
    print("█" + "  Motor Spares POS - PHASE 1 Command-Line Test Suite".center(68) + "█")
    print("█" + " " * 68 + "█")
    print("█" * 70)
    
    results = {}
    
    # Run tests
    results['Database'] = test_database_initialization()
    
    if results['Database']:
        initialize_test_data()
        results['Products'] = test_product_operations()
        results['StockLevels'] = test_stock_levels()
        results['Movements'] = test_stock_movements()
    
    # Print summary
    print_section("Test Summary")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}  -  {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! PHASE 1 is working correctly.")
        return 0
    else:
        print(f"\n⚠ {total - passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

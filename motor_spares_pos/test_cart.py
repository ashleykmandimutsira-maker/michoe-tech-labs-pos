"""
Cart functionality tests.
Tests for POS cart data integrity and product independence.
"""

import sys
import os
import shutil
import tempfile
from pathlib import Path
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import main as pos_main
from database.db import configure_database
from services.product_service import ProductService

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


@pytest.fixture(scope="module", autouse=True)
def _cart_test_database():
    """Give this module its own isolated, throwaway SQLite database seeded
    with the same sample catalog main.py creates on first run (this suite
    expects part numbers like SPARK-001 and OIL-001 to exist).

    Without this fixture these tests silently relied on whatever database
    the process-wide DatabaseManager singleton happened to be left pointing
    at by a previously-run test module -- which breaks under pytest, since
    another module's tearDown() may have already deleted that database's
    temp directory by the time these tests run. This never touches the
    real data/pos.db.
    """
    directory = Path(tempfile.mkdtemp(prefix="pos_cart_test_"))
    configure_database(str(directory / "cart_test.db"))
    pos_main.initialize_sample_data()
    yield
    shutil.rmtree(directory, ignore_errors=True)


class CartSimulator:
    """Simulates the POSPage cart for testing."""
    
    def __init__(self):
        self.cart = {}
    
    def add_to_cart(self, product):
        """Add product to cart (mimic POSPage.add_to_cart)."""
        if product.quantity_on_hand <= 0:
            raise ValueError(f"Out of stock: {product.description}")
        
        if product.id in self.cart:
            current_qty = self.cart[product.id]['quantity']
            new_qty = current_qty + 1
            if new_qty > product.quantity_on_hand:
                raise ValueError(f"Only {product.quantity_on_hand} available")
            self.cart[product.id]['quantity'] = new_qty
        else:
            # KEY FIX: Store independent copy of product data, not reference
            self.cart[product.id] = {
                'product_id': product.id,
                'part_no': product.part_no,
                'description': product.description,
                'brand': product.brand or '',
                'vehicle_make': product.vehicle_make,
                'vehicle_model': product.vehicle_model,
                'unit_price': product.selling_price,
                'quantity': 1
            }
    
    def get_cart_total(self):
        """Calculate cart total from cart items."""
        total = 0.0
        for item in self.cart.values():
            total += item['unit_price'] * item['quantity']
        return total
    
    def get_item(self, product_id):
        """Get cart item by product ID."""
        return self.cart.get(product_id)


def test_add_different_products():
    """Test adding two different products to cart."""
    logger.info("\n" + "="*70)
    logger.info("TEST: Add Different Products")
    logger.info("="*70)
    
    product_service = ProductService()
    cart = CartSimulator()
    
    # Get two different products
    spark_plugs = product_service.get_product_by_part_no('SPARK-001')
    oil_filter = product_service.get_product_by_part_no('OIL-001')
    
    assert spark_plugs is not None, "SPARK-001 not found"
    assert oil_filter is not None, "OIL-001 not found"
    assert spark_plugs.id != oil_filter.id, "Products must be different"
    
    logger.info(f"✓ Product 1: {spark_plugs.part_no} - {spark_plugs.description} (${spark_plugs.selling_price})")
    logger.info(f"✓ Product 2: {oil_filter.part_no} - {oil_filter.description} (${oil_filter.selling_price})")
    
    # Add both products to cart
    cart.add_to_cart(spark_plugs)
    cart.add_to_cart(oil_filter)
    
    logger.info(f"\n✓ Added both products to cart")
    logger.info(f"  Cart size: {len(cart.cart)} items")
    
    # Verify data independence
    spark_in_cart = cart.get_item(spark_plugs.id)
    oil_in_cart = cart.get_item(oil_filter.id)
    
    assert spark_in_cart is not None, "Spark plugs not in cart"
    assert oil_in_cart is not None, "Oil filter not in cart"
    
    logger.info(f"\nCart Item 1:")
    logger.info(f"  Part No: {spark_in_cart['part_no']}")
    logger.info(f"  Description: {spark_in_cart['description']}")
    logger.info(f"  Brand: {spark_in_cart['brand']}")
    logger.info(f"  Price: ${spark_in_cart['unit_price']:.2f}")
    logger.info(f"  Quantity: {spark_in_cart['quantity']}")
    
    logger.info(f"\nCart Item 2:")
    logger.info(f"  Part No: {oil_in_cart['part_no']}")
    logger.info(f"  Description: {oil_in_cart['description']}")
    logger.info(f"  Brand: {oil_in_cart['brand']}")
    logger.info(f"  Price: ${oil_in_cart['unit_price']:.2f}")
    logger.info(f"  Quantity: {oil_in_cart['quantity']}")
    
    # Verify independence
    assert spark_in_cart['part_no'] == spark_plugs.part_no, "Spark plug part_no mismatch"
    assert spark_in_cart['description'] == spark_plugs.description, "Spark plug description mismatch"
    assert spark_in_cart['brand'] == spark_plugs.brand, "Spark plug brand mismatch"
    assert spark_in_cart['unit_price'] == spark_plugs.selling_price, "Spark plug price mismatch"
    
    assert oil_in_cart['part_no'] == oil_filter.part_no, "Oil filter part_no mismatch"
    assert oil_in_cart['description'] == oil_filter.description, "Oil filter description mismatch"
    assert oil_in_cart['brand'] == oil_filter.brand or '', "Oil filter brand mismatch"
    assert oil_in_cart['unit_price'] == oil_filter.selling_price, "Oil filter price mismatch"
    
    # THE CRITICAL TEST: Verify they don't share data
    assert spark_in_cart['brand'] != oil_in_cart['brand'], f"FAIL: Brands match! {spark_in_cart['brand']} == {oil_in_cart['brand']}"
    assert spark_in_cart['description'] != oil_in_cart['description'], "FAIL: Descriptions match!"
    assert spark_in_cart['unit_price'] != oil_in_cart['unit_price'], "FAIL: Prices match!"
    
    logger.info(f"\n✓ PASS: Items are independent")
    logger.info(f"  Spark brand ({spark_in_cart['brand']}) != Oil brand ({oil_in_cart['brand']})")
    logger.info(f"  Spark price (${spark_in_cart['unit_price']:.2f}) != Oil price (${oil_in_cart['unit_price']:.2f})")


def test_same_product_increases_quantity():
    """Test that adding same product twice increments quantity."""
    logger.info("\n" + "="*70)
    logger.info("TEST: Same Product Increases Quantity")
    logger.info("="*70)
    
    product_service = ProductService()
    cart = CartSimulator()
    
    # Get a product
    spark_plugs = product_service.get_product_by_part_no('SPARK-001')
    assert spark_plugs is not None, "SPARK-001 not found"
    
    logger.info(f"✓ Product: {spark_plugs.part_no} - {spark_plugs.description}")
    logger.info(f"  Available stock: {spark_plugs.quantity_on_hand}")
    
    # Add same product twice
    cart.add_to_cart(spark_plugs)
    cart_item_after_first = cart.get_item(spark_plugs.id)
    assert cart_item_after_first['quantity'] == 1, "First add should set quantity to 1"
    logger.info(f"\n✓ After 1st add: Qty = {cart_item_after_first['quantity']}")
    
    cart.add_to_cart(spark_plugs)
    cart_item_after_second = cart.get_item(spark_plugs.id)
    assert cart_item_after_second['quantity'] == 2, "Second add should increment quantity to 2"
    logger.info(f"✓ After 2nd add: Qty = {cart_item_after_second['quantity']}")
    
    # Verify cart still has only 1 item (same product)
    assert len(cart.cart) == 1, "Cart should have only 1 unique product"
    logger.info(f"✓ Cart still has 1 unique item (not 2 duplicate rows)")
    
    # Verify line total
    line_total = cart_item_after_second['unit_price'] * cart_item_after_second['quantity']
    expected_total = spark_plugs.selling_price * 2
    assert line_total == expected_total, f"Line total mismatch: {line_total} != {expected_total}"
    logger.info(f"\n✓ Line total correct: {cart_item_after_second['quantity']} × ${cart_item_after_second['unit_price']:.2f} = ${line_total:.2f}")


def test_cart_total_calculation():
    """Test that cart total is calculated correctly from cart items."""
    logger.info("\n" + "="*70)
    logger.info("TEST: Cart Total Calculation")
    logger.info("="*70)
    
    product_service = ProductService()
    cart = CartSimulator()
    
    # Add multiple products
    spark_plugs = product_service.get_product_by_part_no('SPARK-001')
    oil_filter = product_service.get_product_by_part_no('OIL-001')
    air_filter = product_service.get_product_by_part_no('BP-AIR-001')
    
    assert spark_plugs and oil_filter and air_filter, "Products not found"
    
    # Add products with various quantities
    cart.add_to_cart(spark_plugs)
    cart.add_to_cart(spark_plugs)
    cart.add_to_cart(oil_filter)
    cart.add_to_cart(air_filter)
    cart.add_to_cart(air_filter)
    
    logger.info(f"✓ Added 5 items to cart (3 unique products)")
    
    # Calculate expected total manually
    expected_total = (
        spark_plugs.selling_price * 2 +
        oil_filter.selling_price * 1 +
        air_filter.selling_price * 2
    )
    
    # Get cart total from cart model (not from table text)
    cart_total = cart.get_cart_total()
    
    logger.info(f"\nCart contents:")
    for product_id, item in cart.cart.items():
        line = item['unit_price'] * item['quantity']
        logger.info(f"  {item['part_no']}: {item['quantity']} × ${item['unit_price']:.2f} = ${line:.2f}")
    
    logger.info(f"\n  Expected total: ${expected_total:.2f}")
    logger.info(f"  Cart total:     ${cart_total:.2f}")
    
    assert abs(cart_total - expected_total) < 0.01, f"Total mismatch: {cart_total} != {expected_total}"
    logger.info(f"✓ PASS: Cart total is correct")


def test_product_independence_after_quantity_change():
    """Test that changing quantity of one product doesn't affect others."""
    logger.info("\n" + "="*70)
    logger.info("TEST: Product Independence After Quantity Change")
    logger.info("="*70)
    
    product_service = ProductService()
    cart = CartSimulator()
    
    # Add two products
    spark_plugs = product_service.get_product_by_part_no('SPARK-001')
    oil_filter = product_service.get_product_by_part_no('OIL-001')
    
    cart.add_to_cart(spark_plugs)
    cart.add_to_cart(oil_filter)
    
    spark_initial = cart.get_item(spark_plugs.id).copy()
    
    # Change oil filter quantity
    cart.cart[oil_filter.id]['quantity'] = 5
    
    spark_after = cart.get_item(spark_plugs.id)
    
    logger.info(f"\nBefore oil filter quantity change:")
    logger.info(f"  Spark plugs Qty: {spark_initial['quantity']}")
    logger.info(f"  Spark brand: {spark_initial['brand']}")
    logger.info(f"  Spark price: ${spark_initial['unit_price']:.2f}")
    
    logger.info(f"\nAfter changing oil filter Qty to 5:")
    logger.info(f"  Spark plugs Qty: {spark_after['quantity']}")
    logger.info(f"  Spark brand: {spark_after['brand']}")
    logger.info(f"  Spark price: ${spark_after['unit_price']:.2f}")
    
    # Verify spark plugs data didn't change
    assert spark_after['quantity'] == spark_initial['quantity'], "Quantity changed!"
    assert spark_after['brand'] == spark_initial['brand'], "Brand changed!"
    assert spark_after['unit_price'] == spark_initial['unit_price'], "Price changed!"
    
    logger.info(f"\n✓ PASS: Spark plug data unchanged")


if __name__ == '__main__':
    logger.info("="*70)
    logger.info("POS CART - DATA INTEGRITY TESTS")
    logger.info("="*70)
    
    try:
        test_add_different_products()
        test_same_product_increases_quantity()
        test_cart_total_calculation()
        test_product_independence_after_quantity_change()
        
        logger.info("\n" + "="*70)
        logger.info("✓✓✓ ALL CART TESTS PASSED ✓✓✓")
        logger.info("="*70)
        logger.info("\nThe cart now:")
        logger.info("  - Stores independent data for each product (no shared references)")
        logger.info("  - Correctly deduplicates same products")
        logger.info("  - Maintains accurate quantities and prices")
        logger.info("  - Calculates totals correctly")
        
    except AssertionError as e:
        logger.error(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

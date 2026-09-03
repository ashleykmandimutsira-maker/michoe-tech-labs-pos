"""
Main entry point for Motor Spares POS.
PHASE 1: Database initialization and test window.
"""

import sys
import os
import logging

# Add project directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db import get_database_manager
from services.product_service import ProductService
from models.product import Product, Category

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def initialize_sample_data():
    """Initialize development catalog data once, without touching real data.

    Startup is intentionally idempotent: existing categories and products are
    read first (including archived products), then only missing sample records
    are inserted.  Unexpected database errors are logged and re-raised.
    """
    product_service = ProductService()

    categories = {
        'Engine': 'Engine parts',
        'Brakes': 'Brake system components',
        'Suspension': 'Suspension parts',
        'Electrical': 'Electrical components',
        'Belts & Hoses': 'Belts and hoses',
        'Cooling System': 'Cooling system parts',
        'Drivetrain': 'Drivetrain components',
    }

    existing_categories = {cat.name: cat for cat in product_service.get_all_categories()}
    category_map = {name: cat.id for name, cat in existing_categories.items()}
    created_categories = 0
    skipped_categories = 0
    for cat_name, cat_desc in categories.items():
        if cat_name in existing_categories:
            skipped_categories += 1
            continue
        try:
            cat_id = product_service.create_category(Category(name=cat_name, description=cat_desc))
            category_map[cat_name] = cat_id
            existing_categories[cat_name] = product_service.get_category_by_id(cat_id)
            created_categories += 1
            logger.info("Created sample category: %s", cat_name)
        except Exception:
            logger.exception("Failed to create sample category: %s", cat_name)
            raise

    # Sample products for Toyota Corolla
    toyota_products = [
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
            'quantity_on_hand': 12,
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
            'quantity_on_hand': 25,
            'reorder_level': 10,
        },
        {
            'barcode': '8711111111113',
            'part_no': 'BP-AIR-001',
            'description': 'Air Filter',
            'brand': 'Mann Filter',
            'category': 'Engine',
            'vehicle_make': 'Toyota',
            'vehicle_model': 'Corolla',
            'cost_price': 5.00,
            'selling_price': 12.00,
            'quantity_on_hand': 18,
            'reorder_level': 8,
        },
        {
            'barcode': '8711111111114',
            'part_no': 'SPARK-001',
            'description': 'Spark Plugs (Set of 4)',
            'brand': 'NGK',
            'category': 'Electrical',
            'vehicle_make': 'Toyota',
            'vehicle_model': 'Corolla',
            'cost_price': 8.00,
            'selling_price': 18.00,
            'quantity_on_hand': 22,
            'reorder_level': 5,
        },
        {
            'barcode': '8711111111115',
            'part_no': 'FAN-BELT-001',
            'description': 'Fan Belt',
            'brand': 'Toyota',
            'category': 'Belts & Hoses',
            'vehicle_make': 'Toyota',
            'vehicle_model': 'Corolla',
            'cost_price': 4.50,
            'selling_price': 10.50,
            'quantity_on_hand': 3,  # Low stock
            'reorder_level': 5,
        },
    ]

    # More sample products for Honda Civic.
    honda_products = [
        {
            'barcode': '8722222222221',
            'part_no': 'HND-BP-001',
            'description': 'Brake Pads Front',
            'brand': 'Akebono',
            'category': 'Brakes',
            'vehicle_make': 'Honda',
            'vehicle_model': 'Civic',
            'cost_price': 12.00,
            'selling_price': 28.00,
            'quantity_on_hand': 8,
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
            'quantity_on_hand': 0,  # Out of stock
            'reorder_level': 5,
        },
    ]

    sample_products = toyota_products + honda_products
    existing_products = {
        product.part_no: product
        for product in product_service.get_all_products(active_only=False)
    }
    created_products = 0
    skipped_products = 0
    for prod_data in sample_products:
        part_no = prod_data['part_no']
        if part_no in existing_products:
            skipped_products += 1
            continue
        product = Product(
            barcode=prod_data['barcode'],
            part_no=part_no,
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
        try:
            product_id = product_service.create_product(product)
            existing_products[part_no] = product
            created_products += 1
            logger.info("Created sample product: %s (ID: %s)", part_no, product_id)
        except Exception:
            logger.exception("Failed to create sample product: %s", part_no)
            raise

    if created_categories == 0 and created_products == 0:
        logger.info("Sample data already exists; skipping initialization")
    else:
        logger.info(
            "Sample data initialization complete: created %s categories and %s products; skipped %s categories and %s products",
            created_categories, created_products, skipped_categories, skipped_products,
        )
    return {
        'created_categories': created_categories,
        'created_products': created_products,
        'skipped_categories': skipped_categories,
        'skipped_products': skipped_products,
    }


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Motor Spares POS - PHASE 1")
    logger.info("=" * 60)

    try:
        # Initialize database
        db = get_database_manager()
        logger.info("Database initialized")

        # Sample data is opt-in so a reset database stays empty until the user
        # explicitly imports or seeds a development dataset.
        if os.environ.get('POS_LOAD_SAMPLE_DATA') == '1':
            initialize_sample_data()

        # Import and run the branded application shell.
        from ui.test_window import launch
        logger.info("Launching Michoe Tech Labs application")
        sys.exit(launch())

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

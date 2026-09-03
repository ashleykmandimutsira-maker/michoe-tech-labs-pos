"""Regression tests for idempotent startup/sample catalog initialization."""

from __future__ import annotations

import logging
from pathlib import Path

from database.db import configure_database
from models.product import Product
from services.product_service import ProductService
import main


def _counts(service: ProductService) -> tuple[int, int]:
    db = service.db
    categories = db.execute_query("SELECT COUNT(*) count FROM categories")[0][
        "count"
    ]
    products = db.execute_query("SELECT COUNT(*) count FROM products")[0][
        "count"
    ]
    return categories, products


def run_all_tests() -> bool:
    test_db = (
        Path(__file__).resolve().parent / "data" / "initialization_test.db"
    )
    test_db.unlink(missing_ok=True)
    try:
        configure_database(str(test_db))
        service = ProductService()

        # First startup creates the catalog; the second must only read it.
        first = main.initialize_sample_data()
        after_first = _counts(service)
        second = main.initialize_sample_data()
        after_second = _counts(service)
        assert after_first == after_second, (after_first, after_second)
        assert second["created_categories"] == 0
        assert second["created_products"] == 0
        assert second["skipped_categories"] == 7
        assert second["skipped_products"] == 7
        print("PASS initialization is idempotent")

        # A real user duplicate gets a clear validation error, not seed logic.
        service.create_product(
            Product(part_no="USER-NEW-001", description="User product")
        )
        try:
            service.create_product(
                Product(
                    part_no="USER-NEW-001",
                    description="Duplicate user product",
                )
            )
        except ValueError as exc:
            assert "already exists" in str(exc)
            print("PASS duplicate user product validation")
        else:
            raise AssertionError(
                "Duplicate product creation should fail validation"
            )
        return True
    finally:
        test_db.unlink(missing_ok=True)


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    raise SystemExit(0 if run_all_tests() else 1)

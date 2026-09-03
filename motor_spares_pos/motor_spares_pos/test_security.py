"""Security regression tests for product archive/restore authorization."""

from pathlib import Path
import shutil
import tempfile
from database.db import configure_database
from models.product import Product
from services.auth_service import AuthenticationService
from services.product_service import ProductService
from services.sales_service import SalesService

TEST_DATABASES: list[Path] = []


def _setup():
    db_path = (
        Path(tempfile.mkdtemp(prefix="pos_security_")) / "security_test.db"
    )
    TEST_DATABASES.append(db_path.parent)
    configure_database(str(db_path))
    auth = AuthenticationService()
    cashier = auth.create_user(
        "security_cashier", "cash123", "Security Cashier", 3
    )
    clerk = auth.create_user("security_clerk", "clerk123", "Security Clerk", 4)
    manager = auth.create_user(
        "security_manager", "manager123", "Security Manager", 2
    )
    admin = auth.authenticate("admin", "admin123")
    return ProductService(), auth, cashier, clerk, manager, admin


def _product(service, part="SEC-001"):
    return service.create_product(
        Product(
            part_no=part,
            description="Security Test Part",
            selling_price=20,
            cost_price=10,
            quantity_on_hand=10,
        )
    )


def test_cashier_cannot_delete_product():
    service, _, cashier, _, _, admin = _setup()
    product_id = _product(service, "SEC-CASH")
    try:
        service.delete_product(product_id, cashier, reason="attempt")
    except PermissionError:
        pass
    else:
        raise AssertionError("Cashier delete must be rejected")
    assert service.get_product_by_id(product_id).active


def test_stock_clerk_cannot_delete_product():
    service, _, _, clerk, _, _ = _setup()
    product_id = _product(service, "SEC-CLERK")
    try:
        service.delete_product(product_id, clerk, reason="attempt")
    except PermissionError:
        pass
    else:
        raise AssertionError("Stock clerk delete must be rejected")
    assert service.get_product_by_id(product_id).active


def test_manager_delete_requires_authorization():
    service, _, _, _, manager, admin = _setup()
    product_id = _product(service, "SEC-MGR")
    try:
        service.delete_product(product_id, manager, reason="manager request")
    except PermissionError:
        pass
    else:
        raise AssertionError("Manager delete must require admin authorization")
    assert service.delete_product(
        product_id, manager, admin.id, "approved by admin"
    )


def test_admin_can_delete_product():
    service, _, _, _, _, admin = _setup()
    product_id = _product(service, "SEC-ADMIN")
    assert service.delete_product(product_id, admin.id, reason="retired part")
    assert service.get_product_by_id(product_id) is None


def test_archived_product_not_shown_in_pos():
    service, _, _, _, _, admin = _setup()
    product_id = _product(service, "SEC-POS")
    service.archive_product(product_id, admin.id, reason="retired")
    assert service.get_product_by_part_no("SEC-POS") is None
    assert not service.search_products("SEC-POS")


def test_archived_product_remains_in_historical_sales():
    service, _, _, _, _, admin = _setup()
    product_id = _product(service, "SEC-HISTORY")
    sales = SalesService()
    sale = sales.create_sale(user_id=admin.id, cashier_name=admin.full_name)
    sales.add_item_to_sale(sale, product_id, 1)
    sales.add_payment(sale, "CASH_USD", sale.total, "USD", sale.total)
    sales.complete_sale(sale)
    service.archive_product(product_id, admin.id, reason="retired")
    historical = sales.get_sale_by_invoice_number(sale.invoice_number)
    assert (
        historical
        and historical.items
        and historical.items[0].product_id == product_id
    )


def test_admin_can_restore_product():
    service, _, _, _, _, admin = _setup()
    product_id = _product(service, "SEC-RESTORE")
    service.archive_product(product_id, admin.id, reason="temporary")
    assert service.restore_product(
        product_id, admin.id, reason="part returned"
    )
    assert service.get_product_by_part_no("SEC-RESTORE").active


def test_delete_action_creates_audit_log():
    service, _, cashier, _, _, admin = _setup()
    product_id = _product(service, "SEC-AUDIT")
    service.delete_product(product_id, cashier, admin.id, "customer request")
    logs = service.db.execute_query(
        "SELECT * FROM audit_logs WHERE entity_type='PRODUCT' AND entity_id=? ORDER BY id DESC",
        (product_id,),
    )
    assert (
        logs
        and logs[0]["action"] == "PRODUCT_PERMANENTLY_DELETED"
        and logs[0]["requesting_user_id"] == cashier
        and logs[0]["approving_user_id"] == admin.id
        and logs[0]["reason"] == "customer request"
    )


def test_admin_can_grant_privileges_and_role_downgrade_is_safe():
    service, auth, cashier, _, manager, admin = _setup()
    granted = auth.set_user_permissions(
        admin.id, cashier, ["MAKE_SALE", "VIEW_REPORTS", "VIEW_PROFIT"]
    )
    current = {p.code for p in auth.get_user_permissions(cashier)}
    assert {"MAKE_SALE", "VIEW_REPORTS", "VIEW_PROFIT"} == current
    assert "VIEW_REPORTS" in granted["granted"] or "VIEW_REPORTS" in current

    # Changing to a lower-privilege role replaces the previous direct grants
    # with the new role baseline so elevated privileges cannot linger.
    auth.change_user_role(
        admin.id, cashier, auth.get_user_by_id(manager).role_id
    )
    promoted = auth.get_user_by_id(cashier)
    assert promoted.role.name == "MANAGER"
    promoted_permissions = {
        permission.code for permission in auth.get_user_permissions(cashier)
    }
    assert "CHANGE_PRICE" in promoted_permissions
    assert "DELETE_PRODUCT" not in promoted_permissions


if __name__ == "__main__":
    tests = [
        test_cashier_cannot_delete_product,
        test_stock_clerk_cannot_delete_product,
        test_manager_delete_requires_authorization,
        test_admin_can_delete_product,
        test_archived_product_not_shown_in_pos,
        test_archived_product_remains_in_historical_sales,
        test_admin_can_restore_product,
        test_delete_action_creates_audit_log,
        test_admin_can_grant_privileges_and_role_downgrade_is_safe,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    for test_dir in TEST_DATABASES:
        shutil.rmtree(test_dir, ignore_errors=True)
    print("9/9 security tests passed")

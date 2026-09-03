"""Customer and vehicle CRM backed by the existing POS database and services."""

from typing import Optional
import json

from database.db import get_database_manager
from models.customer import Customer, Vehicle
from services.audit_service import AuditService
from services.sync_service import SyncService
from services.permission_service import PermissionService


class CustomerService:
    def __init__(self):
        self.db = get_database_manager()
        self.sync = SyncService()
        self.permissions = PermissionService()

    def _require(self, user_id, permission):
        if user_id is not None:
            self.permissions.check_permission_or_raise(user_id, permission)

    def search_customers(
        self, term: str = "", archived: bool = False
    ) -> list[Customer]:
        pattern = f"%{term.strip()}%"
        rows = self.db.execute_query(
            "SELECT * FROM customers WHERE active=? AND (name LIKE ? OR phone LIKE ? OR email LIKE ? OR customer_code LIKE ? OR company LIKE ?) ORDER BY name LIMIT 100",
            (
                0 if archived else 1,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
            ),
        )
        return [self._customer(row) for row in rows]

    def get_customer(self, customer_id: int) -> Optional[Customer]:
        rows = self.db.execute_query(
            "SELECT * FROM customers WHERE id=?", (customer_id,)
        )
        return self._customer(rows[0]) if rows else None

    def create_customer(
        self, customer: Customer, user_id: Optional[int] = None
    ) -> Customer:
        self._require(user_id, "customers.create")
        self._validate_customer(customer)
        self._ensure_unique(customer)
        with self.db.transaction() as conn:
            customer_id = conn.execute(
                "INSERT INTO customers(name,company,phone,email,address,city,country,id_number,active) VALUES(?,?,?,?,?,?,?,?,1)",
                (
                    customer.name.strip(),
                    customer.company,
                    customer.phone,
                    customer.email,
                    customer.address,
                    customer.city,
                    customer.country,
                    customer.id_number,
                ),
            ).lastrowid
            conn.execute(
                "UPDATE customers SET customer_code=? WHERE id=?",
                (f"CUS-{customer_id:06d}", customer_id),
            )
        saved = self.get_customer(customer_id)
        if saved is None:
            raise RuntimeError("Failed to retrieve newly created customer")
        AuditService().log_action(
            "CUSTOMER_CREATED", "CUSTOMER", customer_id, user_id
        )
        self._sync("CREATE", saved)
        return saved

    def update_customer(
        self, customer: Customer, user_id: Optional[int] = None
    ) -> Customer:
        self._require(user_id, "customers.edit")
        if not customer.id or not self.get_customer(customer.id):
            raise ValueError("Customer was not found")
        self._validate_customer(customer)
        self._ensure_unique(customer, customer.id)
        self.db.execute_update(
            "UPDATE customers SET name=?,company=?,phone=?,email=?,address=?,city=?,country=?,id_number=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                customer.name.strip(),
                customer.company,
                customer.phone,
                customer.email,
                customer.address,
                customer.city,
                customer.country,
                customer.id_number,
                customer.id,
            ),
        )
        saved = self.get_customer(customer.id)
        if saved is None:
            raise RuntimeError("Failed to retrieve updated customer")
        AuditService().log_action(
            "CUSTOMER_EDITED", "CUSTOMER", customer.id, user_id
        )
        self._sync("UPDATE", saved)
        return saved

    def archive_customer(
        self, customer_id: int, user_id: Optional[int] = None
    ) -> None:
        self._require(user_id, "customers.archive")
        self._set_customer_active(customer_id, False, user_id)

    def restore_customer(
        self, customer_id: int, user_id: Optional[int] = None
    ) -> None:
        self._require(user_id, "customers.restore")
        self._set_customer_active(customer_id, True, user_id)

    def _set_customer_active(self, customer_id, active, user_id):
        if (
            self.db.execute_update(
                "UPDATE customers SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(active), customer_id),
            )
            != 1
        ):
            raise ValueError("Customer was not found")
        customer = self.get_customer(customer_id)
        AuditService().log_action(
            "CUSTOMER_RESTORED" if active else "CUSTOMER_ARCHIVED",
            "CUSTOMER",
            customer_id,
            user_id,
        )
        self._sync("UPDATE", customer)

    def create_vehicle(
        self, vehicle: Vehicle, user_id: Optional[int] = None
    ) -> Vehicle:
        self._require(user_id, "vehicles.create")
        if not self.get_customer(vehicle.customer_id):
            raise ValueError("Vehicle owner was not found")
        if not vehicle.registration_number.strip():
            raise ValueError("Registration number is required")
        if self.db.execute_query(
            "SELECT id FROM vehicles WHERE registration_number=?",
            (vehicle.registration_number.strip(),),
        ):
            raise ValueError("A vehicle with this registration already exists")
        self.db.execute_update(
            "INSERT INTO vehicles(customer_id,registration_number,make,model,year,engine,vin,color,notes,active) VALUES(?,?,?,?,?,?,?,?,?,1)",
            (
                vehicle.customer_id,
                vehicle.registration_number.strip().upper(),
                vehicle.make,
                vehicle.model,
                vehicle.year,
                vehicle.engine,
                vehicle.vin,
                vehicle.color,
                vehicle.notes,
            ),
        )
        saved = self.get_vehicle(self.db.get_last_insert_id())
        if saved is None:
            raise RuntimeError("Failed to retrieve newly created vehicle")
        AuditService().log_action(
            "VEHICLE_CREATED", "VEHICLE", saved.id, user_id
        )
        self._sync("CREATE", saved)
        return saved

    def get_vehicle(self, vehicle_id: int) -> Optional[Vehicle]:
        rows = self.db.execute_query(
            "SELECT * FROM vehicles WHERE id=?", (vehicle_id,)
        )
        return self._vehicle(rows[0]) if rows else None

    def update_vehicle(
        self, vehicle: Vehicle, user_id: Optional[int] = None
    ) -> Vehicle:
        self._require(user_id, "vehicles.edit")
        if not vehicle.id or not self.get_vehicle(vehicle.id):
            raise ValueError("Vehicle was not found")
        if not vehicle.registration_number.strip():
            raise ValueError("Registration number is required")
        duplicate = self.db.execute_query(
            "SELECT id FROM vehicles WHERE registration_number=? AND id<>?",
            (vehicle.registration_number.strip().upper(), vehicle.id),
        )
        if duplicate:
            raise ValueError("A vehicle with this registration already exists")
        self.db.execute_update(
            "UPDATE vehicles SET registration_number=?,make=?,model=?,year=?,engine=?,vin=?,color=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                vehicle.registration_number.strip().upper(),
                vehicle.make,
                vehicle.model,
                vehicle.year,
                vehicle.engine,
                vehicle.vin,
                vehicle.color,
                vehicle.notes,
                vehicle.id,
            ),
        )
        saved = self.get_vehicle(vehicle.id)
        if saved is None:
            raise RuntimeError("Failed to retrieve updated vehicle")
        AuditService().log_action(
            "VEHICLE_EDITED", "VEHICLE", vehicle.id, user_id
        )
        self._sync("UPDATE", saved)
        return saved

    def list_vehicles(
        self, customer_id: int, archived: bool = False
    ) -> list[Vehicle]:
        return [
            self._vehicle(row)
            for row in self.db.execute_query(
                "SELECT * FROM vehicles WHERE customer_id=? AND active=? ORDER BY registration_number",
                (customer_id, 0 if archived else 1),
            )
        ]

    def search_vehicles(
        self, term: str = "", archived: bool = False
    ) -> list[Vehicle]:
        pattern = f"%{term.strip()}%"
        rows = self.db.execute_query(
            "SELECT v.* FROM vehicles v JOIN customers c ON c.id=v.customer_id WHERE v.active=? AND (v.registration_number LIKE ? OR v.vin LIKE ? OR v.make LIKE ? OR v.model LIKE ? OR c.name LIKE ?) ORDER BY v.registration_number LIMIT 100",
            (
                0 if archived else 1,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
            ),
        )
        return [self._vehicle(row) for row in rows]

    def archive_vehicle(self, vehicle_id, user_id=None):
        self._require(user_id, "vehicles.archive")
        self._set_vehicle_active(vehicle_id, False, user_id)

    def restore_vehicle(self, vehicle_id, user_id=None):
        self._require(user_id, "vehicles.restore")
        self._set_vehicle_active(vehicle_id, True, user_id)

    def _set_vehicle_active(self, vehicle_id, active, user_id):
        if (
            self.db.execute_update(
                "UPDATE vehicles SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(active), vehicle_id),
            )
            != 1
        ):
            raise ValueError("Vehicle was not found")
        vehicle = self.get_vehicle(vehicle_id)
        AuditService().log_action(
            "VEHICLE_RESTORED" if active else "VEHICLE_ARCHIVED",
            "VEHICLE",
            vehicle_id,
            user_id,
        )
        self._sync("UPDATE", vehicle)

    def customer_profile(self, customer_id: int) -> dict:
        customer = self.get_customer(customer_id)
        if not customer:
            raise ValueError("Customer was not found")
        stats = self.db.execute_query(
            "SELECT COUNT(*) sales,COALESCE(SUM(total),0) purchases,MAX(created_at) last_purchase FROM sales WHERE customer_id=? AND status='COMPLETED'",
            (customer_id,),
        )[0]
        return {
            "customer": customer,
            "sales_count": stats["sales"],
            "total_purchases": stats["purchases"],
            "last_purchase": stats["last_purchase"],
            "vehicles": self.list_vehicles(customer_id),
            "sales": [
                dict(row)
                for row in self.db.execute_query(
                    "SELECT * FROM sales WHERE customer_id=? ORDER BY created_at DESC",
                    (customer_id,),
                )
            ],
            "invoices": [
                dict(row)
                for row in self.db.execute_query(
                    "SELECT * FROM invoices WHERE customer_id=? ORDER BY created_at DESC",
                    (customer_id,),
                )
            ],
            "returns": [
                dict(row)
                for row in self.db.execute_query(
                    "SELECT * FROM returns WHERE customer_id=? ORDER BY created_at DESC",
                    (customer_id,),
                )
            ],
        }

    def vehicle_history(self, vehicle_id: int) -> list[dict]:
        vehicle = self.get_vehicle(vehicle_id)
        if not vehicle:
            raise ValueError("Vehicle was not found")
        return [
            dict(row)
            for row in self.db.execute_query(
                "SELECT s.created_at date,s.invoice_number,si.product_id,si.quantity,si.line_total,p.part_no,p.description FROM sales s JOIN sale_items si ON si.sale_id=s.id LEFT JOIN products p ON p.id=si.product_id WHERE s.customer_id=? AND (s.vehicle_id=? OR (s.vehicle_id IS NULL AND s.vehicle_registration=?)) AND s.status='COMPLETED' ORDER BY s.created_at DESC,si.id",
                (vehicle.customer_id, vehicle_id, vehicle.registration_number),
            )
        ]

    def _ensure_unique(self, customer, ignore_id=None):
        if not customer.phone and not customer.email:
            return
        clauses = []
        values = []
        if customer.phone:
            clauses.append("phone=?")
            values.append(customer.phone)
        if customer.email:
            clauses.append("lower(email)=lower(?)")
            values.append(customer.email)
        query = "SELECT id FROM customers WHERE (" + " OR ".join(clauses) + ")"
        if ignore_id:
            query += " AND id<>?"
            values.append(ignore_id)
        if self.db.execute_query(query, tuple(values)):
            raise ValueError(
                "A customer with this phone number or email already exists"
            )

    @staticmethod
    def _validate_customer(customer):
        if not customer.name.strip():
            raise ValueError("Customer name is required")

    @staticmethod
    def _customer(row):
        return Customer(
            **{
                field: row[field]
                for field in Customer.__dataclass_fields__
                if field in row.keys()
            }
        )

    @staticmethod
    def _vehicle(row):
        return Vehicle(
            **{
                field: row[field]
                for field in Vehicle.__dataclass_fields__
                if field in row.keys()
            }
        )

    def _sync(self, operation, entity):
        self.sync.enqueue(
            "CUSTOMER" if isinstance(entity, Customer) else "VEHICLE",
            entity.id,
            operation,
            json.dumps(entity.to_dict()),
        )
        self.sync.request_background_sync()

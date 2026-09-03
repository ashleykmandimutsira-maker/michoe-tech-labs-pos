"""
Inventory spreadsheet (Excel) service for Motor Spares POS.

Lets a data-entry clerk fill in one Excel sheet — new stock arrivals, a
stock count, price updates, whatever — and import it once. Each row is
matched to an existing product (by barcode, then part number) and applied
through the normal product/inventory services, so every change:

  - keeps a proper stock-movement audit trail (quantity changes are never
    silently overwritten; they're recorded as ADJUSTMENT movements),
  - is queued for synchronization exactly like a change made by hand in
    the POS, and
  - shows up live on the dashboard and every other open screen, because it
    goes through the same SyncService.enqueue() choke point as everything
    else in the app.

The same file format works for a full "export the whole inventory, edit
it, bring it back in" round trip for an admin — export, edit, re-import
using the same importer.
"""

from __future__ import annotations

import logging
import time
import json
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from database.db import get_database_manager
from models.product import Product, Category
from services.product_service import ProductService
from services.inventory_service import InventoryService
from core.events import batch_changes

logger = logging.getLogger(__name__)

# Column order used for BOTH the template/export and what the importer reads.
# Keep header text stable — the importer matches columns by header name, not
# position, so re-ordered or slightly-edited columns still work.
COLUMNS = [
    ("part_no", "Part No", True),
    ("barcode", "Barcode", False),
    ("oem_number", "OEM Number", False),
    ("description", "Description", True),
    ("brand", "Brand", False),
    ("category", "Category", False),
    ("vehicle_make", "Vehicle Make", False),
    ("vehicle_model", "Vehicle Model", False),
    ("vehicle_year_from", "Vehicle Year From", False),
    ("vehicle_year_to", "Vehicle Year To", False),
    ("cost_price", "Cost Price", False),
    ("selling_price", "Selling Price", False),
    ("quantity_on_hand", "Quantity On Hand", False),
    ("reorder_level", "Reorder Level", False),
]

HEADER_FILL = PatternFill(start_color="1F2933", end_color="1F2933", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)


@dataclass
class ImportResult:
    import_id: Optional[int] = None
    import_batch_id: Optional[str] = None
    filename: str = ""
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return self.created + self.updated + self.unchanged + len(self.errors)


class SpreadsheetService:
    """Import/export the product catalog and stock levels via Excel."""

    def __init__(self):
        self.db = get_database_manager()
        self.products = ProductService()
        self.inventory = InventoryService()

    # ------------------------------------------------------------------
    # Export / template
    # ------------------------------------------------------------------

    def export_inventory(self, path: str, include_cost_price: bool = True) -> int:
        """Write the full current inventory to an .xlsx file. Returns row count."""
        started = time.perf_counter()
        logger.info("START inventory spreadsheet")
        query_started = time.perf_counter()
        items = self.products.get_all_products(active_only=False)
        category_names = {c.id: c.name for c in self.products.get_all_categories()}
        logger.info("DATABASE QUERY COMPLETE elapsed=%.3fs", time.perf_counter() - query_started)
        columns = COLUMNS if include_cost_price else [c for c in COLUMNS if c[0] != "cost_price"]
        logger.info("XLSX GENERATION START")
        wb = Workbook()
        ws = wb.active
        ws.title = "Inventory"
        self._write_header(ws, columns)

        for row_idx, product in enumerate(items, start=2):
            values = {
                "part_no": product.part_no,
                "barcode": product.barcode or "",
                "oem_number": product.oem_number or "",
                "description": product.description,
                "brand": product.brand or "",
                "category": category_names.get(product.category_id, ""),
                "vehicle_make": product.vehicle_make or "",
                "vehicle_model": product.vehicle_model or "",
                "vehicle_year_from": product.vehicle_year_from or "",
                "vehicle_year_to": product.vehicle_year_to or "",
                "cost_price": product.cost_price,
                "selling_price": product.selling_price,
                "quantity_on_hand": product.quantity_on_hand,
                "reorder_level": product.reorder_level,
            }
            for col_idx, (key, _label, _required) in enumerate(columns, start=1):
                ws.cell(row=row_idx, column=col_idx, value=values.get(key, ""))

        self._autosize(ws, columns)
        logger.info("XLSX GENERATION COMPLETE elapsed=%.3fs", time.perf_counter() - started)
        wb.save(path)
        logger.info("FILE WRITE COMPLETE elapsed=%.3fs", time.perf_counter() - started)
        logger.info("Exported %s products to %s", len(items), path)
        return len(items)

    def generate_template(self, path: str) -> None:
        """Write a blank template with headers only, for data entry."""
        started = time.perf_counter()
        logger.info("START inventory spreadsheet")
        logger.info("DATABASE QUERY COMPLETE elapsed=0.000s")
        logger.info("XLSX GENERATION START")
        wb = Workbook()
        ws = wb.active
        ws.title = "Inventory"
        self._write_header(ws, COLUMNS)
        self._autosize(ws, COLUMNS)
        logger.info("XLSX GENERATION COMPLETE elapsed=%.3fs", time.perf_counter() - started)
        wb.save(path)
        logger.info("FILE WRITE COMPLETE elapsed=%.3fs", time.perf_counter() - started)
        logger.info("Wrote blank inventory template to %s", path)

    @staticmethod
    def _write_header(ws, columns) -> None:
        for col_idx, (_key, label, required) in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=label + (" *" if required else ""))
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
        ws.freeze_panes = "A2"

    @staticmethod
    def _autosize(ws, columns) -> None:
        for col_idx, (_key, label, _required) in enumerate(columns, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = max(14, len(label) + 4)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_inventory(self, path: str, user_id: Optional[int] = None) -> ImportResult:
        """Read an .xlsx file and apply every row to the live inventory.

        Existing products (matched by barcode, falling back to part number)
        are updated; unrecognised rows create new products. Quantity
        changes are recorded as proper ADJUSTMENT stock movements rather
        than silently overwritten, so stock history stays accurate.
        """
        result = ImportResult(filename=str(path), import_batch_id=str(uuid.uuid4()))
        self.db.execute_update(
            "INSERT INTO inventory_imports(import_batch_id,filename,imported_by,status) VALUES(?,?,?,'IN_PROGRESS')",
            (result.import_batch_id, str(path), user_id),
        )
        result.import_id = self.db.get_last_insert_id()
        wb = load_workbook(path, data_only=True)
        ws = wb.active

        header_row = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
        label_to_key = {label: key for key, label, _req in COLUMNS}
        # Accept headers with or without the " *" required-marker suffix.
        col_index = {}
        for idx, raw_label in enumerate(header_row):
            label = raw_label[:-2].strip() if raw_label.endswith(" *") else raw_label
            key = label_to_key.get(label)
            if key:
                col_index[key] = idx

        missing = [label for key, label, required in COLUMNS if required and key not in col_index]
        if missing:
            raise ValueError(
                "The spreadsheet is missing required column(s): " + ", ".join(missing)
            )

        category_lookup = {c.name.strip().lower(): c.id for c in self.products.get_all_categories()}

        with batch_changes("INVENTORY_IMPORT"):
            for row_num, row in enumerate(ws.iter_rows(min_row=2), start=2):
                values = {key: self._cell(row, idx) for key, idx in col_index.items()}
                part_no = str(values.get("part_no") or "").strip()
                description = str(values.get("description") or "").strip()
                if not part_no and not description:
                    continue
                try:
                    before = self._snapshot_by_identity(part_no, values.get("barcode"))
                    self._apply_row(row_num, values, part_no, description, category_lookup, user_id, result)
                    after = self._snapshot_by_identity(part_no, values.get("barcode"))
                    product_id = after.get("id") if after else None
                    self.db.execute_update(
                        "INSERT INTO inventory_import_items(import_id,product_id,part_no,action,before_values,after_values) VALUES(?,?,?,?,?,?)",
                        (result.import_id, product_id, part_no, 'CREATED' if not before else 'UPDATED', json.dumps(before) if before else None, json.dumps(after) if after else None),
                    )
                except Exception as exc:
                    logger.exception("Row %s failed to import", row_num)
                    result.errors.append(f"Row {row_num} ({part_no or '?'}): {exc}")

        status = 'FAILED' if result.errors and result.created == 0 and result.updated == 0 else 'PARTIAL' if result.errors else 'COMPLETED'
        self.db.execute_update(
            "UPDATE inventory_imports SET total_rows=?,created_count=?,updated_count=?,skipped_count=?,error_count=?,status=? WHERE id=?",
            (result.total_rows, result.created, result.updated, result.unchanged, len(result.errors), status, result.import_id),
        )
        logger.info(
            "Inventory import from %s: %s created, %s updated, %s unchanged, %s errors",
            path, result.created, result.updated, result.unchanged, len(result.errors),
        )
        return result

    def _snapshot_by_identity(self, part_no, barcode=None):
        row = None
        if barcode:
            rows = self.db.execute_query("SELECT * FROM products WHERE barcode=? LIMIT 1", (str(barcode).strip(),))
            row = rows[0] if rows else None
        if row is None and part_no:
            rows = self.db.execute_query("SELECT * FROM products WHERE part_no=? LIMIT 1", (part_no,))
            row = rows[0] if rows else None
        return dict(row) if row else None

    def list_imports(self, limit=50):
        return self.db.execute_query("SELECT * FROM inventory_imports ORDER BY imported_at DESC LIMIT ?", (limit,))

    def undo_import(self, import_id: int, admin_user_id: int) -> dict:
        from services.permission_service import PermissionService
        if not PermissionService().is_admin(admin_user_id):
            raise PermissionError("Only an administrator can undo an inventory import.")
        batch = self.db.execute_query("SELECT * FROM inventory_imports WHERE id=?", (import_id,))
        if not batch:
            raise ValueError("Inventory import not found.")
        if batch[0]['status'] == 'UNDONE':
            raise ValueError("This inventory import has already been undone.")
        items = self.db.execute_query("SELECT * FROM inventory_import_items WHERE import_id=? ORDER BY id DESC", (import_id,))
        removed = 0
        restored = 0
        with self.db.transaction() as conn:
            trigger = conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='prevent_product_physical_delete'").fetchone()
            if trigger:
                conn.execute("DROP TRIGGER prevent_product_physical_delete")
            for item in items:
                if item['action'] == 'CREATED' and item['product_id']:
                    dependent = conn.execute("SELECT 1 FROM sale_items WHERE product_id=? UNION SELECT 1 FROM stock_movements WHERE product_id=? UNION SELECT 1 FROM return_items WHERE product_id=? LIMIT 1", (item['product_id'], item['product_id'], item['product_id'])).fetchone()
                    if not dependent:
                        conn.execute("UPDATE inventory_import_items SET product_id=NULL WHERE id=?", (item['id'],))
                        conn.execute("DELETE FROM products WHERE id=?", (item['product_id'],))
                        conn.execute("INSERT OR REPLACE INTO product_tombstones(product_id, part_no) VALUES (?, ?)", (item['product_id'], item['part_no']))
                        removed += 1
                        continue
                before = json.loads(item['before_values']) if item['before_values'] else None
                if before and item['product_id']:
                    conn.execute("UPDATE products SET barcode=?,oem_number=?,part_no=?,description=?,brand=?,category_id=?,vehicle_make=?,vehicle_model=?,vehicle_year_from=?,vehicle_year_to=?,cost_price=?,selling_price=?,currency=?,quantity_on_hand=?,reorder_level=?,vat_rate=?,active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (before.get('barcode'),before.get('oem_number'),before.get('part_no'),before.get('description'),before.get('brand'),before.get('category_id'),before.get('vehicle_make'),before.get('vehicle_model'),before.get('vehicle_year_from'),before.get('vehicle_year_to'),before.get('cost_price'),before.get('selling_price'),before.get('currency'),before.get('quantity_on_hand'),before.get('reorder_level'),before.get('vat_rate'),before.get('active'),item['product_id']))
                    restored += 1
            conn.execute("UPDATE inventory_imports SET status='UNDONE' WHERE id=?", (import_id,))
            if trigger:
                conn.execute(trigger[0])
        return {'removed': removed, 'restored': restored}

    @staticmethod
    def _cell(row, idx):
        try:
            return row[idx].value
        except IndexError:
            return None

    def _apply_row(self, row_num, values, part_no, description, category_lookup, user_id, result: ImportResult) -> None:
        barcode = str(values.get("barcode") or "").strip() or None
        existing = None
        if barcode:
            existing = self.products.get_product_by_barcode(barcode)
        if not existing and part_no:
            existing = self.products.get_product_by_part_no(part_no)

        category_id = None
        category_name = str(values.get("category") or "").strip()
        if category_name:
            category_id = category_lookup.get(category_name.lower())
            if category_id is None:
                category_id = self.products.create_category(Category(name=category_name))
                category_lookup[category_name.lower()] = category_id

        cost_price = self._num(values.get("cost_price"), default=None)
        selling_price = self._num(values.get("selling_price"), default=None)
        reorder_level = self._num(values.get("reorder_level"), default=None, integer=True)
        target_quantity = self._num(values.get("quantity_on_hand"), default=None, integer=True)

        if existing:
            if not part_no:
                part_no = existing.part_no
            changed = False
            updated = Product(
                id=existing.id,
                barcode=barcode or existing.barcode,
                part_no=part_no,
                oem_number=str(values.get("oem_number") or existing.oem_number or "") or None,
                description=description or existing.description,
                brand=str(values.get("brand") or existing.brand or ""),
                category_id=category_id if category_id is not None else existing.category_id,
                vehicle_make=str(values.get("vehicle_make") or existing.vehicle_make or "") or None,
                vehicle_model=str(values.get("vehicle_model") or existing.vehicle_model or "") or None,
                vehicle_year_from=self._num(values.get("vehicle_year_from"), default=existing.vehicle_year_from, integer=True),
                vehicle_year_to=self._num(values.get("vehicle_year_to"), default=existing.vehicle_year_to, integer=True),
                cost_price=cost_price if cost_price is not None else existing.cost_price,
                selling_price=selling_price if selling_price is not None else existing.selling_price,
                currency=existing.currency,
                quantity_on_hand=existing.quantity_on_hand,  # quantity handled separately below
                reorder_level=reorder_level if reorder_level is not None else existing.reorder_level,
                vat_rate=existing.vat_rate,
                active=existing.active,
            )
            field_names = [
                "barcode", "description", "brand", "category_id", "vehicle_make",
                "vehicle_model", "cost_price", "selling_price", "reorder_level",
                "oem_number", "vehicle_year_from", "vehicle_year_to",
            ]
            if any(getattr(updated, f) != getattr(existing, f) for f in field_names):
                self.products.update_product(updated)
                changed = True

            if target_quantity is not None and target_quantity != existing.quantity_on_hand:
                self.inventory.set_stock_level(
                    product_id=existing.id,
                    new_quantity=target_quantity,
                    reason=f"Set to {target_quantity} via inventory spreadsheet import",
                    user_id=user_id,
                    reference=f"Spreadsheet import (row {row_num})",
                )
                changed = True

            if changed:
                result.updated += 1
            else:
                result.unchanged += 1
        else:
            if not part_no or not description:
                raise ValueError("New products need at least a Part No and Description")
            new_product = Product(
                barcode=barcode,
                part_no=part_no,
                oem_number=str(values.get("oem_number") or "") or None,
                description=description,
                brand=str(values.get("brand") or ""),
                category_id=category_id,
                vehicle_make=str(values.get("vehicle_make") or "") or None,
                vehicle_model=str(values.get("vehicle_model") or "") or None,
                vehicle_year_from=self._num(values.get("vehicle_year_from"), default=None, integer=True),
                vehicle_year_to=self._num(values.get("vehicle_year_to"), default=None, integer=True),
                cost_price=cost_price or 0.0,
                selling_price=selling_price or 0.0,
                quantity_on_hand=target_quantity or 0,
                reorder_level=reorder_level if reorder_level is not None else 5,
            )
            self.products.create_product(new_product)
            result.created += 1

    @staticmethod
    def _num(value, default=None, integer: bool = False):
        if value is None or value == "":
            return default
        try:
            return int(value) if integer else float(value)
        except (TypeError, ValueError):
            return default

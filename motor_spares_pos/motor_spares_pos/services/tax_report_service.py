"""Database-backed tax and ZIMRA report preparation. Not FDMS fiscalisation."""

from database.db import get_database_manager
from openpyxl import Workbook


class TaxReportService:
    def __init__(self):
        self.db = get_database_manager()

    def summary(self, start: str, end: str) -> dict:
        params = (start, end)
        sales = self.db.execute_query(
            "SELECT COALESCE(SUM(subtotal),0) taxable_sales,COALESCE(SUM(vat_amount),0) output_vat,COALESCE(SUM(discount_amount),0) discounts,COALESCE(SUM(total),0) gross_sales,COUNT(*) invoices FROM sales WHERE status='COMPLETED' AND date(created_at) BETWEEN date(?) AND date(?)",
            params,
        )[0]
        returns = self.db.execute_query(
            "SELECT COALESCE(SUM(total_refund),0) refunds FROM returns WHERE status='COMPLETED' AND date(created_at) BETWEEN date(?) AND date(?)",
            params,
        )[0]
        payments = [
            dict(row)
            for row in self.db.execute_query(
                "SELECT payment_method method,COALESCE(SUM(amount),0) amount FROM payments p JOIN sales s ON s.id=p.sale_id WHERE s.status='COMPLETED' AND date(s.created_at) BETWEEN date(?) AND date(?) GROUP BY payment_method",
                params,
            )
        ]
        register = [
            dict(row)
            for row in self.db.execute_query(
                "SELECT invoice_number,created_at,customer_name,customer_phone,vehicle_registration,subtotal,vat_amount,total,status FROM invoices WHERE date(created_at) BETWEEN date(?) AND date(?) ORDER BY created_at",
                params,
            )
        ]
        return {
            "sales": dict(sales),
            "returns": float(returns["refunds"]),
            "net_sales": float(sales["gross_sales"])
            - float(returns["refunds"]),
            "payments": payments,
            "invoice_register": register,
            "zero_rated_sales": 0.0,
            "exempt_sales": 0.0,
        }

    def export_xlsx(self, path: str, start: str, end: str) -> int:
        """Export the real invoice register and tax summary to an XLSX workbook."""
        report = self.summary(start, end)
        workbook = Workbook()
        summary = workbook.active
        summary.title = "Tax Summary"
        summary.append(["Tax & ZIMRA Report", f"{start} to {end}"])
        for label, value in [
            ("Invoices", report["sales"]["invoices"]),
            ("Gross sales", report["sales"]["gross_sales"]),
            ("Taxable sales", report["sales"]["taxable_sales"]),
            ("Output VAT", report["sales"]["output_vat"]),
            ("Discounts", report["sales"]["discounts"]),
            ("Returns / credit notes", report["returns"]),
            ("Net sales", report["net_sales"]),
        ]:
            summary.append([label, value])
        register = workbook.create_sheet("Invoice Register")
        fields = [
            "invoice_number",
            "created_at",
            "customer_name",
            "customer_phone",
            "vehicle_registration",
            "subtotal",
            "vat_amount",
            "total",
            "status",
        ]
        register.append(fields)
        for row in report["invoice_register"]:
            register.append([row.get(field) for field in fields])
        workbook.save(path)
        return len(report["invoice_register"])

"""Reusable, database-backed analytics for the POS dashboard and reports.

The UI deliberately contains no analytics SQL.  Every chart, KPI and ranking
is sourced through this service so the same definitions are used in reports.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from database.db import get_database_manager


class AnalyticsService:
    """Read-only business analytics built on the existing SQLite schema."""

    PERIODS = {"today", "week", "month", "year"}

    def __init__(self):
        self.db = get_database_manager()

    @staticmethod
    def _bounds(period: str = "today", start: Optional[str] = None,
                end: Optional[str] = None) -> tuple[str, str]:
        """Return ISO date bounds (inclusive start, exclusive end)."""
        if period == "custom" and start:
            begin = datetime.fromisoformat(start).date()
            finish = datetime.fromisoformat(end).date() + timedelta(days=1) if end else begin + timedelta(days=1)
            return begin.isoformat(), finish.isoformat()
        today = date.today()
        if period == "week":
            begin = today - timedelta(days=today.weekday())
        elif period == "month":
            begin = today.replace(day=1)
        elif period == "year":
            begin = today.replace(month=1, day=1)
        else:
            begin = today
        return begin.isoformat(), (today + timedelta(days=1)).isoformat()

    def _where(self, period: str, start: Optional[str] = None, end: Optional[str] = None) -> tuple[str, tuple]:
        begin, finish = self._bounds(period, start, end)
        return "s.created_at >= ? AND s.created_at < ? AND s.status = 'COMPLETED'", (begin, finish)

    def get_sales_summary(self, period: str = "today", start: Optional[str] = None,
                          end: Optional[str] = None) -> dict:
        where, params = self._where(period, start, end)
        sales_row = self.db.execute_query(f"SELECT COALESCE(SUM(s.total), 0) revenue, COUNT(*) transactions FROM sales s WHERE {where}", params)[0]
        item_row = self.db.execute_query(f"""
            SELECT COALESCE(SUM(si.quantity), 0) units_sold,
                   COALESCE(SUM((si.unit_price - p.cost_price) * si.quantity), 0) profit
            FROM sales s LEFT JOIN sale_items si ON si.sale_id = s.id LEFT JOIN products p ON p.id = si.product_id
            WHERE {where}
        """, params)[0]
        revenue = float(sales_row["revenue"] or 0)
        transactions = int(sales_row["transactions"] or 0)
        returns = self.get_return_summary(period, start, end)["count"]
        return {
            "revenue": revenue,
            "profit": float(item_row["profit"] or 0),
            "transactions": transactions,
            "units_sold": int(item_row["units_sold"] or 0),
            "average_transaction": revenue / transactions if transactions else 0.0,
            "returns": returns,
        }

    def get_sales_trend(self, metric: str = "revenue", period: str = "today",
                        start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
        """Return ordered points suitable for a line chart."""
        where, params = self._where(period, start, end)
        metric_expr = {"profit": "SUM((si.unit_price - p.cost_price) * si.quantity)", "units_sold": "SUM(si.quantity)"}.get(metric)
        if period == "today":
            group = "strftime('%H', s.created_at)"
            label = "strftime('%H:00', s.created_at)"
        elif period == "week":
            group = "date(s.created_at)"
            label = "strftime('%a', s.created_at)"
        elif period == "year":
            group = "strftime('%Y-%m', s.created_at)"
            label = "strftime('%b', s.created_at)"
        else:
            group = "date(s.created_at)"
            label = "strftime('%d %b', s.created_at)"
        if metric in ("revenue", "transactions"):
            expr = "SUM(s.total)" if metric == "revenue" else "COUNT(*)"
            rows = self.db.execute_query(f"SELECT {label} label, {expr} value FROM sales s WHERE {where} GROUP BY {group} ORDER BY {group}", params)
        else:
            rows = self.db.execute_query(f"""
                SELECT {label} label, {metric_expr} value
                FROM sales s LEFT JOIN sale_items si ON si.sale_id = s.id LEFT JOIN products p ON p.id = si.product_id
                WHERE {where} GROUP BY {group} ORDER BY {group}
            """, params)
        return [{"label": row["label"] or "", "value": float(row["value"] or 0)} for row in rows]

    def get_transaction_count(self, period: str = "today") -> int:
        return self.get_sales_summary(period)["transactions"]

    def get_units_sold(self, period: str = "today") -> int:
        return self.get_sales_summary(period)["units_sold"]

    def get_average_transaction_value(self, period: str = "today") -> float:
        return self.get_sales_summary(period)["average_transaction"]

    def get_top_products(self, period: str = "year", limit: int = 10, start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
        where, params = self._where(period, start, end)
        rows = self.db.execute_query(f"""
            SELECT p.part_no, p.description, COALESCE(p.brand, '') brand,
                   COALESCE(p.vehicle_make || ' ' || p.vehicle_model, '') vehicle,
                   SUM(si.quantity) quantity_sold,
                   SUM(si.line_total) revenue,
                   SUM((si.unit_price - p.cost_price) * si.quantity) profit
            FROM sales s
            JOIN sale_items si ON si.sale_id = s.id
            JOIN products p ON p.id = si.product_id
            WHERE {where}
            GROUP BY p.id
            ORDER BY quantity_sold DESC, revenue DESC
            LIMIT ?
        """, params + (limit,))
        return [dict(row) for row in rows]

    def get_vehicle_sales(self, period: str = "year", make: str = "", model: str = "", start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
        where, params = self._where(period, start, end)
        extra, extra_params = "", []
        if make:
            extra += " AND p.vehicle_make = ?"; extra_params.append(make)
        if model:
            extra += " AND p.vehicle_model = ?"; extra_params.append(model)
        rows = self.db.execute_query(f"""
            SELECT COALESCE(p.vehicle_make, 'Unspecified') make,
                   COALESCE(p.vehicle_model, 'Unspecified') model,
                   SUM(si.quantity) quantity_sold, SUM(si.line_total) revenue,
                   SUM((si.unit_price - p.cost_price) * si.quantity) profit
            FROM sales s JOIN sale_items si ON si.sale_id = s.id JOIN products p ON p.id = si.product_id
            WHERE {where}{extra}
            GROUP BY p.vehicle_make, p.vehicle_model ORDER BY revenue DESC
        """, params + tuple(extra_params))
        return [dict(row) for row in rows]

    def get_brand_sales(self, period: str = "year", limit: int = 10, start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
        where, params = self._where(period, start, end)
        rows = self.db.execute_query(f"""
            SELECT COALESCE(p.brand, 'Unbranded') brand, SUM(si.quantity) units_sold,
                   SUM(si.line_total) revenue, SUM((si.unit_price - p.cost_price) * si.quantity) profit
            FROM sales s JOIN sale_items si ON si.sale_id = s.id JOIN products p ON p.id = si.product_id
            WHERE {where} GROUP BY p.brand ORDER BY revenue DESC LIMIT ?
        """, params + (limit,))
        return [dict(row) for row in rows]

    def get_inventory_summary(self) -> dict:
        row = self.db.execute_query("""
            SELECT COUNT(*) total_products, COALESCE(SUM(quantity_on_hand), 0) units_in_stock,
                   COALESCE(SUM(cost_price * quantity_on_hand), 0) stock_cost_value,
                   COALESCE(SUM(selling_price * quantity_on_hand), 0) stock_selling_value,
                   COALESCE(SUM((selling_price - cost_price) * quantity_on_hand), 0) potential_profit,
                   COALESCE(SUM(CASE WHEN quantity_on_hand > 0 AND quantity_on_hand <= reorder_level THEN 1 ELSE 0 END), 0) low_stock,
                   COALESCE(SUM(CASE WHEN quantity_on_hand = 0 THEN 1 ELSE 0 END), 0) out_of_stock
            FROM products WHERE active = 1
        """)[0]
        return dict(row)

    def get_low_stock_products(self, limit: int = 20) -> list[dict]:
        rows = self.db.execute_query("""
            SELECT part_no, description, COALESCE(brand, '') brand,
                   TRIM(COALESCE(vehicle_make, '') || ' ' || COALESCE(vehicle_model, '')) vehicle,
                   quantity_on_hand current_stock, reorder_level,
                   CASE WHEN quantity_on_hand = 0 THEN 'OUT OF STOCK' ELSE 'LOW STOCK' END status
            FROM products WHERE active = 1 AND quantity_on_hand <= reorder_level
            ORDER BY quantity_on_hand ASC, description LIMIT ?
        """, (limit,))
        return [dict(row) for row in rows]

    def get_return_summary(self, period: str = "today", start: Optional[str] = None,
                           end: Optional[str] = None) -> dict:
        begin, finish = self._bounds(period, start, end)
        row = self.db.execute_query("""
            SELECT COUNT(*) count, COALESCE(SUM(total_refund), 0) value
            FROM returns WHERE created_at >= ? AND created_at < ? AND status != 'CANCELLED'
        """, (begin, finish))[0]
        top = self.db.execute_query("""
            SELECT p.description product, SUM(ri.quantity) quantity
            FROM returns r JOIN return_items ri ON ri.return_id = r.id JOIN products p ON p.id = ri.product_id
            WHERE r.created_at >= ? AND r.created_at < ? AND r.status != 'CANCELLED'
            GROUP BY p.id ORDER BY quantity DESC LIMIT 5
        """, (begin, finish))
        return {"count": int(row["count"] or 0), "value": float(row["value"] or 0), "top_products": [dict(x) for x in top]}

    def get_payment_method_sales(self, period: str = "year", start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
        where, params = self._where(period, start, end)
        rows = self.db.execute_query(f"""
            SELECT COALESCE(p.payment_method, 'Unknown') method, SUM(p.amount) amount
            FROM sales s JOIN payments p ON p.sale_id = s.id WHERE {where}
            GROUP BY p.payment_method ORDER BY amount DESC
        """, params)
        return [dict(row) for row in rows]

    def get_recent_transactions(self, limit: int = 12) -> list[dict]:
        rows = self.db.execute_query("""
            SELECT s.invoice_number invoice, s.created_at date,
                   COALESCE(s.customer_name, 'Walk-in customer') customer,
                   COALESCE(u.full_name, 'Unknown cashier') cashier, s.total amount,
                   COALESCE((SELECT payment_method FROM payments WHERE sale_id = s.id LIMIT 1), 'Unknown') payment,
                   s.status status
            FROM sales s LEFT JOIN users u ON u.id = s.user_id
            ORDER BY s.created_at DESC LIMIT ?
        """, (limit,))
        return [dict(row) for row in rows]

    def get_daily_sales_report(self, start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
        """Return daily sales, returns, net sales, and profit from SQLite."""
        begin = start or date.today().isoformat()
        finish = end or (date.today() + timedelta(days=1)).isoformat()
        rows = self.db.execute_query("""
            SELECT date(s.created_at) day, COUNT(DISTINCT s.id) sales,
                   COALESCE(SUM(s.total), 0) gross_sales,
                   COALESCE(SUM((si.unit_price - p.cost_price) * si.quantity), 0) profit
            FROM sales s LEFT JOIN sale_items si ON si.sale_id=s.id LEFT JOIN products p ON p.id=si.product_id
            WHERE s.created_at >= ? AND s.created_at < ? AND s.status='COMPLETED'
            GROUP BY date(s.created_at) ORDER BY day
        """, (begin, finish))
        result = []
        for row in rows:
            returns = self.db.execute_query("SELECT COALESCE(SUM(total_refund),0) value FROM returns WHERE date(created_at)=? AND status != 'CANCELLED'", (row['day'],))[0]['value']
            item = dict(row); item['returns'] = float(returns or 0); item['net_sales'] = float(item['gross_sales'] or 0) - item['returns']; result.append(item)
        return result

    def get_stock_report(self) -> list[dict]:
        rows = self.db.execute_query("""
            SELECT description, part_no, quantity_on_hand current_stock, reorder_level,
                   cost_price * quantity_on_hand stock_value,
                   CASE WHEN quantity_on_hand=0 THEN 'OUT OF STOCK' WHEN quantity_on_hand <= reorder_level THEN 'LOW STOCK' ELSE 'IN STOCK' END stock_status
            FROM products WHERE active=1 ORDER BY description
        """)
        return [dict(row) for row in rows]

    def get_customer_sales(self) -> list[dict]:
        rows = self.db.execute_query("""
            SELECT COALESCE(customer_name, 'Walk-in customer') customer, COUNT(*) purchases,
                   COALESCE(SUM(total),0) total_spent FROM sales
            WHERE status='COMPLETED' GROUP BY customer_id, customer_name ORDER BY total_spent DESC
        """)
        return [dict(row) for row in rows]

    def get_returns_report(self) -> list[dict]:
        rows = self.db.execute_query("""
            SELECT r.return_number, r.original_invoice_number invoice, p.description product,
                   ri.quantity, r.total_refund refund, r.reason, r.user_id, r.created_at
            FROM returns r JOIN return_items ri ON ri.return_id=r.id JOIN products p ON p.id=ri.product_id
            ORDER BY r.created_at DESC
        """)
        return [dict(row) for row in rows]

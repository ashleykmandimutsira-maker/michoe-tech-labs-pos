"""Credit-note document rendering from existing persisted return data."""
from services.returns_service import ReturnsService


class CreditNoteService:
    def render_html(self, return_id: int) -> str:
        return_obj = ReturnsService().get_return_by_id(return_id)
        if not return_obj:
            raise ValueError('Return was not found')
        rows = ''.join(f'<tr><td>{item.product_id}</td><td>{item.quantity}</td><td>{item.unit_price:.2f}</td><td>{item.line_total:.2f}</td></tr>' for item in return_obj.items)
        return f'''<h1>Credit Note / Return</h1><p><b>{return_obj.return_number}</b><br>Original invoice: {return_obj.original_invoice_number}<br>Customer: {return_obj.customer_name}<br>Phone: {return_obj.customer_phone or ''}<br>Status: {return_obj.status}</p><table border="1" cellspacing="0" cellpadding="5"><tr><th>Product ID</th><th>Quantity</th><th>Unit Price</th><th>Total</th></tr>{rows}</table><p>VAT impact: {return_obj.vat_amount:.2f}<br><b>Refund total: {return_obj.total_refund:.2f}</b><br>Reason: {return_obj.reason or ''}<br>Approved by: {return_obj.authorized_by or ''}</p><p>This document is not an FDMS fiscal credit note.</p>'''
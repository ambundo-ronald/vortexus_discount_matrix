"""Resolve general Standard Selling prices without trusting transaction price fields."""
import frappe
from frappe.utils import getdate, flt


def reference_rate(doc, row):
    price_list = frappe.get_cached_doc('Price List', 'Standard Selling')
    if not price_list.enabled or not price_list.selling:
        frappe.throw('Standard Selling must be enabled for selling.')
    # Fail explicitly rather than trust editable transaction exchange rates.
    if price_list.currency != doc.currency:
        frappe.throw('Discount Matrix currently requires the transaction currency to match Standard Selling.')
    day = getdate(doc.get('transaction_date') or doc.get('posting_date'))
    stock_uom = frappe.db.get_value('Item', row.item_code, 'stock_uom')
    conversion = 1 if row.uom == stock_uom else frappe.db.get_value(
        'UOM Conversion Detail', {'parent': row.item_code, 'parenttype': 'Item', 'uom': row.uom}, 'conversion_factor'
    )
    if not conversion:
        template = frappe.db.get_value('Item', row.item_code, 'variant_of')
        if template:
            conversion = frappe.db.get_value('UOM Conversion Detail',
                {'parent': template, 'parenttype': 'Item', 'uom': row.uom}, 'conversion_factor')
    if not conversion or abs(flt(conversion) - flt(row.conversion_factor)) > 1e-9:
        frappe.throw(f'Row {row.idx}: UOM conversion must match the Item master.')
    prices = frappe.get_all('Item Price', filters={'item_code': row.item_code, 'price_list': 'Standard Selling', 'selling': 1},
        fields=['name', 'uom', 'price_list_rate', 'currency', 'customer', 'supplier', 'batch_no', 'valid_from', 'valid_upto', 'packing_unit'])
    candidates = [p for p in prices if not p.customer and not p.supplier and not p.batch_no
        and (not p.valid_from or getdate(p.valid_from) <= day)
        and (not p.valid_upto or getdate(p.valid_upto) >= day)
        and p.currency == doc.currency]
    exact = [p for p in candidates if p.uom == row.uom]
    selected = exact or [p for p in candidates if p.uom == stock_uom]
    if not selected:
        frappe.throw(f'Row {row.idx}: no valid general Standard Selling price for {row.item_code}.')
    latest = max(getdate(p.valid_from or '1900-01-01') for p in selected)
    selected = [p for p in selected if getdate(p.valid_from or '1900-01-01') == latest]
    if len(selected) != 1 or flt(selected[0].price_list_rate) <= 0:
        frappe.throw(f'Row {row.idx}: ambiguous or invalid Standard Selling price; resolve Item Price records.')
    price = selected[0]
    if flt(price.packing_unit) not in (0, 1):
        frappe.throw(f'Row {row.idx}: packing-unit prices need review before using Discount Matrix.')
    return flt(price.price_list_rate) * (1 if exact else flt(conversion)), price.name

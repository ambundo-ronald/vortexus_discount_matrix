"""Resolve general Standard Selling prices and valuation costs without trusting transaction price fields."""
import math
import frappe
from frappe.utils import getdate, flt


def uom_conversion(row):
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
    return stock_uom, conversion


def reference_rate(doc, row):
    day = getdate(doc.get('transaction_date') or doc.get('posting_date'))
    stock_uom, conversion = uom_conversion(row)
    price, exact, currency = standard_selling_price(row.item_code, row.uom, stock_uom, day, f'Row {row.idx}')
    fx = selling_exchange_rate(currency, doc.currency, day)
    return flt(price.price_list_rate) * (1 if exact else flt(conversion)) * fx, price.name


def standard_selling_price(item_code, uom, stock_uom, day, label, fail=None):
    """(Item Price row, exact UOM match, price list currency) for the general Standard Selling price."""
    fail = fail or frappe.throw
    price_list = frappe.get_cached_doc('Price List', 'Standard Selling')
    if not price_list.enabled or not price_list.selling:
        fail('Standard Selling must be enabled for selling.')
    prices = frappe.get_all('Item Price', filters={'item_code': item_code, 'price_list': 'Standard Selling', 'selling': 1},
        fields=['name', 'uom', 'price_list_rate', 'currency', 'customer', 'supplier', 'batch_no', 'valid_from', 'valid_upto', 'packing_unit'])
    candidates = [p for p in prices if not p.customer and not p.supplier and not p.batch_no
        and (not p.valid_from or getdate(p.valid_from) <= day)
        and (not p.valid_upto or getdate(p.valid_upto) >= day)
        and p.currency == price_list.currency]
    exact = [p for p in candidates if p.uom == uom]
    selected = exact or [p for p in candidates if p.uom == stock_uom]
    if not selected:
        fail(f'{label}: no valid general Standard Selling price for {item_code}.')
    latest = max(getdate(p.valid_from or '1900-01-01') for p in selected)
    selected = [p for p in selected if getdate(p.valid_from or '1900-01-01') == latest]
    if len(selected) != 1 or flt(selected[0].price_list_rate) <= 0:
        fail(f'{label}: ambiguous or invalid Standard Selling price; resolve Item Price records.')
    price = selected[0]
    if flt(price.packing_unit) not in (0, 1):
        fail(f'{label}: packing-unit prices need review before using Discount Matrix.')
    return price, bool(exact), price_list.currency


def stock_cost(item_code, warehouse=None):
    """(cost per stock UOM in company currency, source), or (None, None) when no cost is known.

    Order: warehouse valuation rate, Item valuation rate, Item last purchase rate."""
    lookups = [('Item Valuation Rate', lambda: frappe.db.get_value('Item', item_code, 'valuation_rate')),
               ('Last Purchase Rate', lambda: frappe.db.get_value('Item', item_code, 'last_purchase_rate'))]
    if warehouse:
        lookups.insert(0, ('Warehouse Valuation Rate', lambda: frappe.db.get_value(
            'Bin', {'item_code': item_code, 'warehouse': warehouse}, 'valuation_rate')))
    for source, lookup in lookups:
        cost = flt(lookup())
        if math.isfinite(cost) and cost > 0:
            return cost, source
    return None, None


def cost_rate(doc, row):
    """(cost per transaction UOM in the document currency, cost source) for margin checks."""
    day = getdate(doc.get('transaction_date') or doc.get('posting_date'))
    _, conversion = uom_conversion(row)
    cost, source = stock_cost(row.item_code, row.get('warehouse'))
    if cost is None:
        frappe.throw(f'Row {row.idx}: {row.item_code} has no valuation rate or last purchase rate, so its margin '
                     'cannot be checked. Receive or purchase stock, or set the Item valuation rate.')
    company_currency = frappe.get_cached_value('Company', doc.get('company'), 'default_currency')
    fx = selling_exchange_rate(company_currency, doc.currency, day)
    return cost * flt(conversion) * fx, source


def selling_exchange_rate(from_currency, to_currency, day, fail=None):
    fail = fail or frappe.throw
    if not from_currency or not to_currency or not day:
        fail('Discount Matrix requires currencies and a document date for currency conversion.')
    if from_currency == to_currency:
        return 1.0
    # Resolve independently of editable transaction conversion_rate and
    # plc_conversion_rate; honor ERPNext selling-rate and stale-rate settings.
    from erpnext.setup.utils import get_exchange_rate
    rate = flt(get_exchange_rate(from_currency, to_currency, day, args='for_selling'))
    if not math.isfinite(rate) or rate <= 0:
        fail(f'Discount Matrix: no valid selling exchange rate from {from_currency} to {to_currency} on {day}. Configure Currency Exchange and retry.')
    return rate

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


FIFO_SOURCE, COMPANY_SOURCE, PURCHASE_SOURCE = 'System cost (FIFO)', 'Company stock valuation', 'Last Purchase Rate'


def fifo_cost(item_code, warehouse, stock_qty, day, company):
    """Cost per stock UOM ERPNext would book for this quantity leaving this warehouse now.

    Uses ERPNext's own incoming-rate calculation (FIFO/LIFO stock queue or moving
    average, per the Item/Company valuation method). Only called when the warehouse
    holds stock, so ERPNext's Item-master fallbacks are not reached."""
    qty = flt(frappe.db.get_value('Bin', {'item_code': item_code, 'warehouse': warehouse}, 'actual_qty'))
    if not math.isfinite(qty) or qty <= 0:
        return 0.0
    try:
        from erpnext.stock.utils import get_incoming_rate
        from frappe.utils import nowtime
        args = dict(item_code=item_code, warehouse=warehouse, posting_date=day, posting_time=nowtime(),
                    qty=-abs(flt(stock_qty) or 1), company=company, voucher_type='Delivery Note',
                    allow_zero_valuation=1)
        try:
            rate = get_incoming_rate(args, raise_error_if_no_rate=False, fallbacks=False)
        except TypeError:  # ERPNext releases without the fallbacks argument
            rate = get_incoming_rate(args, raise_error_if_no_rate=False)
        rate = flt(rate)
    except ImportError:
        rate = 0.0
    except Exception:  # never block a sale because the costing helper failed; fall back instead
        frappe.log_error(title='VDM: FIFO cost lookup failed', message=frappe.get_traceback()
                         if hasattr(frappe, 'get_traceback') else '')
        rate = 0.0
    return rate if math.isfinite(rate) and rate > 0 else 0.0


def company_valuation(item_code, company):
    """Weighted stock value per unit across the company's warehouses holding stock."""
    if not company:
        return 0.0
    rows = frappe.db.sql("""
        SELECT SUM(b.stock_value) AS value, SUM(b.actual_qty) AS qty
        FROM `tabBin` b JOIN `tabWarehouse` w ON w.name = b.warehouse
        WHERE b.item_code = %s AND w.company = %s AND b.actual_qty > 0""", (item_code, company), as_dict=True)
    row = rows[0] if rows else {}
    qty, value = flt(row.get('qty')), flt(row.get('value'))
    rate = value / qty if qty > 0 else 0.0
    return rate if math.isfinite(rate) and rate > 0 else 0.0


def stock_cost(item_code, warehouse=None, stock_qty=1, day=None, company=None, basis=None):
    """(cost per stock UOM in company currency, source), or (None, None) when no cost is known.

    Order: ERPNext FIFO cost in the warehouse, company-wide stock valuation, last purchase
    rate. The Item master valuation rate is not used: stock transactions do not update it.
    With "Higher of system cost and last purchase rate" the last purchase rate wins when higher."""
    from vortexus_discount_matrix.core import HIGHER_COST
    if not day:
        from frappe.utils import nowdate
        day = getdate(nowdate())
    purchase = flt(frappe.db.get_value('Item', item_code, 'last_purchase_rate'))
    purchase = purchase if math.isfinite(purchase) and purchase > 0 else 0.0
    cost, source = 0.0, None
    if warehouse:
        cost, source = fifo_cost(item_code, warehouse, stock_qty, day, company), FIFO_SOURCE
    if not cost:
        cost, source = company_valuation(item_code, company), COMPANY_SOURCE
    if not cost:
        cost, source = purchase, PURCHASE_SOURCE
    if not cost:
        return None, None
    if basis == HIGHER_COST and purchase > cost:
        return purchase, PURCHASE_SOURCE + ' (higher than system cost)'
    return cost, source


def cost_rate(doc, row, basis=None):
    """(cost per transaction UOM in the document currency, cost source), or (None, None) if unknown."""
    day = getdate(doc.get('transaction_date') or doc.get('posting_date'))
    _, conversion = uom_conversion(row)
    stock_qty = flt(row.get('stock_qty')) or flt(row.get('qty')) * flt(conversion)
    cost, source = stock_cost(row.item_code, row.get('warehouse'), stock_qty, day, doc.get('company'), basis)
    if cost is None:
        return None, None
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

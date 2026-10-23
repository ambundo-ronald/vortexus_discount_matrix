"""VDM Price Simulation: project margin and profit for proposed Standard Selling prices.

Read-only against live data: prices, costs, matrix limits and sales history are
read; nothing outside the simulation document is changed.
"""
import json
import frappe
from frappe.utils import flt, getdate, nowdate
from vortexus_discount_matrix.prices import standard_selling_price, stock_cost, selling_exchange_rate
from vortexus_discount_matrix.simulation_math import simulate_item, history_by_column, HISTORICAL

MAX_ITEMS = 500


class Unavailable(Exception):
    pass


def unavailable(message):
    raise Unavailable(message)


def validate(doc, method=None):
    if not doc.get('company'):
        frappe.throw('Select a Company.')
    if not doc.get('from_date') or not doc.get('to_date'):
        frappe.throw('Select the sales history period.')
    if getdate(doc.from_date) > getdate(doc.to_date):
        frappe.throw('The sales history start date must be on or before the end date.')
    seen = set()
    for row in doc.get('items') or []:
        if row.item_code in seen:
            frappe.throw(f'Item {row.item_code} appears more than once.')
        seen.add(row.item_code)
    refresh(doc)


def refresh(doc):
    """Reload system data for every row and recalculate. Proposed prices are kept."""
    from vortexus_discount_matrix.settings import customer_mappings, matrix_tables
    discounts, margins = matrix_tables()
    mappings = customer_mappings()
    rows = doc.get('items') or []
    history = history_by_column(sales_history(doc.company, doc.from_date, doc.to_date,
                                              [r.item_code for r in rows]), mappings)
    company_currency = frappe.get_cached_value('Company', doc.company, 'default_currency')
    day = getdate(nowdate())
    basis = doc.get('projection_basis') or HISTORICAL
    totals = dict(history_revenue=0.0, history_profit=0.0, projected_revenue=0.0, projected_profit=0.0)
    for row in rows:
        item = frappe.db.get_value('Item', row.item_code, ['item_name', 'item_group', 'stock_uom'], as_dict=True) or {}
        row.item_name, row.item_group, row.stock_uom = item.get('item_name'), item.get('item_group'), item.get('stock_uom')
        warnings = []
        try:
            price, _, currency = standard_selling_price(row.item_code, row.stock_uom, row.stock_uom, day,
                                                        row.item_code, fail=unavailable)
            row.current_price = flt(price.price_list_rate) * selling_exchange_rate(currency, company_currency, day,
                                                                                  fail=unavailable)
        except Unavailable as exc:
            row.current_price = 0
            warnings.append(str(exc))
        if not flt(row.proposed_price) and flt(row.current_price):
            row.proposed_price = row.current_price
        cost, row.cost_source = stock_cost(row.item_code, doc.get('warehouse'))
        row.cost = cost or 0
        result = simulate_item(flt(row.proposed_price), cost, history.get(row.item_code, {}),
                               discounts.get(row.item_group, {}), margins.get(row.item_group, {}), basis)
        if row.item_group not in discounts:
            warnings.append('Item Group is not in the discount matrix: no maximum discount applies.')
        row.price_change = ((flt(row.proposed_price) / flt(row.current_price) - 1) * 100
                            if flt(row.current_price) and flt(row.proposed_price) else 0)
        row.history_qty = result['history_qty']
        row.history_revenue = result['history_revenue']
        row.history_profit = result['history_profit'] or 0
        row.projected_revenue = result['projected_revenue']
        row.projected_profit = result['projected_profit'] or 0
        row.projected_margin = result['projected_margin'] or 0
        row.lowest_floor_margin = result['lowest_floor_margin'] or 0
        row.warnings = '\n'.join(warnings + result['warnings'])
        row.column_detail = json.dumps(result['columns'])
        for key in totals:
            totals[key] += flt(row.get(key))
    for key, value in totals.items():
        doc.set(key, value)
    doc.projected_margin = (totals['projected_profit'] / totals['projected_revenue'] * 100
                            if totals['projected_revenue'] else 0)


def sales_history(company, from_date, to_date, item_codes):
    """Submitted, non-return Sales Invoice lines per item and customer group, per stock UOM in company currency."""
    if not item_codes:
        return []
    return frappe.db.sql("""
        SELECT sii.item_code, si.customer_group,
            SUM(sii.stock_qty) AS qty,
            SUM(sii.base_net_amount) AS revenue,
            SUM(CASE WHEN sii.base_price_list_rate > 0 THEN sii.base_price_list_rate * sii.qty ELSE 0 END) AS list_amount,
            SUM(CASE WHEN sii.base_price_list_rate > 0 THEN sii.base_net_amount ELSE 0 END) AS list_revenue
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1 AND si.is_return = 0 AND si.company = %(company)s
            AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
            AND sii.item_code IN %(items)s
        GROUP BY sii.item_code, si.customer_group
    """, dict(company=company, from_date=from_date, to_date=to_date, items=tuple(item_codes)), as_dict=True)


@frappe.whitelist()
def load_items(name):
    """Add matrix items (optionally one Item Group, optionally only items sold in the period)."""
    doc = frappe.get_doc('VDM Price Simulation', name)
    doc.check_permission('write')
    from vortexus_discount_matrix.settings import matrix_tables
    discounts, _ = matrix_tables()
    groups = [doc.item_group] if doc.get('item_group') else list(discounts)
    if not groups:
        frappe.throw('The discount matrix in VDM Settings has no Item Groups. Select an Item Group to load.')
    items = frappe.get_all('Item', filters={'item_group': ['in', groups], 'disabled': 0, 'is_sales_item': 1},
                           pluck='name', order_by='item_group asc, name asc', limit_page_length=0)
    if doc.get('only_sold_items') and items:
        sold = {r['item_code'] for r in sales_history(doc.company, doc.from_date, doc.to_date, items)}
        items = [i for i in items if i in sold]
    existing = {r.item_code for r in doc.get('items') or []}
    new = [i for i in items if i not in existing]
    room = max(MAX_ITEMS - len(existing), 0)
    for item_code in new[:room]:
        doc.append('items', {'item_code': item_code})
    doc.save()
    return dict(added=min(len(new), room), not_added=max(len(new) - room, 0), limit=MAX_ITEMS)

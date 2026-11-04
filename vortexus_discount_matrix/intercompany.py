"""Intercompany pricing: group companies buy at system cost plus a fixed markup.

Lines for a customer in the intercompany Customer Group are priced on every draft save at
the cost VDM uses (ERPNext FIFO cost in the row warehouse, then company stock valuation,
then last purchase rate) plus the markup in VDM Settings. Discounts on those lines are
cleared. Lines copied from an earlier document (quotation -> order -> invoice) keep the
price agreed there. Intercompany customers are outside the discount and margin matrix."""
import frappe
from frappe.utils import flt
from vortexus_discount_matrix.core import intercompany_rate, SYSTEM_COST, DEFAULT_INTERCOMPANY_GROUP, DEFAULT_INTERCOMPANY_MARKUP

# Fields that show a line was copied from an earlier selling document.
CARRIED_FROM = ('prevdoc_docname', 'quotation_item', 'sales_order', 'so_detail', 'delivery_note', 'dn_detail')


def options():
    value = lambda field: frappe.db.get_single_value('VDM Settings', field)
    on, group, markup = value('intercompany_pricing'), value('intercompany_customer_group'), value('intercompany_markup')
    return dict(
        on=str(1 if on is None else on) in ('1', 'True'),
        group=group if isinstance(group, str) and group else DEFAULT_INTERCOMPANY_GROUP,
        markup=flt(markup) if isinstance(markup, (int, float, str)) and not isinstance(markup, bool) else DEFAULT_INTERCOMPANY_MARKUP,
    )


def party_group(doc):
    """Customer Group of the document's customer, or None when it cannot be resolved yet."""
    if doc.doctype == 'Quotation':
        party_type, party = doc.get('quotation_to'), doc.get('party_name')
        if party_type == 'Customer':
            customer = party
        elif party_type == 'CRM Deal' and party:
            # A Frappe CRM deal counts once it has become an ERPNext Customer.
            customer = frappe.db.get_value('CRM Deal', party, 'erpnext_customer')
        else:
            return None
    else:
        customer = doc.get('customer')
    return frappe.db.get_value('Customer', customer, 'customer_group') if customer else None


def carried(row):
    return any(row.get(field) for field in CARRIED_FROM)


def apply(doc):
    """Price a draft intercompany document at cost plus markup. Returns a summary, or None if not intercompany."""
    if doc.get('docstatus') not in (0, None) or doc.get('is_return'):
        return None
    opts = options()
    if not opts['on'] or party_group(doc) != opts['group']:
        return None
    from vortexus_discount_matrix.prices import cost_rate
    priced, kept, missing = [], [], []
    for row in doc.items:
        if carried(row):
            kept.append(row.idx)
            continue
        cost, _ = cost_rate(doc, row, SYSTEM_COST)
        if not cost:
            missing.append(row.idx)
            continue
        precision = row.precision('rate') if hasattr(row, 'precision') else 2
        rate = float(intercompany_rate(cost, opts['markup'], precision or 2))
        row.price_list_rate = rate
        row.rate = rate
        row.discount_percentage = 0
        row.discount_amount = 0
        row.margin_type = ''
        row.margin_rate_or_amount = 0
        priced.append(row.idx)
    if priced:
        from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
        calculate_taxes_and_totals(doc)
    parts = [f"Intercompany price: system cost + {opts['markup']:g}% on {len(priced)} line(s)."]
    if kept:
        parts.append('Rows ' + ', '.join(map(str, kept)) + ' keep the price from the earlier document.')
    if missing:
        parts.append('Rows ' + ', '.join(map(str, missing)) + ' have no cost in the system: enter the price manually.')
        frappe.msgprint(parts[-1], title='Intercompany price', indicator='orange')
    return ' '.join(parts)

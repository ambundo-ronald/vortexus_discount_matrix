import json
import frappe
from frappe.utils import flt
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
from vortexus_discount_matrix.core import limit, minimum_price, effective_discount, fingerprint, policy
from vortexus_discount_matrix.prices import reference_rate

DOCTYPES = ('Quotation', 'Sales Order', 'Sales Invoice')


def enabled():
    return str(frappe.db.get_single_value('VDM Settings', 'enabled') or 0) in ('1', 'True')


def customer_group(doc):
    customer = doc.get('customer')
    if doc.doctype == 'Quotation':
        if doc.get('quotation_to') != 'Customer':
            frappe.throw('Select a Customer on this quotation so Discount Matrix can determine the customer group.')
        customer = doc.get('party_name')
    if not customer:
        frappe.throw('Select a Customer before checking Discount Matrix.')
    return frappe.db.get_value('Customer', customer, 'customer_group')


def inspect(doc):
    if doc.doctype not in DOCTYPES:
        frappe.throw('Unsupported document type.')
    result = {'status': 'Not Applicable', 'lines': [], 'violations': [], 'fingerprint': '', 'snapshot': {}, 'message': '', 'excluded_rows': []}
    groups, _ = policy()
    actual_groups = {r.idx: frappe.db.get_value('Item', r.item_code, 'item_group') for r in doc.items}
    result['excluded_rows'] = [dict(row=r.idx, item_code=r.item_code, item_group=actual_groups[r.idx],
        reason='Item Group has no accepted matrix mapping.') for r in doc.items if actual_groups[r.idx] not in groups]
    if not any(g in groups for g in actual_groups.values()):
        result['message'] = 'No items were checked: their Item Groups are outside the accepted matrix mappings.'
        return result
    group = customer_group(doc)
    from vortexus_discount_matrix.settings import customer_mappings
    mappings = customer_mappings()
    applicable = [(r, limit(actual_groups[r.idx], group, mappings)) for r in doc.items]
    applicable = [(r, cap) for r, cap in applicable if cap is not None]
    if not applicable:
        result['message'] = f'No items were checked: Customer Group {group or "(blank)"} has no mapping in VDM Settings.'
        return result
    if doc.get('is_return') or doc.get('is_consolidated'):
        frappe.throw('Discount Matrix requires separate review for returns or consolidated invoices; this version does not support them.')
    if doc.get('is_cash_or_non_trade_discount') and (doc.get('discount_amount') or doc.get('additional_discount_percentage')):
        frappe.throw('Use a regular additional discount for matrix-controlled sales, not a cash/non-trade discount.')
    for row, _ in applicable:
        if flt(row.qty) <= 0 or row.get('is_alternative'):
            frappe.throw(f'Row {row.idx}: matrix-controlled items require positive quantities and cannot be alternative quotation rows.')
    # Recompute derived amounts so caller-supplied net rates cannot bypass controls.
    calculate_taxes_and_totals(doc)
    shadow = frappe.get_doc(doc.as_dict())
    shadow.discount_amount = 0
    shadow.additional_discount_percentage = 0
    shadow.is_cash_or_non_trade_discount = 0
    refs = {}
    for row, cap in applicable:
        rate, price_name = reference_rate(doc, row)
        refs[row.idx] = (rate, price_name)
        baseline = shadow.items[row.idx - 1]
        baseline.rate = baseline.price_list_rate = baseline.rate_with_margin = rate
        baseline.discount_percentage = baseline.discount_amount = baseline.margin_rate_or_amount = 0
        baseline.margin_type = ''
        baseline.pricing_rules = ''
    calculate_taxes_and_totals(shadow)
    for row, cap in applicable:
        baseline = shadow.items[row.idx - 1]
        precision = row.precision('net_rate') or 2
        floor = minimum_price(baseline.net_rate, cap, precision)
        line = dict(row=row.idx, item_code=row.item_code, item_group=actual_groups[row.idx],
            reference_price=refs[row.idx][0], item_price=refs[row.idx][1], reference_net_rate=baseline.net_rate,
            max_discount=float(cap), minimum_net_rate=float(floor), actual_net_rate=row.net_rate,
            effective_discount=float(effective_discount(baseline.net_rate, row.net_rate)))
        result['lines'].append(line)
        if flt(row.net_rate, precision) < float(floor):
            result['violations'].append(line)
    def pick(obj, names):
        return {n: obj.get(n) for n in names.split()}
    snapshot = dict(document=doc.name, doctype=doc.doctype, customer_group=group, matrix_column=mappings.get(group), lines=result['lines'],
        header=pick(doc, 'customer quotation_to party_name company currency transaction_date posting_date conversion_rate selling_price_list discount_amount additional_discount_percentage apply_discount_on'),
        items=[pick(r, 'item_code qty uom conversion_factor rate net_rate net_amount discount_percentage discount_amount warehouse item_tax_template item_tax_rate quotation quotation_item prevdoc_docname sales_order so_detail') for r in doc.items],
        taxes=[pick(r, 'charge_type account_head rate tax_amount included_in_print_rate row_id add_deduct_tax category') for r in doc.get('taxes', [])])
    result['snapshot'] = snapshot
    result['fingerprint'] = fingerprint(snapshot)
    result['status'] = 'Adjust Price' if result['violations'] else 'Within Limit'
    result['message'] = ('Discount exceeds the permitted limit. Increase the selling price or reduce the discount.'
        if result['violations'] else f"All {len(result['lines'])} checked item lines are within their limits.")
    if result['violations'] and not doc.is_new():
        if frappe.db.exists('VDM Approval', {'reference_doctype': doc.doctype, 'reference_name': doc.name, 'fingerprint': result['fingerprint']}):
            result['status'] = 'Approved Exception'
            result['message'] = 'A Sales Manager explicitly approved an exception for these exact terms.'
    if result['violations'] and result['status'] != 'Approved Exception':
        from vortexus_discount_matrix.carry_forward import inherited_rows
        inherited = inherited_rows(doc, result['violations'], inspect, frappe)
        result['inherited_approvals'] = inherited
        result['violations'] = [v for v in result['violations'] if v['row'] not in inherited]
        if not result['violations']:
            result['status'] = 'Inherited Exception'
            references = sorted({v['source_doctype'] + ' ' + v['source_name'] for v in inherited.values()})
            result['message'] = 'Approved discount carried forward from ' + ', '.join(references) + '. No additional approval is required.'
    return result


def summary(result):
    return '\n'.join(f"Row {r['row']} ({r['item_code']}): maximum discount {r['max_discount']:g}%; minimum net unit price {r['minimum_net_rate']:g}; entered net unit price {r['actual_net_rate']:g}." for r in result['violations'])


def validate(doc, method=None):
    if not enabled():
        doc.custom_vdm_status = 'Disabled'
        doc.custom_vdm_summary = 'Discount Matrix enforcement is disabled in VDM Settings. Prices are not being blocked.'
        return
    result = inspect(doc)
    doc.custom_vdm_status = result['status']
    doc.custom_vdm_summary = summary(result) or result.get('message', '')


def before_submit(doc, method=None):
    validate(doc)
    if doc.custom_vdm_status in ('Adjust Price', 'Pending Approval'):
        frappe.throw('Discount exceeds the permitted matrix limit. Increase the selling price or reduce the discount before submitting.\n' + doc.custom_vdm_summary)


def on_submit(doc, method=None):
    # Last check of the persisted document, in the submission transaction.
    # An exception rolls back submission even when another before_submit hook
    # modifies prices after our earlier check. Never trust display status fields.
    if enabled():
        before_submit(frappe.get_doc(doc.doctype, doc.name))


@frappe.whitelist()
def preview(document):
    doc = frappe.get_doc(frappe.parse_json(document))
    if doc.doctype not in DOCTYPES:
        frappe.throw('Unsupported document type.')
    if doc.is_new():
        frappe.has_permission(doc.doctype, 'create', throw=True)
    else:
        frappe.get_doc(doc.doctype, doc.name).check_permission('read')
    if not enabled():
        return {'status': 'Disabled', 'violations': [], 'lines': [], 'excluded_rows': [],
            'message': 'Discount Matrix enforcement is disabled in VDM Settings. No discount limit is being enforced.'}
    result = inspect(doc)
    return {k: result[k] for k in ('status', 'lines', 'violations', 'message', 'excluded_rows')}


@frappe.whitelist()
def approve(doctype, name, reason):
    if doctype not in DOCTYPES or not enabled():
        frappe.throw('Discount Matrix is not enabled for this document.')
    if 'Sales Manager' not in frappe.get_roles():
        frappe.throw('Only a Sales Manager can approve a discount exception.', frappe.PermissionError)
    reason = (reason or '').strip()
    if not reason:
        frappe.throw('Enter the reason for approving this discount.')
    # Serialize approval against concurrent saves and approve only persisted terms.
    frappe.db.sql(f'SELECT name FROM `tab{doctype}` WHERE name=%s FOR UPDATE', (name,))
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('write')
    if doc.docstatus != 0:
        frappe.throw('Only saved drafts can receive discount approval.')
    result = inspect(doc)
    if not result['violations']:
        frappe.throw('This document does not require a discount exception.')
    approval = frappe.get_doc(dict(doctype='VDM Approval', reference_doctype=doctype, reference_name=name,
        fingerprint=result['fingerprint'], reason=reason, approved_by=frappe.session.user,
        approved_at=frappe.utils.now_datetime(), snapshot=json.dumps(result['snapshot'], default=str)))
    approval.insert(ignore_permissions=True)
    doc.save()
    return approval.name

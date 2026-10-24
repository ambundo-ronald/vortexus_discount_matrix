import json
import frappe
from frappe.utils import flt
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
from vortexus_discount_matrix.core import (limit, minimum_price, effective_discount, margin_minimum_price,
    gross_margin, terms_fingerprint, changed_term_paths, DISCOUNT_MODE, MARGIN_MODE, BOTH_MODE,
    SALES_MANAGER, MARGIN_APPROVER, BELOW_COST, LEVEL_RANK, required_level, covers, cost_within_tolerance)
from vortexus_discount_matrix.prices import reference_rate, cost_rate

DOCTYPES = ('Quotation', 'Sales Order', 'Sales Invoice')


def enabled():
    return str(frappe.db.get_single_value('VDM Settings', 'enabled') or 0) in ('1', 'True')


def approvals_allowed():
    return str(frappe.db.get_single_value('VDM Settings', 'allow_manager_approvals') or 0) in ('1', 'True')


def options():
    from vortexus_discount_matrix.settings import control_options
    return control_options()


def user_level(opts):
    """Highest approval level the current user holds: the margin approver role (MD) or Sales Manager."""
    roles = set(frappe.get_roles())
    if opts['approver_role'] in roles:
        return MARGIN_APPROVER
    return SALES_MANAGER if 'Sales Manager' in roles else None


def level_label(level, opts):
    return {SALES_MANAGER: f"a Sales Manager or {opts['approver_role']}", MARGIN_APPROVER: opts['approver_role'],
            BELOW_COST: 'nobody: below-cost sales are blocked'}.get(level, '')


@frappe.whitelist()
def approval_options():
    opts = options()
    return {'allow_approval': bool(enabled() and approvals_allowed() and user_level(opts)),
            'approver_role': opts['approver_role']}


def customer_group(doc):
    customer = doc.get('customer')
    if doc.doctype == 'Quotation':
        if doc.get('quotation_to') == 'Lead':
            lead = doc.get('party_name')
            if not lead:
                frappe.throw('Select a Lead before checking Discount Matrix.')
            group = frappe.db.get_value('Lead', lead, 'custom_customer_group')
            if not group:
                frappe.throw('Set Customer Group on the Lead before checking Discount Matrix.')
            return group
        if doc.get('quotation_to') != 'Customer':
            frappe.throw('Discount Matrix supports quotations to a Customer or Lead.')
        customer = doc.get('party_name')
    if not customer:
        frappe.throw('Select a Customer before checking Discount Matrix.')
    return frappe.db.get_value('Customer', customer, 'customer_group')


def inspect(doc):
    if doc.doctype not in DOCTYPES:
        frappe.throw('Unsupported document type.')
    result = {'status': 'Not Applicable', 'lines': [], 'violations': [], 'fingerprint': '', 'snapshot': {}, 'message': '', 'excluded_rows': []}
    if doc.doctype == 'Sales Invoice' and doc.get('is_return'):
        result['message'] = ('Credit note: Discount Matrix selling-price limits do not apply. '
                             'ERPNext return validation still applies.')
        return result
    from vortexus_discount_matrix.settings import customer_mappings, enforced_limits
    mode, discounts, margins = enforced_limits()
    opts = options()
    scope = set(discounts or {}) | set(margins or {})
    table = {MARGIN_MODE: 'margin matrix', BOTH_MODE: 'discount or margin matrix'}.get(mode, 'discount matrix')
    actual_groups = {r.idx: frappe.db.get_value('Item', r.item_code, 'item_group') for r in doc.items}
    result['excluded_rows'] = [dict(row=r.idx, item_code=r.item_code, item_group=actual_groups[r.idx],
        reason=f'Item Group is not in the VDM Settings {table}.') for r in doc.items if actual_groups[r.idx] not in scope]
    if not any(g in scope for g in actual_groups.values()):
        result['message'] = f'No items were checked: their Item Groups are not in the VDM Settings {table}.'
        return result
    group = customer_group(doc)
    mappings = customer_mappings()
    applicable = []
    for r in doc.items:
        item_group = actual_groups[r.idx]
        cap = limit(item_group, group, mappings, discounts) if discounts and item_group in discounts else None
        minimum_margin = limit(item_group, group, mappings, margins) if margins and item_group in margins else None
        if cap is not None or minimum_margin is not None:
            applicable.append((r, cap, minimum_margin))
    if not applicable:
        result['message'] = f'No items were checked: Customer Group {group or "(blank)"} has no mapping in VDM Settings.'
        return result
    if doc.get('is_return') or doc.get('is_consolidated'):
        frappe.throw('Discount Matrix does not support this return document type or consolidated invoices.')
    if doc.get('is_cash_or_non_trade_discount') and (doc.get('discount_amount') or doc.get('additional_discount_percentage')):
        frappe.throw('Use a regular additional discount for matrix-controlled sales, not a cash/non-trade discount.')
    for row, _, _ in applicable:
        if flt(row.qty) <= 0 or row.get('is_alternative'):
            frappe.throw(f'Row {row.idx}: matrix-controlled items require positive quantities and cannot be alternative quotation rows.')
    # Recompute derived amounts so caller-supplied net rates cannot bypass controls.
    calculate_taxes_and_totals(doc)
    discount_lines = check_discounts(doc, [(r, cap) for r, cap, _ in applicable if cap is not None], actual_groups)
    check_lines(doc, applicable, actual_groups, discount_lines, margins is not None or opts['block_below_cost'], opts, result)
    def pick(obj, names):
        return {n: obj.get(n) for n in names.split()}
    snapshot = dict(document=doc.name, doctype=doc.doctype, customer_group=group, matrix_column=mappings.get(group), lines=result['lines'],
        header=pick(doc, 'customer quotation_to party_name company currency transaction_date posting_date conversion_rate selling_price_list discount_amount additional_discount_percentage apply_discount_on'),
        items=[pick(r, 'item_code qty uom conversion_factor rate net_rate net_amount discount_percentage discount_amount warehouse item_tax_template item_tax_rate quotation quotation_item prevdoc_docname sales_order so_detail') for r in doc.items],
        taxes=[pick(r, 'charge_type account_head rate tax_amount included_in_print_rate row_id add_deduct_tax category') for r in doc.get('taxes', [])])
    if mode != DISCOUNT_MODE:
        # Discount snapshots keep their original shape so existing approvals stay valid.
        snapshot['matrix_mode'] = mode
    result['snapshot'] = snapshot
    result['fingerprint'] = terms_fingerprint(snapshot)
    needed = result['required_level'] = required_level(result['violations'])
    if needed == BELOW_COST:
        result['status'] = 'Below Cost'
        result['message'] = ('A price is below cost. Selling below cost is blocked and cannot be approved. '
                             'Increase the selling price.')
        return result
    result['status'] = 'Adjust Price' if result['violations'] else 'Within Limit'
    if result['violations']:
        margin_breach = needed == MARGIN_APPROVER
        result['message'] = (('Margin is below the permitted minimum. Increase the selling price or reduce the discount.' if margin_breach
            else 'Discount exceeds the permitted limit. Increase the selling price or reduce the discount.')
            + f' An exception needs approval by {level_label(needed, opts)}.')
    else:
        result['message'] = f"All {len(result['lines'])} checked item lines are within their limits."
    exceptions_enabled = approvals_allowed()
    if result['violations'] and not exceptions_enabled:
        result['message'] += ' Manager exceptions are disabled in VDM Settings.'
    if exceptions_enabled and result['violations'] and not doc.is_new():
        if matching_approval(doc, result, opts):
            result['status'] = 'Approved Exception'
            result['message'] = 'An authorised manager explicitly approved an exception for these exact terms.'
    if exceptions_enabled and result['violations'] and result['status'] != 'Approved Exception':
        from vortexus_discount_matrix.carry_forward import inherited_rows
        inherited = inherited_rows(doc, result['violations'], inspect, frappe)
        # A source approval covers only lines needing the same or a lower approval level.
        levels = {v['row']: v.get('level') for v in result['violations']}
        inherited = {row: entry for row, entry in inherited.items()
                     if covers(entry.get('source_level') or SALES_MANAGER, levels.get(row))}
        result['inherited_approvals'] = inherited
        result['violations'] = [v for v in result['violations'] if v['row'] not in inherited]
        if not result['violations']:
            result['status'] = 'Inherited Exception'
            references = sorted({v['source_doctype'] + ' ' + v['source_name'] for v in inherited.values()})
            result['message'] = 'Approved exception carried forward from ' + ', '.join(references) + '. No additional approval is required.'
    return result


def check_lines(doc, applicable, actual_groups, discount_lines, need_cost, opts, result):
    """Add margin and below-cost checks to each line and decide who may approve it."""
    for row, cap, minimum_margin in applicable:
        precision = row.precision('net_rate') or 2
        line = discount_lines.get(row.idx) or dict(row=row.idx, item_code=row.item_code,
                                                   item_group=actual_groups[row.idx], actual_net_rate=row.net_rate)
        net = flt(row.net_rate, precision)
        cost = None
        if need_cost:
            # ERPNext net_rate excludes tax and includes additional discounts; cost is per row UOM.
            cost, source = cost_rate(doc, row, opts['cost_basis'])
            line['cost_rate'] = cost
            line['cost_source'] = source or 'No cost found'
            if minimum_margin is not None or cost is not None:
                actual = None if cost is None else gross_margin(cost, row.net_rate)
                line['actual_margin'] = None if actual is None else float(actual)
        level = None
        if cap is not None and net < float(line['minimum_net_rate']):
            level = SALES_MANAGER
        if minimum_margin is not None:
            line['min_margin'] = float(minimum_margin)
            if cost is None:
                level = MARGIN_APPROVER  # unknown cost: cannot prove the margin
            else:
                floor = float(margin_minimum_price(cost, minimum_margin, precision))
                line['margin_floor'] = floor
                if cap is None:
                    line['minimum_net_rate'] = floor
                if net < floor:
                    level = MARGIN_APPROVER
        if opts['block_below_cost'] and cost is not None and net < flt(cost, precision):
            line['below_cost'] = True
            level = BELOW_COST
        line['level'] = level
        line['description'] = describe(line, opts)
        result['lines'].append(line)
        if level:
            result['violations'].append(line)


def check_discounts(doc, applicable, actual_groups):
    """Discount floor per row index from the general Standard Selling price."""
    lines = {}
    if not applicable:
        return lines
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
        lines[row.idx] = dict(row=row.idx, item_code=row.item_code, item_group=actual_groups[row.idx],
            reference_price=refs[row.idx][0], item_price=refs[row.idx][1], reference_net_rate=baseline.net_rate,
            max_discount=float(cap), minimum_net_rate=float(floor), actual_net_rate=row.net_rate,
            effective_discount=float(effective_discount(baseline.net_rate, row.net_rate)))
    return lines


def matching_approval(doc, result, opts=None):
    opts = opts or options()
    needed = result.get('required_level') or SALES_MANAGER
    filters = {'reference_doctype': doc.doctype, 'reference_name': doc.name}
    cost_checked = any(line.get('cost_rate') is not None for line in result.get('lines') or [])
    if not cost_checked:
        exact = {**filters, 'fingerprint': result['fingerprint']}
        if needed != SALES_MANAGER:
            exact['approval_level'] = MARGIN_APPROVER
        if frappe.db.exists('VDM Approval', exact):
            return True
    # Existing records retain their original hashes and snapshots. Compare
    # equivalent representations without rewriting the historical audit data.
    records = frappe.get_all('VDM Approval', filters=filters,
        fields=['name', 'snapshot', 'approval_level'], order_by='creation desc')
    for index, record in enumerate(records):
        try:
            old = json.loads(record['snapshot'])
            if not isinstance(old, dict):
                continue
            if terms_fingerprint(old) == result['fingerprint']:
                if not covers(record.get('approval_level'), needed):
                    result['approval_mismatch'] = (f"The earlier approval was by {level_label(record.get('approval_level') or SALES_MANAGER, opts)}; "
                                                   f"these terms now need {level_label(needed, opts)}.")
                    continue
                risen = cost_within_tolerance(old.get('lines'), result.get('lines') or [], opts['cost_tolerance'])
                if risen:
                    result['approval_mismatch'] = (f"Cost rose more than {opts['cost_tolerance']:g}% since approval ("
                                                   + '; '.join(risen[:4]) + '). A new approval is required.')
                    continue
                return True
            if index == 0:
                paths = changed_term_paths(old, result['snapshot'])[:6]
                result['approval_mismatch'] = 'Previous approval no longer matches these terms: ' + ', '.join(paths) + '.'
        except (ValueError, TypeError):
            continue
    return False


def describe(r, opts=None):
    opts = opts or {'approver_role': 'MD'}
    if r.get('below_cost'):
        tail = f" BELOW COST {r['cost_rate']:g}: blocked."
    elif r.get('level') == MARGIN_APPROVER:
        tail = f" Needs approval by {opts['approver_role']}."
    else:
        tail = ''
    margin_part = ''
    if r.get('min_margin') is not None:
        if r.get('cost_rate') is None:
            margin_part = f"minimum margin {r['min_margin']:g}% but no cost was found"
        else:
            margin_part = f"minimum margin {r['min_margin']:g}%"
    actual = 'n/a' if r.get('actual_margin') is None else f"{r['actual_margin']:.2f}%"
    if r.get('max_discount') is not None:
        text = f"Row {r['row']} ({r['item_code']}): maximum discount {r['max_discount']:g}%; minimum net unit price {r['minimum_net_rate']:g}"
        if margin_part:
            text += f"; {margin_part}" + (f" (margin floor {r['margin_floor']:g})" if r.get('margin_floor') is not None else '')
        text += f"; entered net unit price {r['actual_net_rate']:g}"
        if r.get('min_margin') is not None or r.get('below_cost'):
            text += f" (margin {actual})"
        return text + '.' + tail
    if margin_part:
        floor = f"; minimum net unit price {r['minimum_net_rate']:g}" if r.get('minimum_net_rate') is not None else ''
        return (f"Row {r['row']} ({r['item_code']}): {margin_part}{floor}; entered net unit price "
                f"{r['actual_net_rate']:g} (margin {actual}).") + tail
    return f"Row {r['row']} ({r['item_code']}): entered net unit price {r['actual_net_rate']:g} (margin {actual})." + tail


def summary(result):
    details = '\n'.join(r.get('description') or describe(r) for r in result['violations'])
    return details + ('\n' + result['approval_mismatch'] if result.get('approval_mismatch') else '')


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
    if doc.custom_vdm_status == 'Below Cost':
        frappe.throw('A price is below cost. Selling below cost is blocked. Increase the selling price before submitting.\n' + doc.custom_vdm_summary)
    if doc.custom_vdm_status in ('Adjust Price', 'Pending Approval'):
        frappe.throw('Price is below the permitted matrix minimum. Increase the selling price or reduce the discount before submitting.\n' + doc.custom_vdm_summary)


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
    if not approvals_allowed():
        frappe.throw('Sales Manager discount exceptions are disabled in VDM Settings.')
    opts = options()
    level = user_level(opts)
    if not level:
        frappe.throw(f"Only a Sales Manager or {opts['approver_role']} can approve a discount exception.", frappe.PermissionError)
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
    if result.get('required_level') == BELOW_COST:
        frappe.throw('A price is below cost. Selling below cost is blocked and cannot be approved.')
    if not result['violations']:
        frappe.throw('This document does not require a discount exception.')
    if not covers(level, result.get('required_level')):
        frappe.throw(f"These prices are below the margin minimum and need approval by {opts['approver_role']}.",
                     frappe.PermissionError)
    # Persist controller recalculations before recording the terms approved.
    doc.save()
    result = inspect(frappe.get_doc(doctype, name))
    approval = frappe.get_doc(dict(doctype='VDM Approval', reference_doctype=doctype, reference_name=name,
        fingerprint=result['fingerprint'], reason=reason, approved_by=frappe.session.user, approval_level=level,
        approved_at=frappe.utils.now_datetime(), snapshot=json.dumps(result['snapshot'], default=str)))
    approval.insert(ignore_permissions=True)
    doc.db_set({'custom_vdm_status': 'Approved Exception', 'custom_vdm_summary': summary(result)}, update_modified=False)
    return approval.name

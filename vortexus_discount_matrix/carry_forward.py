"""Carry an approved exception from a submitted source document to the documents made from it.

A source counts as approved by its state when it was submitted (Approved Exception with a
VDM Approval record, or Inherited Exception), not by re-checking it against today's prices,
costs or matrix limits. Each downstream row must still link natively to its source row and
must not be worse than what was approved: same item and UOM, no lower net price, and no more
quantity than the source row across all submitted downstream documents. Copied status fields
alone never authorise anything; the source document and its approval records are re-read.
"""
from collections import defaultdict
from vortexus_discount_matrix.core import decimal, LEVEL_RANK, SALES_MANAGER

LINKS = {
    'Sales Order': ('Quotation', 'prevdoc_docname', 'quotation_item'),
    'Sales Invoice': ('Sales Order', 'sales_order', 'so_detail'),
}
APPROVED, INHERITED = 'Approved Exception', 'Inherited Exception'


def party(doc):
    return doc.get('party_name') if doc.doctype == 'Quotation' and doc.get('quotation_to') == 'Customer' else doc.get('customer')


def same_party(doc, source, frappe):
    """Same company, currency and customer. A quotation to a Lead or CRM Deal matches the
    Customer it became when the system records one; otherwise the native row link is the proof."""
    customer = doc.get('customer')
    if not customer or doc.get('company') != source.get('company') or doc.get('currency') != source.get('currency'):
        return False
    if source.doctype != 'Quotation' or source.get('quotation_to') == 'Customer':
        return customer == party(source)
    lead_or_deal = source.get('party_name')
    if not lead_or_deal:
        return False
    if source.get('quotation_to') == 'CRM Deal':
        became = frappe.db.get_value('CRM Deal', lead_or_deal, 'erpnext_customer')
        return not became or became == customer
    if source.get('quotation_to') == 'Lead':
        became = frappe.db.get_value('Customer', {'lead_name': lead_or_deal}, 'name')
        return not became or became == customer
    return False


def amendment_chain(doctype, name, frappe, limit=10):
    """This document and the documents it amends, newest first."""
    names = []
    while name and name not in names and len(names) < limit:
        names.append(name)
        name = frappe.db.get_value(doctype, name, 'amended_from')
    return names


def approval_level(source, frappe, depth=0):
    """Highest level that authorised the submitted source, or None when it was not an approved exception."""
    if source.docstatus != 1 or source.get('is_return') or depth > 3:
        return None
    status = source.get('custom_vdm_status')
    if status == APPROVED:
        records = frappe.get_all('VDM Approval', filters={
            'reference_doctype': source.doctype,
            'reference_name': ['in', amendment_chain(source.doctype, source.name, frappe)]},
            fields=['approval_level'])
        if not records:
            return None
        return max((r.get('approval_level') or SALES_MANAGER for r in records), key=lambda level: LEVEL_RANK.get(level, 0))
    if status == INHERITED and source.doctype in LINKS:
        # Its own upstream sources authorised it; use the strongest of them.
        upstream_type, parent_field, _ = LINKS[source.doctype]
        levels = []
        for upstream_name in sorted({r.get(parent_field) for r in source.items if r.get(parent_field)}):
            if frappe.db.exists(upstream_type, upstream_name):
                level = approval_level(frappe.get_doc(upstream_type, upstream_name), frappe, depth + 1)
                if level:
                    levels.append(level)
        return max(levels, key=lambda level: LEVEL_RANK.get(level, 0)) if levels else None
    return None


def inherited_rows(doc, violations, frappe, notes=None):
    """Rows covered by an approved source. notes, when given, receives row -> reason for linked
    rows that cannot inherit because they differ from what was approved."""
    notes = {} if notes is None else notes
    if doc.doctype not in LINKS:
        return {}
    source_type, parent_field, row_field = LINKS[doc.doctype]
    linked = defaultdict(list)
    for row in doc.items:
        if row.get(parent_field) and row.get(row_field):
            linked[(row.get(parent_field), row.get(row_field))].append(row)
    needed = {v['row'] for v in violations}
    covered = {}
    sources = {}
    for source_name, source_row in sorted(linked):
        rows = linked[(source_name, source_row)]
        if not any(row.idx in needed for row in rows):
            continue
        if source_name not in sources:
            # Serialize competing allocations and cancellations of this source.
            frappe.db.sql(f'SELECT name FROM `tab{source_type}` WHERE name=%s FOR UPDATE', (source_name,))
            if not frappe.db.exists(source_type, source_name):
                sources[source_name] = None
                continue
            source = frappe.get_doc(source_type, source_name)
            level = approval_level(source, frappe) if same_party(doc, source, frappe) else None
            sources[source_name] = (source, level) if level else None
        entry = sources[source_name]
        if not entry:
            continue
        source, level = entry
        original = next((r for r in source.items if r.name == source_row), None)
        if not original:
            continue
        label = f'{source_type} {source_name}'
        if any(r.item_code != original.item_code or r.uom != original.uom
            or decimal(r.conversion_factor) != decimal(original.conversion_factor)
            or decimal(r.qty) <= 0 for r in rows):
            for r in rows:
                notes.setdefault(r.idx, f'Row {r.idx}: item or unit differs from the line approved on {label}; a new approval is required.')
            continue
        # Locking read counts prior submitted downstream allocations, excluding
        # this document on resubmission/final on_submit checks. Returns never
        # replenish the approved allocation automatically.
        previous = frappe.db.sql(
            f'SELECT qty FROM `tab{doc.doctype} Item` WHERE `{parent_field}`=%s '
            f'AND `{row_field}`=%s AND docstatus=1 AND parent != %s AND qty > 0 FOR UPDATE',
            (source_name, source_row, doc.name or ''), as_dict=True)
        used = sum((decimal(r['qty']) for r in previous), decimal(0))
        requested = sum((decimal(r.qty) for r in rows), decimal(0))
        if used + requested > decimal(original.qty):
            for r in rows:
                notes.setdefault(r.idx, f'Row {r.idx}: quantity exceeds the {original.qty:g} approved on {label} '
                                        f'({used:g} already used); a new approval is required.')
            continue
        for row in rows:
            if row.idx in needed and decimal(row.net_rate) < decimal(original.net_rate):
                notes.setdefault(row.idx, f'Row {row.idx}: net price {row.net_rate:g} is below the {original.net_rate:g} '
                                          f'approved on {label}; a new approval is required.')
            elif row.idx in needed:
                covered[row.idx] = dict(source_doctype=source_type, source_name=source_name,
                    source_row=source_row, source_status=source.get('custom_vdm_status'), source_level=level)
    return covered

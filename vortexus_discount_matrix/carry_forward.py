"""Verify native source-row links; never inherit a copied status field."""
from collections import defaultdict
from vortexus_discount_matrix.core import decimal

LINKS = {
    'Sales Order': ('Quotation', 'prevdoc_docname', 'quotation_item'),
    'Sales Invoice': ('Sales Order', 'sales_order', 'so_detail'),
}


def party(doc):
    return doc.get('party_name') if doc.doctype == 'Quotation' and doc.get('quotation_to') == 'Customer' else doc.get('customer')


def inherited_rows(doc, violations, inspect_source, frappe):
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
            if (source.docstatus != 1 or source.get('is_return') or not party(doc)
                or party(doc) != party(source) or doc.get('company') != source.get('company')
                or doc.get('currency') != source.get('currency')):
                sources[source_name] = None
                continue
            result = inspect_source(source)
            sources[source_name] = (source, result) if result['status'] in ('Approved Exception', 'Inherited Exception') else None
        entry = sources[source_name]
        if not entry:
            continue
        source, result = entry
        original = next((r for r in source.items if r.name == source_row), None)
        if not original:
            continue
        if any(r.item_code != original.item_code or r.uom != original.uom
            or decimal(r.conversion_factor) != decimal(original.conversion_factor)
            or decimal(r.qty) <= 0 for r in rows):
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
            continue
        for row in rows:
            if row.idx in needed and decimal(row.net_rate) >= decimal(original.net_rate):
                covered[row.idx] = dict(source_doctype=source_type, source_name=source_name,
                    source_row=source_row, source_fingerprint=result['fingerprint'])
    return covered

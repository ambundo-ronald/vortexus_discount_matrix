import frappe
from vortexus_discount_matrix.core import mapping_from_rows


def validate(doc, method=None):
    try:
        mapping_from_rows(doc.get('customer_mappings') or [])
    except ValueError as exc:
        frappe.throw(str(exc))


def customer_mappings():
    # Read this site's current configuration, never a process-wide cached mapping.
    doc = frappe.get_doc('VDM Settings')
    try:
        return mapping_from_rows(doc.get('customer_mappings') or [])
    except ValueError as exc:
        frappe.throw(str(exc))

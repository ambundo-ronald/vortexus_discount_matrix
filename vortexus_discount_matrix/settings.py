import frappe
from vortexus_discount_matrix.core import (mapping_from_rows, limits_from_rows,
    DISCOUNT_MODE, MARGIN_MODE, MATRIX_MODES)


def validate(doc, method=None):
    try:
        if (doc.get('matrix_mode') or DISCOUNT_MODE) not in MATRIX_MODES:
            raise ValueError('Select Discount Matrix or Margin Matrix.')
        mapping_from_rows(doc.get('customer_mappings') or [])
        limits_from_rows(doc.get('discount_limits') or [])
        limits_from_rows(doc.get('margin_limits') or [], MARGIN_MODE)
    except ValueError as exc:
        frappe.throw(str(exc))


def customer_mappings():
    # Read this site's current configuration, never a process-wide cached mapping.
    doc = frappe.get_doc('VDM Settings')
    try:
        return mapping_from_rows(doc.get('customer_mappings') or [])
    except ValueError as exc:
        frappe.throw(str(exc))


def active_limits():
    """(mode, Item Group -> {matrix column: %}) for the matrix selected in VDM Settings.

    Discount Matrix limits are maximum discounts from Standard Selling; Margin
    Matrix limits are minimum gross margins on price over valuation cost."""
    doc = frappe.get_doc('VDM Settings')
    mode = doc.get('matrix_mode') or DISCOUNT_MODE
    try:
        if mode == MARGIN_MODE:
            return mode, limits_from_rows(doc.get('margin_limits') or [], MARGIN_MODE)
        return DISCOUNT_MODE, limits_from_rows(doc.get('discount_limits') or [])
    except ValueError as exc:
        frappe.throw(str(exc))


def matrix_tables():
    """(discount limits, margin limits) from VDM Settings, whichever matrix is in use."""
    doc = frappe.get_doc('VDM Settings')
    try:
        return (limits_from_rows(doc.get('discount_limits') or []),
                limits_from_rows(doc.get('margin_limits') or [], MARGIN_MODE))
    except ValueError as exc:
        frappe.throw(str(exc))

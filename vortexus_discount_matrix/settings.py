import frappe
from frappe.utils import flt
from vortexus_discount_matrix.core import (mapping_from_rows, limits_from_rows,
    DISCOUNT_MODE, MARGIN_MODE, BOTH_MODE, MATRIX_MODES, SYSTEM_COST, COST_BASES, DEFAULT_APPROVER_ROLE)


def validate(doc, method=None):
    try:
        if (doc.get('matrix_mode') or DISCOUNT_MODE) not in MATRIX_MODES:
            raise ValueError('Select Discount Matrix, Margin Matrix or Discount and Margin.')
        if doc.get('cost_basis') and doc.get('cost_basis') not in COST_BASES:
            raise ValueError('Select a valid Cost Basis.')
        if not 0 <= flt(doc.get('cost_tolerance')) <= 100:
            raise ValueError('Cost tolerance must be between 0 and 100%.')
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


def enforced_limits():
    """(mode, discount limits or None, margin limits or None) for the matrix selected in VDM Settings.

    Discount limits are maximum discounts from Standard Selling; margin limits are
    minimum gross margins on price over cost. Discount and Margin enforces both."""
    doc = frappe.get_doc('VDM Settings')
    mode = doc.get('matrix_mode') or DISCOUNT_MODE
    try:
        discounts = limits_from_rows(doc.get('discount_limits') or []) if mode in (DISCOUNT_MODE, BOTH_MODE) else None
        margins = limits_from_rows(doc.get('margin_limits') or [], MARGIN_MODE) if mode in (MARGIN_MODE, BOTH_MODE) else None
    except ValueError as exc:
        frappe.throw(str(exc))
    return mode, discounts, margins


def active_limits():
    """(mode, Item Group -> limits) for every Item Group the selected matrix controls."""
    mode, discounts, margins = enforced_limits()
    if mode == MARGIN_MODE:
        return mode, margins
    if mode == BOTH_MODE:
        return mode, {**(margins or {}), **(discounts or {})}
    return mode, discounts


def matrix_tables():
    """(discount limits, margin limits) from VDM Settings, whichever matrix is in use."""
    doc = frappe.get_doc('VDM Settings')
    try:
        return (limits_from_rows(doc.get('discount_limits') or []),
                limits_from_rows(doc.get('margin_limits') or [], MARGIN_MODE))
    except ValueError as exc:
        frappe.throw(str(exc))


def control_options():
    """Below-cost block, cost basis, approval cost tolerance and the margin approver role."""
    value = lambda field: frappe.db.get_single_value('VDM Settings', field)
    block = value('block_below_cost')
    basis = value('cost_basis')
    tolerance = value('cost_tolerance')
    role = value('margin_approver_role')
    return dict(
        block_below_cost=str(1 if block is None else block) in ('1', 'True'),
        cost_basis=basis if basis in COST_BASES else SYSTEM_COST,
        cost_tolerance=flt(tolerance) if isinstance(tolerance, (int, float, str)) and not isinstance(tolerance, bool) else 5.0,
        approver_role=role if isinstance(role, str) and role else DEFAULT_APPROVER_ROLE,
    )

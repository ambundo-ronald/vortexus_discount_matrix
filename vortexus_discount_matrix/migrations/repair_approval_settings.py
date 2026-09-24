"""Explicit, recorded upgrade for sites missing the approval setting."""
import frappe
from vortexus_discount_matrix.setup import install


def execute():
    install()
    if not frappe.db.exists('DocField', {
        'parent': 'VDM Settings', 'fieldname': 'allow_manager_approvals',
    }):
        frappe.throw('VDM upgrade failed: Allow Sales Manager Discount Exceptions was not created.')
    frappe.clear_cache(doctype='VDM Settings')

import frappe
from vortexus_discount_matrix.core import MATRIX_COLUMNS, policy
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def field(name, label, kind='Data', **kwargs):
    return dict(fieldname=name, label=label, fieldtype=kind, **kwargs)


def install():
    """Idempotent: never enable enforcement as a side effect of install/migrate."""
    if not frappe.db.exists('Module Def', 'Vortexus Discount Matrix'):
        frappe.get_doc(dict(doctype='Module Def', module_name='Vortexus Discount Matrix', app_name='vortexus_discount_matrix')).insert(ignore_permissions=True)
    definitions = {
        'VDM Customer Mapping': dict(istable=1, editable_grid=1, fields=[
            field('customer_group', 'Customer Group', 'Link', options='Customer Group', reqd=1, in_list_view=1),
            field('matrix_column', 'Matrix Group', 'Select', options='\n'.join(MATRIX_COLUMNS), reqd=1, in_list_view=1),
        ], permissions=[]),
        'VDM Settings': dict(issingle=1, track_changes=1, fields=[
            field('enabled', 'Enable discount matrix enforcement', 'Check', default='0'),
            field('price_list', 'Reference Price List', 'Link', options='Price List', default='Standard Selling', read_only=1),
        ], permissions=[dict(role='System Manager', read=1, write=1)]),
        'VDM Approval': dict(autoname='hash', fields=[
            field('reference_doctype', 'Document Type', reqd=1),
            field('reference_name', 'Document', reqd=1),
            field('fingerprint', 'Approved Terms Hash', reqd=1),
            field('reason', 'Manager Reason', 'Small Text', reqd=1),
            field('approved_by', 'Approved By', 'Link', options='User', reqd=1),
            field('approved_at', 'Approved At', 'Datetime', reqd=1),
            field('snapshot', 'Approved Terms', 'Long Text', reqd=1),
        ], permissions=[dict(role='Sales Manager', read=1), dict(role='System Manager', read=1)]),
    }
    for name, definition in definitions.items():
        if not frappe.db.exists('DocType', name):
            frappe.get_doc(dict(doctype='DocType', name=name, module='Vortexus Discount Matrix', custom=1, **definition)).insert(ignore_permissions=True)
    # Add fields to both new installs and sites upgrading from version 0.1.0.
    settings_type = frappe.get_doc('DocType', 'VDM Settings')
    for definition in [
        field('customer_mappings', 'Customer Group to Matrix Group', 'Table', options='VDM Customer Mapping',
            description='Unmapped customer groups are outside this control. Each customer group may appear only once.'),
        field('mappings_initialized', 'Mappings Initialized', 'Check', hidden=1, read_only=1, default='0'),
    ]:
        if not any(f.fieldname == definition['fieldname'] for f in settings_type.fields):
            settings_type.append('fields', definition)
    settings_type.track_changes = 1
    settings_type.save(ignore_permissions=True)
    frappe.clear_cache(doctype='VDM Settings')
    settings = frappe.get_doc('VDM Settings')
    if not settings.get('mappings_initialized'):
        # Seed once. An intentionally emptied table must remain empty on migration.
        if not settings.get('customer_mappings'):
            for group, column in policy()[1].items():
                settings.append('customer_mappings', {'customer_group': group, 'matrix_column': column})
        settings.mappings_initialized = 1
        settings.save(ignore_permissions=True)
    fields = [
        field('custom_vdm_section', 'Discount Matrix', 'Section Break', insert_after='items'),
        field('custom_vdm_status', 'Matrix Status', read_only=1, no_copy=1),
        field('custom_vdm_summary', 'Matrix Review', 'Small Text', read_only=1, no_copy=1),
    ]
    create_custom_fields({dt: fields for dt in ('Quotation', 'Sales Order', 'Sales Invoice')}, update=True)

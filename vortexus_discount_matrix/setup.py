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
    approvals_added = not any(f.fieldname == 'allow_manager_approvals' for f in settings_type.fields)
    for definition in [
        field('allow_manager_approvals', 'Allow Sales Manager Discount Exceptions', 'Check', default='1',
            description='When unchecked, direct and inherited exceptions cannot authorize submission. Existing approval records are retained.'),
        field('customer_mappings', 'Customer Group to Matrix Group', 'Table', options='VDM Customer Mapping',
            description='Unmapped customer groups are outside this control. Each customer group may appear only once.'),
        field('mappings_initialized', 'Mappings Initialized', 'Check', hidden=1, read_only=1, default='0'),
    ]:
        if not any(f.fieldname == definition['fieldname'] for f in settings_type.fields):
            settings_type.append('fields', definition)
    order_settings_fields(settings_type)
    settings_type.track_changes = 1
    settings_type.save(ignore_permissions=True)
    frappe.clear_cache(doctype='VDM Settings')
    settings = frappe.get_doc('VDM Settings')
    if approvals_added:
        settings.allow_manager_approvals = 1
        settings.save(ignore_permissions=True)
    if not settings.get('mappings_initialized'):
        # Seed once. An intentionally emptied table must remain empty on migration.
        if not settings.get('customer_mappings'):
            for group, column in policy()[1].items():
                settings.append('customer_mappings', {'customer_group': group, 'matrix_column': column})
        settings.mappings_initialized = 1
        settings.save(ignore_permissions=True)
    install_approval_view()
    install_transaction_fields()
    install_sidebar()


def install_transaction_fields():
    fields = [
        field('custom_vdm_section', 'Discount Matrix', 'Section Break', insert_after='items'),
        field('custom_vdm_status', 'Matrix Status', read_only=1, no_copy=1),
        field('custom_vdm_summary', 'Matrix Review', 'Small Text', read_only=1, no_copy=1),
    ]
    # These are app-owned display fields, with no Link/Table options. Frappe's
    # normal on_update checks every field on the target DocType, including
    # unrelated site customizations (e.g. Delivery Personnel with empty options).
    # Scope this supported flag to this batch; do not alter site fields or
    # disable transaction/approval validation.
    create_custom_fields(
        {dt: [dict(df) for df in fields] for dt in ('Quotation', 'Sales Order', 'Sales Invoice')},
        ignore_validate=True,
        update=True,
    )


def install_approval_view():
    approval = frappe.get_doc('DocType', 'VDM Approval')
    if not any(f.fieldname == 'approved_terms_table' for f in approval.fields):
        approval.append('fields', field('approved_terms_table', 'Approved Terms', 'HTML'))
    for df in approval.fields:
        if df.fieldname == 'snapshot':
            df.hidden = 1
            df.read_only = 1
    approval.save(ignore_permissions=True)
    frappe.clear_cache(doctype='VDM Approval')


def order_settings_fields(settings_type):
    # Put controls before the long mapping grid on upgraded sites as well.
    order = ['enabled', 'allow_manager_approvals', 'price_list',
             'customer_mappings', 'mappings_initialized']
    fields = list(settings_type.fields)
    by_name = {df.fieldname: df for df in fields}
    settings_type.set('fields', [by_name[name] for name in order if name in by_name]
                      + [df for df in fields if df.fieldname not in order])
    for df in settings_type.fields:
        if df.fieldname == 'allow_manager_approvals':
            df.hidden = 0


def install_sidebar():
    # Use the module title: v16 otherwise generates an ephemeral module sidebar.
    title = 'Vortexus Discount Matrix'
    if frappe.db.exists('Workspace Sidebar', title):
        sidebar = frappe.get_doc('Workspace Sidebar', title)
    else:
        sidebar = frappe.get_doc(dict(doctype='Workspace Sidebar', title=title,
                                     app='vortexus_discount_matrix', module=title,
                                     header_icon='grid', standard=0, items=[]))
    links = [
        ('VDM Settings', 'DocType', 'VDM Settings', 'settings'),
        ('Discount Approvals', 'DocType', 'VDM Approval', 'check'),
        ('Items Outside Discount Matrix', 'Report', 'Items Outside Discount Matrix', 'table'),
        ('Quotations', 'DocType', 'Quotation', 'file'),
        ('Sales Orders', 'DocType', 'Sales Order', 'file'),
        ('Sales Invoices', 'DocType', 'Sales Invoice', 'file'),
        ('Items', 'DocType', 'Item', 'package'),
        ('Item Groups', 'DocType', 'Item Group', 'folder'),
        ('Customer Groups', 'DocType', 'Customer Group', 'users'),
        ('Item Prices', 'DocType', 'Item Price', 'tag'),
        ('Price Lists', 'DocType', 'Price List', 'list'),
    ]
    existing = {(row.link_type, row.link_to) for row in sidebar.items}
    for label, link_type, link_to, icon in links:
        if (link_type, link_to) not in existing:
            sidebar.append('items', dict(type='Link', label=label, link_type=link_type,
                                         link_to=link_to, icon=icon))
    sidebar.save(ignore_permissions=True)
    frappe.clear_cache()

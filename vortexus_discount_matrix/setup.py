import frappe
from vortexus_discount_matrix.core import MATRIX_COLUMNS, MATRIX_MODES, DISCOUNT_MODE, LIMIT_FIELDS, default_limit_rows, policy
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
        'VDM Discount Limit': dict(istable=1, editable_grid=1, fields=limit_fields(), permissions=[]),
        'VDM Margin Limit': dict(istable=1, editable_grid=1, fields=limit_fields(), permissions=[]),
        'VDM Settings': dict(issingle=1, track_changes=1, fields=[
            field('enabled', 'Enable discount matrix enforcement', 'Check', default='0'),
            field('price_list', 'Reference Price List', 'Link', options='Price List', default='Standard Selling', read_only=1),
        ], permissions=[dict(role='System Manager', read=1, write=1)]),
        'VDM Simulation Item': dict(istable=1, editable_grid=1, fields=simulation_item_fields(), permissions=[]),
        'VDM Price Simulation': dict(autoname='VDM-SIM-.#####', title_field='title', track_changes=1,
            fields=simulation_fields(), permissions=[
                dict(role=role, read=1, write=1, create=1, delete=1) for role in ('System Manager', 'Sales Manager')]),
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
    mode_added = not any(f.fieldname == 'matrix_mode' for f in settings_type.fields)
    for definition in [
        field('allow_manager_approvals', 'Allow Sales Manager Discount Exceptions', 'Check', default='1',
            description='When unchecked, direct and inherited exceptions cannot authorize submission. Existing approval records are retained.'),
        field('customer_mappings', 'Customer Group to Matrix Group', 'Table', options='VDM Customer Mapping',
            description='Unmapped customer groups are outside this control. Each customer group may appear only once.'),
        field('mappings_initialized', 'Mappings Initialized', 'Check', hidden=1, read_only=1, default='0'),
        field('discount_limits', 'Discount Matrix (maximum discount % from Standard Selling)', 'Table',
            options='VDM Discount Limit', allow_bulk_edit=1,
            description='One row per exact Item Group. Item Groups not listed are outside this control. '
                        '0 means no discount is allowed. Changes apply to the next check; submitted documents are not changed.'),
        field('limits_initialized', 'Limits Initialized', 'Check', hidden=1, read_only=1, default='0'),
        field('matrix_mode', 'Matrix In Use', 'Select', options='\n'.join(MATRIX_MODES), default=DISCOUNT_MODE, reqd=1,
            description='Discount Matrix: maximum discount from Standard Selling. '
                        'Margin Matrix: minimum gross margin, (net price - valuation rate) / net price. '
                        'Only the selected table is enforced.'),
        field('margin_limits', 'Margin Matrix (minimum gross margin % on valuation rate)', 'Table',
            options='VDM Margin Limit', allow_bulk_edit=1,
            description='One row per exact Item Group. Item Groups not listed are outside this control when Margin Matrix is in use. '
                        'Each value must be at least 0 and below 100. Items need a valuation rate to be checked.'),
        field('margins_initialized', 'Margins Initialized', 'Check', hidden=1, read_only=1, default='0'),
    ]:
        if not any(f.fieldname == definition['fieldname'] for f in settings_type.fields):
            settings_type.append('fields', definition)
    order_settings_fields(settings_type)
    settings_type.track_changes = 1
    settings_type.save(ignore_permissions=True)
    frappe.clear_cache(doctype='VDM Settings')
    settings = frappe.get_doc('VDM Settings')
    if approvals_added or mode_added or not settings.get('matrix_mode'):
        if approvals_added:
            settings.allow_manager_approvals = 1
        if not settings.get('matrix_mode'):
            settings.matrix_mode = DISCOUNT_MODE
        settings.save(ignore_permissions=True)
    if not settings.get('mappings_initialized'):
        # Seed once. An intentionally emptied table must remain empty on migration.
        if not settings.get('customer_mappings'):
            for group, column in policy()[1].items():
                settings.append('customer_mappings', {'customer_group': group, 'matrix_column': column})
        settings.mappings_initialized = 1
        settings.save(ignore_permissions=True)
    if not settings.get('limits_initialized'):
        # Seed once from the bundled policy. Later edits and deletions are preserved.
        if not settings.get('discount_limits'):
            for row in default_limit_rows():
                if frappe.db.exists('Item Group', row['item_group']):
                    settings.append('discount_limits', row)
                else:
                    print(f"VDM: Item Group {row['item_group']} does not exist on this site; not added to the discount matrix.")
        settings.limits_initialized = 1
        settings.save(ignore_permissions=True)
    if not settings.get('margins_initialized'):
        # Seed once with the discount matrix's Item Groups at 0% so only the
        # percentages need entering. Nothing is enforced until Margin Matrix is selected.
        if not settings.get('margin_limits'):
            for row in settings.get('discount_limits') or []:
                settings.append('margin_limits', dict(item_group=row.item_group, solution_line=row.solution_line,
                    category=row.category, **{name: 0 for name in LIMIT_FIELDS.values()}))
        settings.margins_initialized = 1
        settings.save(ignore_permissions=True)
    update_simulation_basis()
    install_approval_view()
    install_transaction_fields()
    install_lead_fields()
    install_sidebar()


def limit_fields():
    return [
        field('item_group', 'Item Group', 'Link', options='Item Group', reqd=1, in_list_view=1, columns=3),
        *[field(name, column + ' %', 'Percent', precision='3', in_list_view=1, columns=1)
          for column, name in LIMIT_FIELDS.items()],
        field('solution_line', 'Solution Line'),
        field('category', 'Category'),
    ]


def simulation_item_fields():
    ro = dict(read_only=1)
    return [
        field('item_code', 'Item', 'Link', options='Item', reqd=1, in_list_view=1, columns=2),
        field('item_name', 'Item Name', **ro),
        field('item_group', 'Item Group', 'Link', options='Item Group', **ro),
        field('stock_uom', 'Stock UOM', 'Link', options='UOM', **ro),
        field('current_price', 'Current Standard Selling', 'Currency', in_list_view=1, columns=1, **ro),
        field('proposed_price', 'Proposed Price', 'Currency', in_list_view=1, columns=1,
              description='Per stock UOM. Blank starts at the current price.'),
        field('price_change', 'Price Change', 'Percent', **ro),
        field('cost', 'Cost', 'Currency', in_list_view=1, columns=1, **ro),
        field('cost_source', 'Cost Source', **ro),
        field('history_qty', 'Qty Sold', 'Float', in_list_view=1, columns=1, **ro),
        field('history_revenue', 'Historical Revenue', 'Currency', **ro),
        field('history_profit', 'Historical Profit at Current Cost', 'Currency', **ro),
        field('projected_revenue', 'Projected Revenue', 'Currency', **ro),
        field('projected_profit', 'Projected Profit', 'Currency', in_list_view=1, columns=2, **ro),
        field('projected_margin', 'Projected Margin', 'Percent', in_list_view=1, columns=1, **ro),
        field('lowest_floor_margin', 'Lowest Margin at Max Discount', 'Percent', in_list_view=1, columns=1, **ro),
        field('warnings', 'Warnings', 'Small Text', **ro),
        field('column_detail', 'Matrix Column Detail', 'Long Text', hidden=1, **ro),
    ]


BASIS_OPTIONS = 'Historical discount\nMaximum matrix discount\nKeep price paid'
BASIS_DESCRIPTION = ('Historical: each customer group keeps its past discount off today\'s Standard Selling price, capped at the matrix maximum. '
                     'Maximum: every sale at the highest discount the matrix allows (worst case). '
                     'Keep price paid: each group keeps paying its past average price, but not above the proposed price '
                     'or below the matrix floor - use this to test lowering list prices while keeping net prices.')


def update_simulation_basis():
    """Sites installed on 0.10.x keep their DocType; refresh the projection basis choices."""
    if not frappe.db.exists('DocType', 'VDM Price Simulation'):
        return
    simulation = frappe.get_doc('DocType', 'VDM Price Simulation')
    changed = False
    for df in simulation.fields:
        if df.fieldname == 'projection_basis' and (df.options != BASIS_OPTIONS or df.description != BASIS_DESCRIPTION):
            df.options, df.description, changed = BASIS_OPTIONS, BASIS_DESCRIPTION, True
    if changed:
        simulation.save(ignore_permissions=True)
        frappe.clear_cache(doctype='VDM Price Simulation')
    return changed


def simulation_fields():
    ro = dict(read_only=1)
    return [
        field('title', 'Title', reqd=1, in_list_view=1),
        field('company', 'Company', 'Link', options='Company', reqd=1),
        field('projection_basis', 'Projection Basis', 'Select', options=BASIS_OPTIONS,
              default='Historical discount', reqd=1, description=BASIS_DESCRIPTION),
        field('column_break_settings', '', 'Column Break'),
        field('from_date', 'Sales History From', 'Date', reqd=1),
        field('to_date', 'Sales History To', 'Date', reqd=1),
        field('column_break_filters', '', 'Column Break'),
        field('item_group', 'Load Item Group', 'Link', options='Item Group',
              description='Load Items adds this group only. Blank loads every discount-matrix group.'),
        field('only_sold_items', 'Load Only Items Sold in Period', 'Check', default='1'),
        field('warehouse', 'Cost Warehouse', 'Link', options='Warehouse',
              description='Valuation rate from this warehouse first; otherwise Item valuation rate, then last purchase rate.'),
        field('section_items', 'Items', 'Section Break',
              description='Change Proposed Price and save to recalculate. Saving also refreshes prices, costs and sales history.'),
        field('items', 'Items', 'Table', options='VDM Simulation Item', allow_bulk_edit=1),
        field('section_results', 'Results', 'Section Break'),
        field('history_revenue', 'Historical Revenue', 'Currency', **ro),
        field('history_profit', 'Historical Profit at Current Cost', 'Currency', **ro),
        field('column_break_results', '', 'Column Break'),
        field('projected_revenue', 'Projected Revenue', 'Currency', **ro),
        field('projected_profit', 'Projected Profit', 'Currency', **ro),
        field('projected_margin', 'Projected Margin', 'Percent', **ro),
        field('section_detail', 'Detail by Customer Column', 'Section Break'),
        field('results_html', 'Simulation Detail', 'HTML'),
    ]


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
    order = ['enabled', 'allow_manager_approvals', 'matrix_mode', 'price_list',
             'customer_mappings', 'mappings_initialized', 'discount_limits', 'limits_initialized',
             'margin_limits', 'margins_initialized']
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
        ('Price Simulations', 'DocType', 'VDM Price Simulation', 'chart'),
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


def install_lead_fields():
    create_custom_fields({'Lead': [field(
        'custom_customer_group', 'Customer Group', 'Link', options='Customer Group',
        insert_after='lead_name',
        description='Used by Discount Matrix for quotations addressed to this Lead. Select before quoting matrix-controlled items.',
    )]}, ignore_validate=True, update=True)

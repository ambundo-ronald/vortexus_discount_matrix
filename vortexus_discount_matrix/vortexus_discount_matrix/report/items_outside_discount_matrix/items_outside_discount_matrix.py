import frappe
from vortexus_discount_matrix.core import policy


def execute(filters=None):
    filters = filters or {}
    frappe.has_permission('Item', 'read', throw=True)
    query = {}
    if filters.get('item_group'):
        query['item_group'] = filters['item_group']
    if str(filters.get('include_disabled', 1)) in ('0', 'False'):
        query['disabled'] = 0
    if str(filters.get('sales_items_only', 0)) in ('1', 'True'):
        query['is_sales_item'] = 1
    # get_list respects Item permissions; unlimited page length avoids truncating at 20.
    items = frappe.get_list('Item', filters=query,
        fields=['name', 'item_name', 'item_group', 'stock_uom', 'is_sales_item', 'disabled'],
        order_by='item_group asc, name asc', limit_page_length=0)
    groups, _ = policy()
    data = [{**item, 'reason': 'Item Group has no accepted matrix mapping'}
        for item in items if item.get('item_group') not in groups]
    columns = [
        dict(fieldname='name', label='Item Code', fieldtype='Link', options='Item', width=200),
        dict(fieldname='item_name', label='Item Name', fieldtype='Data', width=260),
        dict(fieldname='item_group', label='Item Group', fieldtype='Link', options='Item Group', width=220),
        dict(fieldname='stock_uom', label='Stock UOM', fieldtype='Link', options='UOM', width=100),
        dict(fieldname='is_sales_item', label='Sales Item', fieldtype='Check', width=100),
        dict(fieldname='disabled', label='Disabled', fieldtype='Check', width=90),
        dict(fieldname='reason', label='Reason', fieldtype='Data', width=320),
    ]
    summary = [dict(label='Items Outside Matrix', value=len(data), datatype='Int', indicator='Orange'),
        dict(label='Unmapped Item Groups', value=len({r['item_group'] for r in data}), datatype='Int', indicator='Orange')]
    message = 'Shows items visible to you whose exact Item Group has no accepted mapping. Includes intentionally excluded groups. Customer mappings and transaction discount violations are not evaluated here.'
    return columns, data, message, None, summary

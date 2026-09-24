frappe.query_reports['Items Outside Discount Matrix'] = {
  filters: [
    {fieldname: 'item_group', label: __('Item Group'), fieldtype: 'Link', options: 'Item Group'},
    {fieldname: 'include_disabled', label: __('Include Disabled Items'), fieldtype: 'Check', default: 1},
    {fieldname: 'sales_items_only', label: __('Sales Items Only'), fieldtype: 'Check', default: 0},
  ],
};

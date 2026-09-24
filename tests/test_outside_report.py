import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

MODULE = 'vortexus_discount_matrix.vortexus_discount_matrix.report.items_outside_discount_matrix.items_outside_discount_matrix'


class OutsideReportTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType('frappe')
        self.frappe.has_permission = Mock()
        self.frappe.get_list = Mock(return_value=[
            dict(name='A', item_name='Mapped', item_group='Filters and Catridges', stock_uom='Nos', is_sales_item=1, disabled=0),
            dict(name='B', item_name='Excluded', item_group='POOL PUMP', stock_uom='Nos', is_sales_item=1, disabled=0),
            dict(name='C', item_name='New', item_group='New Group', stock_uom='Nos', is_sales_item=0, disabled=1),
        ])
        self.patch = patch.dict(sys.modules, {'frappe': self.frappe})
        self.patch.start()
        sys.modules.pop(MODULE, None)
        self.report = importlib.import_module(MODULE)

    def tearDown(self):
        sys.modules.pop(MODULE, None)
        self.patch.stop()

    def test_all_unmapped_including_excluded_and_disabled(self):
        _, data, _, _, summary = self.report.execute()
        self.assertEqual([r['name'] for r in data], ['B', 'C'])
        self.assertEqual(summary[0]['value'], 2)
        self.assertEqual(summary[1]['value'], 2)
        self.frappe.has_permission.assert_called_once_with('Item', 'read', throw=True)
        self.assertEqual(self.frappe.get_list.call_args.kwargs['limit_page_length'], 0)
        self.assertEqual(self.frappe.get_list.call_args.kwargs['filters'], {})

    def test_filters_are_forwarded_to_permission_aware_query(self):
        self.report.execute({'item_group':'New Group', 'include_disabled':0, 'sales_items_only':1})
        self.assertEqual(self.frappe.get_list.call_args.kwargs['filters'], {'item_group':'New Group', 'disabled':0, 'is_sales_item':1})

    def test_empty_result_has_zero_counts(self):
        self.frappe.get_list.return_value = []
        _, data, _, _, summary = self.report.execute()
        self.assertEqual(data, [])
        self.assertEqual([s['value'] for s in summary], [0, 0])

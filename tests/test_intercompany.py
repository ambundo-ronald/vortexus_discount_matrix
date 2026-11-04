"""Intercompany pricing: group companies are priced at system cost plus the markup."""
import importlib
import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch
import test_approval
from vortexus_discount_matrix.core import intercompany_rate


class Row(dict):
    __getattr__ = dict.get
    def __setattr__(self, key, value):
        self[key] = value
    def precision(self, field):
        return 2


class Doc(types.SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class IntercompanyRateTests(unittest.TestCase):
    def test_cost_plus_ten_percent(self):
        self.assertEqual(intercompany_rate(1000, 10), Decimal('1100.00'))

    def test_rounds_up_never_below_markup(self):
        self.assertEqual(intercompany_rate('333.333', 10), Decimal('366.67'))

    def test_zero_markup_is_cost(self):
        self.assertEqual(intercompany_rate(500, 0), Decimal('500.00'))

    def test_rejects_missing_cost_or_negative_markup(self):
        for cost, markup in ((0, 10), (-5, 10), (100, -1)):
            with self.assertRaises(ValueError):
                intercompany_rate(cost, markup)


class IntercompanyApplyTests(unittest.TestCase):
    setUp = test_approval.ApprovalTests.setUp
    tearDown = test_approval.ApprovalTests.tearDown

    def setup_case(self, group='Intercompany', settings=None, costs=None):
        values = dict(intercompany_pricing=1, intercompany_customer_group='Intercompany', intercompany_markup=10)
        values.update(settings or {})
        self.frappe.db.get_single_value.side_effect = lambda dt, field: values.get(field)
        self.frappe.db.get_value.side_effect = lambda dt, name, field: group if dt == 'Customer' else None
        self.frappe.msgprint = Mock()
        sys.modules.pop('vortexus_discount_matrix.intercompany', None)
        ic = importlib.import_module('vortexus_discount_matrix.intercompany')
        prices = types.ModuleType('vortexus_discount_matrix.prices')
        costs = costs if costs is not None else {'FRP': 2780.0, 'GAUGE': 441.26}
        prices.cost_rate = lambda doc, row, basis=None: (costs.get(row.item_code), 'System cost (FIFO)') if costs.get(row.item_code) else (None, None)
        self.calls = Mock()
        taxes = sys.modules['erpnext.controllers.taxes_and_totals']
        taxes.calculate_taxes_and_totals = self.calls
        self.patch = patch.dict(sys.modules, {'vortexus_discount_matrix.prices': prices})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(lambda: sys.modules.pop('vortexus_discount_matrix.intercompany', None))
        return ic

    def doc(self, *rows, doctype='Sales Order', docstatus=0):
        return Doc(doctype=doctype, customer='Norwa Water Solutions Limited', docstatus=docstatus, items=list(rows))

    def test_prices_lines_at_cost_plus_markup_and_clears_discount(self):
        ic = self.setup_case()
        row = Row(idx=1, item_code='FRP', rate=9580, price_list_rate=9580, discount_percentage=25)
        message = ic.apply(self.doc(row))
        self.assertEqual(row.rate, 3058.0)
        self.assertEqual(row.price_list_rate, 3058.0)
        self.assertEqual(row.discount_percentage, 0)
        self.calls.assert_called_once()
        self.assertIn('cost + 10%', message)

    def test_markup_comes_from_settings(self):
        ic = self.setup_case(settings={'intercompany_markup': 15})
        row = Row(idx=1, item_code='GAUGE', rate=771)
        ic.apply(self.doc(row))
        self.assertEqual(row.rate, 507.45)

    def test_line_copied_from_earlier_document_keeps_its_price(self):
        ic = self.setup_case()
        row = Row(idx=1, item_code='FRP', rate=3000, sales_order='SO-1', so_detail='x')
        message = ic.apply(self.doc(row, doctype='Sales Invoice'))
        self.assertEqual(row.rate, 3000)
        self.calls.assert_not_called()
        self.assertIn('keep the price', message)

    def test_line_without_cost_is_left_for_manual_price(self):
        ic = self.setup_case()
        row = Row(idx=2, item_code='NOCOST', rate=500)
        message = ic.apply(self.doc(row))
        self.assertEqual(row.rate, 500)
        self.assertIn('no cost', message)
        self.frappe.msgprint.assert_called_once()

    def test_other_customer_groups_are_untouched(self):
        ic = self.setup_case(group='Dealers')
        row = Row(idx=1, item_code='FRP', rate=9580)
        self.assertIsNone(ic.apply(self.doc(row)))
        self.assertEqual(row.rate, 9580)

    def test_switched_off_in_settings(self):
        ic = self.setup_case(settings={'intercompany_pricing': 0})
        row = Row(idx=1, item_code='FRP', rate=9580)
        self.assertIsNone(ic.apply(self.doc(row)))
        self.assertEqual(row.rate, 9580)

    def test_submitted_documents_and_returns_are_not_repriced(self):
        ic = self.setup_case()
        row = Row(idx=1, item_code='FRP', rate=9580)
        self.assertIsNone(ic.apply(self.doc(row, docstatus=1)))
        returned = self.doc(Row(idx=1, item_code='FRP', rate=9580), doctype='Sales Invoice')
        returned.is_return = 1
        self.assertIsNone(ic.apply(returned))
        self.assertEqual(row.rate, 9580)

    def test_quotation_uses_party_name(self):
        ic = self.setup_case()
        row = Row(idx=1, item_code='FRP', rate=9580)
        doc = Doc(doctype='Quotation', quotation_to='Customer', party_name='Everfresh', docstatus=0, items=[row])
        ic.apply(doc)
        self.assertEqual(row.rate, 3058.0)

    def test_quotation_to_converted_crm_deal(self):
        ic = self.setup_case()
        self.frappe.db.get_value.side_effect = lambda dt, name, field: (
            'Everfresh' if dt == 'CRM Deal' else 'Intercompany' if dt == 'Customer' and name == 'Everfresh' else None)
        row = Row(idx=1, item_code='FRP', rate=9580)
        doc = Doc(doctype='Quotation', quotation_to='CRM Deal', party_name='CRM-DEAL-1', docstatus=0, items=[row])
        ic.apply(doc)
        self.assertEqual(row.rate, 3058.0)

    def test_unconverted_crm_deal_is_not_intercompany(self):
        ic = self.setup_case()
        self.frappe.db.get_value.side_effect = lambda dt, name, field: None
        row = Row(idx=1, item_code='FRP', rate=9580)
        doc = Doc(doctype='Quotation', quotation_to='CRM Deal', party_name='CRM-DEAL-2', docstatus=0, items=[row])
        self.assertIsNone(ic.apply(doc))

    def test_quotation_to_lead_is_not_intercompany(self):
        ic = self.setup_case()
        row = Row(idx=1, item_code='FRP', rate=9580)
        doc = Doc(doctype='Quotation', quotation_to='Lead', party_name='LEAD-1', docstatus=0, items=[row])
        self.assertIsNone(ic.apply(doc))


class IntercompanySettingsTests(unittest.TestCase):
    setUp = test_approval.ApprovalTests.setUp
    tearDown = test_approval.ApprovalTests.tearDown

    def validate(self, **values):
        sys.modules.pop('vortexus_discount_matrix.settings', None)
        settings = importlib.import_module('vortexus_discount_matrix.settings')
        doc = Row(matrix_mode='Discount Matrix', cost_tolerance=5, customer_mappings=[], discount_limits=[], margin_limits=[],
                  intercompany_customer_group='Intercompany', intercompany_markup=10)
        doc.update(values)
        settings.validate(doc)

    def test_valid_settings_pass(self):
        self.validate()

    def test_intercompany_group_cannot_be_mapped(self):
        with self.assertRaisesRegex(ValueError, 'cannot also be mapped'):
            self.validate(customer_mappings=[Row(customer_group='Intercompany', matrix_column='Dealers')])

    def test_markup_range(self):
        with self.assertRaisesRegex(ValueError, 'markup'):
            self.validate(intercompany_markup=-1)


if __name__ == '__main__':
    unittest.main()

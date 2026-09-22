import copy
import sys
import types
import unittest
from unittest.mock import Mock, patch
import test_approval


class Record(dict):
    def __getattr__(self, key):
        if key in self:
            return self[key]
        return None
    def __setattr__(self, key, value):
        self[key] = value
    def __deepcopy__(self, memo):
        return type(self)({k: copy.deepcopy(v, memo) for k, v in dict.items(self)})
    def precision(self, field):
        return 2


class SalesDoc(Record):
    @property
    def items(self):
        return self['items']
    def as_dict(self):
        return copy.deepcopy(self)
    def is_new(self):
        return False


class EnforcementTests(unittest.TestCase):
    setUp = test_approval.ApprovalTests.setUp
    tearDown = test_approval.ApprovalTests.tearDown

    def scenario(self, doctype='Sales Order', rate=150, mapped=True):
        item = Record(idx=1, item_code='TEST-RO', qty=1, uom='Nos', conversion_factor=1, rate=rate, net_rate=rate)
        doc = SalesDoc(doctype=doctype, name='TEST-1', customer='CUSTOMER-1', quotation_to='Customer', party_name='CUSTOMER-1', items=[item], taxes=[], discount_amount=0)
        item_group = 'Ro Systems' if mapped else 'Unmapped Group'
        self.frappe.db.get_value.side_effect = lambda dt, name, field: item_group if dt == 'Item' else 'Technician'
        self.frappe.db.exists.return_value = False
        self.frappe.get_doc.side_effect = lambda *args: copy.deepcopy(args[0]) if isinstance(args[0], dict) else doc
        return doc

    def inspect_patches(self):
        settings = types.ModuleType('vortexus_discount_matrix.settings')
        settings.customer_mappings = lambda: {'Technician': 'Technicians'}
        def calculate(doc):
            for row in doc.items:
                row.net_rate = row.rate - (doc.get('discount_amount') or 0) / row.qty
                row.net_amount = row.net_rate * row.qty
        stack = __import__('contextlib').ExitStack()
        stack.enter_context(patch.dict(sys.modules, {settings.__name__: settings}))
        stack.enter_context(patch.object(self.v, 'reference_rate', return_value=(500, 'PRICE-1')))
        stack.enter_context(patch.object(self.v, 'calculate_taxes_and_totals', side_effect=calculate))
        return stack

    def test_500_to_150_is_blocked_for_all_sales_documents(self):
        for doctype in self.v.DOCTYPES:
            doc = self.scenario(doctype)
            with self.inspect_patches():
                result = self.v.inspect(doc)
                self.assertEqual(result['status'], 'Adjust Price')
                self.assertEqual(result['lines'][0]['effective_discount'], 70)
                self.assertEqual(result['lines'][0]['minimum_net_rate'], 320)
                self.v.validate(doc)  # Draft remains available for explicit manager action.
                with self.assertRaisesRegex(ValueError, 'Increase the selling price'):
                    self.v.before_submit(doc)
                with self.assertRaises(ValueError):
                    self.v.on_submit(doc)

    def test_exact_limit_is_allowed(self):
        doc = self.scenario(rate=320)
        with self.inspect_patches():
            self.v.before_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Within Limit')

    def test_additional_discount_breach_is_blocked(self):
        doc = self.scenario(rate=350)
        doc.discount_amount = 40
        with self.inspect_patches():
            with self.assertRaises(ValueError):
                self.v.before_submit(doc)

    def test_exception_requires_stored_matching_approval(self):
        doc = self.scenario()
        self.frappe.db.exists.return_value = True
        with self.inspect_patches():
            self.v.before_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Approved Exception')
            query = self.frappe.db.exists.call_args.args[1]
            self.assertEqual(query['reference_name'], 'TEST-1')
            self.assertTrue(query['fingerprint'])

    def test_unmapped_item_reports_reason_without_expanding_scope(self):
        doc = self.scenario(mapped=False)
        with self.inspect_patches():
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Not Applicable')
        self.assertIn('No items were checked', result['message'])
        self.assertEqual(result['excluded_rows'][0]['item_group'], 'Unmapped Group')

    def test_string_zero_means_disabled(self):
        self.frappe.db.get_single_value.return_value = '0'
        self.assertFalse(self.v.enabled())

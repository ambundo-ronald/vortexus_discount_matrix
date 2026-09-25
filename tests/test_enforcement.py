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

    def test_quotation_approval_flows_through_order_to_invoice(self):
        quote = self.scenario('Quotation')
        quote.name = 'Q-1'
        quote.docstatus = 1
        quote.items[0].name = 'QI-1'
        order = copy.deepcopy(quote)
        order.doctype = 'Sales Order'
        order.name = 'SO-1'
        order.docstatus = 1
        order.items[0].name = 'SOI-1'
        order.items[0].prevdoc_docname = 'Q-1'
        order.items[0].quotation_item = 'QI-1'
        invoice = copy.deepcopy(order)
        invoice.doctype = 'Sales Invoice'
        invoice.name = 'SI-1'
        invoice.docstatus = 0
        invoice.items[0].sales_order = 'SO-1'
        invoice.items[0].so_detail = 'SOI-1'
        docs = {'Q-1': quote, 'SO-1': order, 'SI-1': invoice}
        self.frappe.get_doc.side_effect = lambda *args: copy.deepcopy(args[0]) if isinstance(args[0], dict) else docs[args[1]]
        self.frappe.db.sql.return_value = []
        with self.inspect_patches():
            approved_hash = self.v.inspect(quote)['fingerprint']
            self.frappe.db.exists.side_effect = lambda dt, value: (value.get('reference_name') == 'Q-1' and value.get('fingerprint') == approved_hash) if dt == 'VDM Approval' else value in docs
            self.v.before_submit(order)
            self.assertEqual(order.custom_vdm_status, 'Inherited Exception')
            self.v.before_submit(invoice)
            self.assertEqual(invoice.custom_vdm_status, 'Inherited Exception')
            invoice.items[0].rate = 149
            with self.assertRaises(ValueError):
                self.v.before_submit(invoice)

    def test_existing_approval_does_not_bypass_disabled_exceptions(self):
        doc = self.scenario()
        self.frappe.db.exists.return_value = True
        self.frappe.db.get_single_value.side_effect = lambda dt, field: field == 'enabled'
        with self.inspect_patches():
            with self.assertRaisesRegex(ValueError, 'Increase the selling price'):
                self.v.before_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Adjust Price')
            self.frappe.db.exists.assert_not_called()

    def test_valid_approved_terms_allow_submission_when_enabled(self):
        doc = self.scenario()
        self.frappe.db.exists.return_value = True
        with self.inspect_patches():
            self.v.before_submit(doc)
            self.v.on_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Approved Exception')


    def test_quotation_legacy_approval_survives_transient_customer_alias(self):
        import json
        doc = self.scenario('Quotation')
        doc.customer = None
        with self.inspect_patches():
            approved = self.v.inspect(doc)['snapshot']
            original = json.dumps(approved, default=str)
            self.frappe.get_all.return_value = [{'name': 'APPROVAL-1', 'snapshot': original}]
            doc.customer = doc.party_name
            self.v.before_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Approved Exception')
            self.assertEqual(json.dumps(approved, default=str), original)
            doc.customer = None
            self.v.on_submit(doc)
            # A real customer change must still require new approval.
            doc.party_name = 'CUSTOMER-2'
            doc.customer = 'CUSTOMER-2'
            with self.assertRaisesRegex(ValueError, 'party_name'):
                self.v.before_submit(doc)
            doc.party_name = 'CUSTOMER-1'
            doc.customer = None
            doc.items[0].rate = 140
            with self.assertRaises(ValueError):
                self.v.before_submit(doc)

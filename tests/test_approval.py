"""Adapter tests with controlled Frappe doubles; not a substitute for bench tests."""
import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        frappe = types.ModuleType('frappe')
        frappe.whitelist = lambda: lambda f: f
        frappe.PermissionError = PermissionError
        def throw(message, kind=ValueError):
            raise kind(message)
        frappe.throw = throw
        frappe.get_roles = Mock(return_value=['Sales Manager'])
        frappe.db = Mock()
        frappe.db.get_single_value.return_value = True
        frappe.session = types.SimpleNamespace(user='manager@example.test')
        frappe.utils = types.ModuleType('frappe.utils')
        frappe.utils.flt = lambda v, precision=None: round(float(v or 0), precision) if precision is not None else float(v or 0)
        frappe.utils.now_datetime = lambda: '2026-09-21 12:00:00'
        frappe.utils.getdate = lambda v: v
        frappe.get_doc = Mock()
        taxes = types.ModuleType('erpnext.controllers.taxes_and_totals')
        taxes.calculate_taxes_and_totals = Mock()
        details = types.ModuleType('erpnext.stock.get_item_details')
        details.get_conversion_factor = Mock()
        self.modules = patch.dict(sys.modules, {'frappe': frappe, 'frappe.utils': frappe.utils,
            'erpnext.controllers.taxes_and_totals': taxes, 'erpnext.stock.get_item_details': details})
        self.modules.start()
        for name in ['vortexus_discount_matrix.validation', 'vortexus_discount_matrix.prices']:
            sys.modules.pop(name, None)
        self.v = importlib.import_module('vortexus_discount_matrix.validation')
        self.frappe = frappe

    def tearDown(self):
        for name in ['vortexus_discount_matrix.validation', 'vortexus_discount_matrix.prices']:
            sys.modules.pop(name, None)
        self.modules.stop()

    def test_salesperson_cannot_approve(self):
        self.frappe.get_roles.return_value = ['Sales User']
        with self.assertRaises(PermissionError):
            self.v.approve('Sales Order', 'SO-1', 'Allowed by manager')
        self.frappe.get_doc.assert_not_called()

    def test_blank_reason_rejected(self):
        with self.assertRaisesRegex(ValueError, 'reason'):
            self.v.approve('Sales Order', 'SO-1', '  \n ')
        self.frappe.get_doc.assert_not_called()

    def test_arbitrary_doctype_rejected(self):
        with self.assertRaises(ValueError):
            self.v.approve('User', 'Administrator', 'x')
        self.frappe.db.sql.assert_not_called()

    def test_approval_reads_saved_doc_and_records_reason(self):
        doc = Mock(docstatus=0)
        approval = Mock()
        self.frappe.get_doc.side_effect = [doc, approval]
        with patch.object(self.v, 'inspect', return_value={'violations': [1], 'fingerprint': 'terms', 'snapshot': {'price': 55}}):
            self.v.approve('Sales Order', 'SO-1', '  Contract exception  ')
        doc.check_permission.assert_called_once_with('write')
        payload = self.frappe.get_doc.call_args_list[1].args[0]
        self.assertEqual(payload['reason'], 'Contract exception')
        self.assertEqual(payload['approved_by'], 'manager@example.test')
        self.assertEqual(payload['fingerprint'], 'terms')
        approval.insert.assert_called_once_with(ignore_permissions=True)
        doc.save.assert_called_once()

    def test_submitted_document_cannot_receive_approval(self):
        self.frappe.get_doc.return_value = Mock(docstatus=1)
        with self.assertRaisesRegex(ValueError, 'saved drafts'):
            self.v.approve('Sales Order', 'SO-1', 'Exception')

    def test_submit_blocks_even_if_caller_sets_approved_status(self):
        doc = types.SimpleNamespace(custom_vdm_status='Approved Exception', custom_vdm_summary='')
        result = {'status': 'Adjust Price', 'violations': []}
        with patch.object(self.v, 'inspect', return_value=result):
            with self.assertRaisesRegex(ValueError, 'Increase the selling price'):
                self.v.before_submit(doc)

    def test_disabled_feature_does_not_inspect(self):
        self.frappe.db.get_single_value.return_value = False
        with patch.object(self.v, 'inspect') as inspect:
            self.v.validate(types.SimpleNamespace())
            inspect.assert_not_called()

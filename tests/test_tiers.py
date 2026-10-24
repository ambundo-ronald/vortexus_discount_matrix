"""0.11: discount and margin together, below-cost block, MD approvals and cost tolerance."""
import json
import unittest
from unittest.mock import patch
import test_enforcement
from vortexus_discount_matrix.core import LIMIT_FIELDS, limits_from_rows, default_limit_rows


class TierTests(unittest.TestCase):
    # Reuse the enforcement scenario: Ro Systems, Technicians, Standard Selling 500.
    setUp = test_enforcement.EnforcementTests.setUp
    tearDown = test_enforcement.EnforcementTests.tearDown
    scenario = test_enforcement.EnforcementTests.scenario
    inspect_patches = test_enforcement.EnforcementTests.inspect_patches
    def both(self, margin=30, cost=100, block=True):
        discounts = limits_from_rows(default_limit_rows())  # Ro Systems Technicians: 36% -> floor 320
        margins = limits_from_rows([dict(item_group='Ro Systems', **{f: margin for f in LIMIT_FIELDS.values()})], 'Margin Matrix')
        self.enforced = ('Discount and Margin', discounts, margins)
        self.controls = dict(block_below_cost=block)
        stack = self.inspect_patches()
        self.cost = stack.enter_context(patch.object(self.v, 'cost_rate', return_value=(cost, 'System cost (FIFO)')))
        return stack

    def test_discount_breach_above_margin_needs_sales_manager(self):
        doc = self.scenario(rate=300)  # below 320 discount floor, margin (300-100)/300 = 67%
        with self.both():
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Adjust Price')
        self.assertEqual(result['required_level'], 'Sales Manager')
        line = result['lines'][0]
        self.assertEqual((line['minimum_net_rate'], line['margin_floor'], line['max_discount'], line['min_margin']), (320, 142.86, 36, 30))
        self.assertIn('Sales Manager or MD', result['message'])
        self.assertEqual(result['snapshot']['matrix_mode'], 'Discount and Margin')

    def test_margin_breach_needs_md(self):
        doc = self.scenario(rate=140)  # above cost, below the 142.86 margin floor
        with self.both():
            result = self.v.inspect(doc)
            self.v.validate(doc)
        self.assertEqual(result['required_level'], 'Margin Approver')
        self.assertIn('approval by MD', result['message'])
        self.assertIn('Needs approval by MD', doc.custom_vdm_summary)

    def test_below_cost_is_blocked_and_cannot_be_approved(self):
        doc = self.scenario(rate=90)
        doc.docstatus, doc.check_permission = 0, lambda *a: None
        self.frappe.db.exists.return_value = True  # even an existing approval record changes nothing
        with self.both():
            result = self.v.inspect(doc)
            self.assertEqual(result['status'], 'Below Cost')
            self.assertTrue(result['lines'][0]['below_cost'])
            with self.assertRaisesRegex(ValueError, 'below cost'):
                self.v.before_submit(doc)
            self.frappe.get_roles.return_value = ['MD']
            self.frappe.db.sql.return_value = []
            with self.assertRaisesRegex(ValueError, 'cannot be approved'):
                self.v.approve('Sales Order', 'TEST-1', 'Customer promise')

    def test_below_cost_block_applies_in_discount_mode(self):
        doc = self.scenario(rate=90)
        self.controls = dict(block_below_cost=True)
        with self.inspect_patches(), patch.object(self.v, 'cost_rate', return_value=(100, 'System cost (FIFO)')):
            self.assertEqual(self.v.inspect(doc)['status'], 'Below Cost')
        with self.inspect_patches(), patch.object(self.v, 'cost_rate', return_value=(None, None)):
            result = self.v.inspect(doc)  # unknown cost in discount mode: discount rule only
        self.assertEqual(result['status'], 'Adjust Price')
        self.assertEqual(result['required_level'], 'Sales Manager')

    def test_block_can_be_switched_off(self):
        doc = self.scenario(rate=90)
        with self.both(block=False):
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Adjust Price')
        self.assertEqual(result['required_level'], 'Margin Approver')

    def test_unknown_cost_with_margin_rule_needs_md_but_does_not_block_saving(self):
        doc = self.scenario(rate=400)
        with self.both(cost=None):
            self.cost.return_value = (None, None)
            result = self.v.inspect(doc)
            self.v.validate(doc)
        self.assertEqual(result['required_level'], 'Margin Approver')
        self.assertIn('no cost was found', doc.custom_vdm_summary)

    def test_sales_manager_cannot_approve_margin_breach_but_md_can(self):
        doc = self.scenario(rate=140)
        doc.docstatus, doc.check_permission = 0, lambda *a: None
        self.frappe.db.sql.return_value = []
        with self.both():
            self.frappe.get_roles.return_value = ['Sales Manager']
            with self.assertRaisesRegex(PermissionError, 'need approval by MD'):
                self.v.approve('Sales Order', 'TEST-1', 'Volume deal')
            self.frappe.get_roles.return_value = ['MD']
            doc.save = lambda: None
            doc.db_set = lambda *a, **k: None
            inserted = []
            real = self.frappe.get_doc.side_effect
            def get_doc(*args):
                if isinstance(args[0], dict) and args[0].get('doctype') == 'VDM Approval':
                    record = test_enforcement.Record(args[0])
                    record.insert = lambda **kw: inserted.append(record)
                    return record
                return real(*args)
            self.frappe.get_doc.side_effect = get_doc
            self.v.approve('Sales Order', 'TEST-1', 'Volume deal')
        self.assertEqual(inserted[0]['approval_level'], 'Margin Approver')
        self.assertEqual(inserted[0]['approved_by'], 'manager@example.test')

    def approved(self, doc, level='Margin Approver', cost=100):
        with self.both(cost=cost):
            snapshot = self.v.inspect(doc)['snapshot']
        self.frappe.get_all.return_value = [{'name': 'A1', 'snapshot': json.dumps(snapshot), 'approval_level': level}]

    def test_md_approval_survives_small_cost_rise_but_not_large(self):
        doc = self.scenario(rate=140)
        self.approved(doc)
        with self.both(cost=104):  # +4% within the 5% tolerance; floor moves to 148.58, still approved
            self.assertEqual(self.v.inspect(doc)['status'], 'Approved Exception')
        with self.both(cost=106):
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Adjust Price')
        self.assertIn('Cost rose more than 5%', result['approval_mismatch'])

    def test_cost_fall_keeps_approval(self):
        doc = self.scenario(rate=140)
        self.approved(doc)
        with self.both(cost=99):
            self.assertEqual(self.v.inspect(doc)['status'], 'Approved Exception')

    def test_sales_manager_approval_does_not_cover_md_level(self):
        doc = self.scenario(rate=140)
        self.approved(doc, level='Sales Manager')
        with self.both():
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Adjust Price')
        self.assertIn('now need MD', result['approval_mismatch'])

    def test_price_change_still_needs_new_approval(self):
        doc = self.scenario(rate=140)
        self.approved(doc)
        doc.items[0].rate = 135
        with self.both():
            self.assertEqual(self.v.inspect(doc)['status'], 'Adjust Price')

    def test_existing_discount_approvals_survive_turning_on_the_cost_block(self):
        doc = self.scenario(rate=150)
        with self.inspect_patches():
            old = self.v.inspect(doc)  # 0.10 discount snapshot, no cost fields
        self.controls = dict(block_below_cost=True)
        with self.inspect_patches(), patch.object(self.v, 'cost_rate', return_value=(100, 'System cost (FIFO)')):
            new = self.v.inspect(doc)
        self.assertEqual(old['fingerprint'], new['fingerprint'])
        self.assertIn('cost_rate', new['lines'][0])
        self.assertNotIn('matrix_mode', new['snapshot'])

    def test_md_sees_the_approve_button(self):
        self.frappe.get_roles.return_value = ['MD']
        import sys, types
        settings = types.ModuleType('vortexus_discount_matrix.settings')
        settings.control_options = lambda: dict(block_below_cost=True, cost_basis='System cost (FIFO)', cost_tolerance=5.0, approver_role='MD')
        with patch.dict(sys.modules, {settings.__name__: settings}):
            self.assertEqual(self.v.approval_options(), {'allow_approval': True, 'approver_role': 'MD'})
            self.frappe.get_roles.return_value = ['Sales User']
            self.assertFalse(self.v.approval_options()['allow_approval'])


class LevelTests(unittest.TestCase):
    def test_level_ordering(self):
        from vortexus_discount_matrix.core import covers, required_level
        self.assertTrue(covers(None, 'Sales Manager'))  # pre-0.11 approvals are Sales Manager approvals
        self.assertFalse(covers(None, 'Margin Approver'))
        self.assertTrue(covers('Margin Approver', 'Sales Manager'))
        self.assertFalse(covers('Margin Approver', 'Below Cost'))
        self.assertEqual(required_level([{'level': 'Sales Manager'}, {'level': 'Margin Approver'}, {'level': None}]), 'Margin Approver')
        self.assertIsNone(required_level([]))

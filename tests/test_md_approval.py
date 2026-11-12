"""0.14: with approval chosen, only MD (with a reason) may approve below the margin floor and below cost."""
import json
import unittest
import test_enforcement
import test_tiers

APPROVE = 'Approval by margin approver'


class MdApprovalTests(unittest.TestCase):
    setUp = test_tiers.TierTests.setUp
    tearDown = test_tiers.TierTests.tearDown
    scenario = test_tiers.TierTests.scenario
    inspect_patches = test_tiers.TierTests.inspect_patches

    def md_mode(self, cost=100, floor=APPROVE, below_cost=APPROVE):
        stack = test_tiers.TierTests.both(self, margin=30, cost=cost)
        self.controls = dict(block_below_cost=True, margin_floor_action=floor, below_cost_action=below_cost)
        return stack

    def draft(self, rate):
        doc = self.scenario(rate=rate)
        doc.docstatus, doc.check_permission = 0, lambda *a: None
        doc.save = lambda **kw: None
        doc.db_set = lambda *a, **k: None
        self.frappe.db.sql.return_value = []
        self.inserted = []
        real = self.frappe.get_doc.side_effect
        def get_doc(*args):
            if isinstance(args[0], dict) and args[0].get('doctype') == 'VDM Approval':
                record = test_enforcement.Record(args[0])
                record.insert = lambda **kw: self.inserted.append(record)
                return record
            return real(*args)
        self.frappe.get_doc.side_effect = get_doc
        return doc

    def test_below_cost_shows_red_block_but_md_can_approve(self):
        doc = self.draft(rate=90)  # cost 100
        with self.md_mode():
            result = self.v.inspect(doc)
            self.assertEqual(result['status'], 'Below Cost')  # red block for the sales team
            self.assertEqual(result['required_level'], 'Margin Approver')  # MD can still approve on request
            self.assertTrue(result['lines'][0]['below_cost'])
            self.assertEqual(result['message'], 'A price is below cost. Selling below cost is blocked. Increase the selling price.')
            self.v.validate(doc)
            self.assertIn('BELOW COST 100: blocked.', doc.custom_vdm_summary)
            self.assertNotIn('MD', doc.custom_vdm_summary)
            self.assertNotIn('approv', doc.custom_vdm_summary.lower())
            with self.assertRaisesRegex(ValueError, 'Increase the selling price'):
                self.v.before_submit(doc)

    def test_only_md_can_approve_below_cost_and_a_reason_is_required(self):
        doc = self.draft(rate=90)
        with self.md_mode():
            for roles in (['Finance Manager'], ['Sales Manager'], ['Finance Manager', 'Sales Manager']):
                self.frappe.get_roles.return_value = roles
                with self.assertRaises(PermissionError):
                    self.v.approve('Sales Order', 'TEST-1', 'Clearance')
            self.frappe.get_roles.return_value = ['MD']
            with self.assertRaisesRegex(ValueError, 'reason'):
                self.v.approve('Sales Order', 'TEST-1', '   ')
            self.v.approve('Sales Order', 'TEST-1', 'Clearance of old stock')
        self.assertEqual(self.inserted[0]['approval_level'], 'Margin Approver')
        self.assertEqual(self.inserted[0]['reason'], 'Clearance of old stock')

    def test_md_approval_lets_below_cost_draft_submit(self):
        doc = self.draft(rate=90)
        with self.md_mode():
            snapshot = self.v.inspect(doc)['snapshot']
            self.frappe.get_all.return_value = [{'name': 'APPROVAL', 'snapshot': json.dumps(snapshot),
                                                  'approval_level': 'Margin Approver', 'reference_name': 'TEST-1'}]
            self.v.before_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Approved Exception')
            # A Finance Manager approval of the same terms is not enough.
            self.frappe.get_all.return_value[0]['approval_level'] = 'Discount Approver'
            with self.assertRaises(ValueError):
                self.v.before_submit(doc)
        self.frappe.get_all.return_value = []

    def test_below_floor_needs_md_only(self):
        doc = self.draft(rate=140)  # above cost 100, below the 142.86 floor
        with self.md_mode():
            result = self.v.inspect(doc)
            self.assertEqual(result['status'], 'Below Margin Floor')
            self.assertEqual(result['required_level'], 'Margin Approver')
            self.assertTrue(result['lines'][0]['below_floor'])
            self.frappe.get_roles.return_value = ['Finance Manager']
            with self.assertRaisesRegex(PermissionError, 'need approval by MD'):
                self.v.approve('Sales Order', 'TEST-1', 'Volume deal')
            self.frappe.get_roles.return_value = ['MD']
            self.v.approve('Sales Order', 'TEST-1', 'Volume deal')
        self.assertEqual(self.inserted[0]['approval_level'], 'Margin Approver')

    def test_block_settings_still_block_everyone(self):
        doc = self.draft(rate=90)
        with self.md_mode(below_cost='Block'):
            self.assertEqual(self.v.inspect(doc)['status'], 'Below Cost')
            self.frappe.get_roles.return_value = ['MD']
            with self.assertRaisesRegex(ValueError, 'cannot be approved'):
                self.v.approve('Sales Order', 'TEST-1', 'Clearance')
        doc = self.draft(rate=140)
        with self.md_mode(floor='Block'):
            self.assertEqual(self.v.inspect(doc)['status'], 'Below Margin Floor')

    def test_flags_do_not_change_approval_fingerprint(self):
        doc = self.draft(rate=140)
        with self.md_mode():
            approved = self.v.inspect(doc)['fingerprint']
        with self.md_mode(floor='Block'):
            self.assertEqual(self.v.inspect(doc)['fingerprint'], approved)

    def test_approve_button_offered_only_to_who_can_approve(self):
        below_cost, discount_only = self.draft(rate=90), self.draft(rate=300)  # 300: above the margin floor, below the 320 discount floor
        with self.md_mode():
            cost_result, discount_result = self.v.inspect(below_cost), self.v.inspect(discount_only)
            self.assertEqual(discount_result['required_level'], 'Sales Manager')
            for roles, on_cost, on_discount in ((['MD'], True, True), (['Finance Manager'], False, True),
                                                (['Sales Manager'], False, False), (['Sales User'], False, False)):
                self.frappe.get_roles.return_value = roles
                self.assertEqual(self.v.can_approve(cost_result), on_cost, roles)
                self.assertEqual(self.v.can_approve(discount_result), on_discount, roles)
        with self.md_mode(below_cost='Block'):
            self.frappe.get_roles.return_value = ['MD']
            self.assertFalse(self.v.can_approve(self.v.inspect(below_cost)))  # hard block: nobody
        self.assertFalse(self.v.can_approve({'violations': [], 'required_level': None}))

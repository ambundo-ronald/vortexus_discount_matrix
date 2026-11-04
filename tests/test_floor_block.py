"""0.12: a price below the margin floor is blocked outright when VDM Settings says Block."""
import unittest
from unittest.mock import patch
import test_tiers
from vortexus_discount_matrix.core import covers, BELOW_FLOOR


class FloorBlockTests(unittest.TestCase):
    setUp = test_tiers.TierTests.setUp
    tearDown = test_tiers.TierTests.tearDown
    scenario = test_tiers.TierTests.scenario
    inspect_patches = test_tiers.TierTests.inspect_patches

    def blocked(self, cost=100, action='Block'):
        stack = test_tiers.TierTests.both(self, margin=30, cost=cost)
        self.controls = dict(block_below_cost=True, margin_floor_action=action)
        return stack

    def test_below_floor_is_blocked_and_cannot_be_approved(self):
        doc = self.scenario(rate=140)  # above cost 100, below the 142.86 floor
        doc.docstatus, doc.check_permission = 0, lambda *a: None
        self.frappe.db.exists.return_value = True  # an existing approval record changes nothing
        with self.blocked():
            result = self.v.inspect(doc)
            self.assertEqual(result['status'], 'Below Margin Floor')
            self.assertEqual(result['required_level'], BELOW_FLOOR)
            self.assertTrue(result['lines'][0]['below_floor'])
            self.v.validate(doc)
            self.assertIn('BELOW MARGIN FLOOR 142.86: blocked', doc.custom_vdm_summary)
            with self.assertRaisesRegex(ValueError, 'margin floor'):
                self.v.before_submit(doc)
            self.frappe.get_roles.return_value = ['MD']
            self.frappe.db.sql.return_value = []
            with self.assertRaisesRegex(ValueError, 'cannot be approved'):
                self.v.approve('Sales Order', 'TEST-1', 'Big project')

    def test_at_the_floor_is_allowed(self):
        doc = self.scenario(rate=320)  # discount floor 320, margin (320-100)/320 = 69%
        with self.blocked():
            self.v.before_submit(doc)
        self.assertEqual(doc.custom_vdm_status, 'Within Limit')

    def test_below_cost_still_reported_as_below_cost(self):
        doc = self.scenario(rate=90)
        with self.blocked():
            self.assertEqual(self.v.inspect(doc)['status'], 'Below Cost')

    def test_unknown_cost_needs_sales_manager_when_floor_is_blocked(self):
        doc = self.scenario(rate=400)
        with self.blocked(cost=None):
            self.cost.return_value = (None, None)
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Adjust Price')
        self.assertEqual(result['required_level'], 'Sales Manager')

    def test_approval_mode_keeps_md_route(self):
        doc = self.scenario(rate=140)
        with self.blocked(action='Approval by margin approver'):
            result = self.v.inspect(doc)
        self.assertEqual(result['required_level'], 'Margin Approver')

    def test_no_approval_level_covers_a_blocked_floor(self):
        for level in ('Sales Manager', 'Margin Approver', None):
            self.assertFalse(covers(level, BELOW_FLOOR))


if __name__ == '__main__':
    unittest.main()

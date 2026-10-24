import importlib
import json
import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch
import test_approval
from test_enforcement import Record


class SimulationTests(unittest.TestCase):
    setUp_base = test_approval.ApprovalTests.setUp
    tearDown_base = test_approval.ApprovalTests.tearDown

    def setUp(self):
        self.setUp_base()
        self.frappe.utils.nowdate = lambda: '2026-10-23'
        self.frappe.get_cached_value = Mock(return_value='KES')
        self.frappe.db.get_value.side_effect = lambda dt, name, fields, as_dict=False: dict(
            item_name='Pump ' + name, item_group='Pumps', stock_uom='Nos')
        settings = types.ModuleType('vortexus_discount_matrix.settings')
        columns = ('Dealers', 'Traders', 'Technicians', 'NGOs / Parastatals', 'Corporates', 'End Users / Retail')
        settings.matrix_tables = lambda: ({'Pumps': {c: Decimal(50) for c in columns}}, {'Pumps': {'Dealers': Decimal(30)}})
        settings.customer_mappings = lambda: {'Dealers': 'Dealers'}
        settings.control_options = lambda: dict(block_below_cost=True, cost_basis='System cost (FIFO)', cost_tolerance=5.0, approver_role='MD')
        self.settings = patch.dict(sys.modules, {settings.__name__: settings})
        self.settings.start()
        sys.modules.pop('vortexus_discount_matrix.simulation', None)
        self.sim = importlib.import_module('vortexus_discount_matrix.simulation')

    def tearDown(self):
        sys.modules.pop('vortexus_discount_matrix.simulation', None)
        self.settings.stop()
        self.tearDown_base()

    def doc(self, *rows):
        doc = Record(doctype='VDM Price Simulation', name='VDM-SIM-1', company='CO', from_date='2025-10-23',
                     to_date='2026-10-23', projection_basis='Historical discount', warehouse=None,
                     items=[Record(item_code=code, proposed_price=price) for code, price in rows])
        doc.set = lambda key, value: doc.__setitem__(key, value)
        doc.is_new = lambda: False
        doc.has_value_changed = lambda key: False
        doc.append = lambda key, value: doc['items'].append(Record(value))
        return doc

    def patches(self, price=100, cost=(40, 'Item Valuation Rate'), history=()):
        stack = __import__('contextlib').ExitStack()
        price_row = types.SimpleNamespace(price_list_rate=price, name='PRICE')
        def selling(item_code, uom, stock_uom, day, label, fail):
            if price is None:
                fail(f'{label}: no valid general Standard Selling price for {item_code}.')
            return price_row, True, 'KES'
        stack.enter_context(patch.object(self.sim, 'standard_selling_price', side_effect=selling))
        stack.enter_context(patch.object(self.sim, 'stock_cost', return_value=cost))
        stack.enter_context(patch.object(self.sim, 'selling_exchange_rate', return_value=1.0))
        self.frappe.db.sql = Mock(return_value=list(history))
        return stack

    def test_blank_proposed_price_starts_at_current_and_projects_history(self):
        doc = self.doc(('P1', None))
        history = [dict(item_code='P1', customer_group='Dealers', qty=10, revenue=800, list_amount=1000, list_revenue=800)]
        with self.patches(history=history):
            self.sim.validate(doc)
        row = doc['items'][0]
        self.assertEqual(row.proposed_price, 100)
        self.assertEqual(row.price_change, 0)
        self.assertEqual(row.item_group, 'Pumps')
        self.assertEqual(row.cost_source, 'Item Valuation Rate')
        self.assertAlmostEqual(row.projected_revenue, 800)
        self.assertAlmostEqual(row.projected_profit, 400)
        self.assertAlmostEqual(row.projected_margin, 50)
        self.assertAlmostEqual(row.lowest_floor_margin, 20)
        self.assertIn('30% Margin Matrix minimum', row.warnings)
        detail = json.loads(row.column_detail)
        self.assertEqual(detail[0]['customer_group'], 'Dealers')
        self.assertEqual(detail[0]['column'], 'Dealers')
        self.assertAlmostEqual(doc.projected_profit, 400)
        params = self.frappe.db.sql.call_args.args[1]
        self.assertEqual(params['items'], ('P1',))
        self.assertIn('si.is_return = 0', self.frappe.db.sql.call_args.args[0])

    def test_amended_price_is_kept_and_recalculated(self):
        doc = self.doc(('P1', 150))
        history = [dict(item_code='P1', customer_group='Dealers', qty=10, revenue=800, list_amount=1000, list_revenue=800)]
        with self.patches(history=history):
            self.sim.validate(doc)
        row = doc['items'][0]
        self.assertEqual(row.proposed_price, 150)
        self.assertAlmostEqual(row.price_change, 50)
        self.assertAlmostEqual(row.projected_revenue, 1200)
        self.assertAlmostEqual(row.projected_profit, 800)

    def test_missing_price_is_a_row_warning_not_an_error(self):
        doc = self.doc(('P1', None))
        with self.patches(price=None):
            self.sim.validate(doc)
        row = doc['items'][0]
        self.assertEqual(row.current_price, 0)
        self.assertIn('no valid general Standard Selling price', row.warnings)
        self.assertIn('Enter a proposed price', row.warnings)

    def test_missing_cost_leaves_profit_blank(self):
        doc = self.doc(('P1', 100))
        with self.patches(cost=(None, None)):
            self.sim.validate(doc)
        self.assertEqual(doc['items'][0].projected_profit, 0)
        self.assertIn('No valuation rate', doc['items'][0].warnings)

    def test_duplicate_items_and_bad_dates_rejected(self):
        with self.patches(), self.assertRaisesRegex(ValueError, 'more than once'):
            self.sim.validate(self.doc(('P1', 1), ('P1', 2)))
        doc = self.doc()
        doc.from_date = '2026-12-01'
        with self.patches(), self.assertRaisesRegex(ValueError, 'start date'):
            self.sim.validate(doc)

    def test_no_items_skips_history_query(self):
        with self.patches():
            self.assertEqual(self.sim.sales_history('CO', '2026-01-01', '2026-02-01', []), [])
        self.frappe.db.sql.assert_not_called()

    def test_load_items_respects_permission_filters_and_limit(self):
        doc = self.doc(('EXISTING', 10))
        doc.item_group, doc.only_sold_items = None, 1
        doc.check_permission = Mock()
        doc.save = Mock()
        self.frappe.get_doc = Mock(return_value=doc)
        self.frappe.get_all = Mock(return_value=['EXISTING', 'SOLD', 'UNSOLD'])
        with self.patches(history=[dict(item_code='SOLD'), dict(item_code='EXISTING')]):
            result = self.sim.load_items('VDM-SIM-1')
        doc.check_permission.assert_called_once_with('write')
        self.assertEqual(self.frappe.get_all.call_args.kwargs['filters'],
                         {'item_group': ['in', ['Pumps']], 'disabled': 0, 'is_sales_item': 1})
        self.assertEqual([r.item_code for r in doc['items']], ['EXISTING', 'SOLD'])
        self.assertEqual(result, dict(added=1, not_added=0, limit=500, found=2, only_sold=True))
        doc.save.assert_called_once_with()
        with self.patches(history=[dict(item_code='SOLD'), dict(item_code='UNSOLD')]), \
                patch.object(self.sim, 'MAX_ITEMS', 3):
            doc.only_sold_items = 0
            doc['items'] = [Record(item_code='EXISTING')]
            self.frappe.get_all.return_value = ['A', 'B', 'C', 'D']
            self.assertEqual(self.sim.load_items('VDM-SIM-1'), dict(added=2, not_added=2, limit=3, found=4, only_sold=False))

    def test_selecting_item_group_fills_table_on_save(self):
        doc = self.doc(('KEPT', 75))
        doc.item_group, doc.only_sold_items = 'CATRIDGES', 0
        doc.has_value_changed = lambda key: key == 'item_group'
        self.frappe.get_all = Mock(return_value=['KEPT', 'C1', 'C2'])
        self.frappe.msgprint = Mock()
        with self.patches():
            self.sim.validate(doc)
        self.assertEqual(self.frappe.get_all.call_args.kwargs['filters']['item_group'], ['in', ['CATRIDGES']])
        self.assertEqual([r.item_code for r in doc['items']], ['KEPT', 'C1', 'C2'])
        self.assertEqual(doc['items'][0].proposed_price, 75)  # existing amendments kept
        self.assertEqual(doc['items'][1].proposed_price, 100)
        self.frappe.msgprint.assert_not_called()

    def test_unchanged_item_group_does_not_reload(self):
        doc = self.doc(('KEPT', 75))
        doc.item_group = 'CATRIDGES'
        self.frappe.get_all = Mock(return_value=['C1'])
        with self.patches():
            self.sim.validate(doc)
        self.frappe.get_all.assert_not_called()
        self.assertEqual(len(doc['items']), 1)

    def test_empty_item_group_explains_why(self):
        doc = self.doc()
        doc.item_group, doc.only_sold_items = 'CATRIDGES', 1
        doc.is_new = lambda: True
        self.frappe.get_all = Mock(return_value=['C1'])
        self.frappe.msgprint = Mock()
        with self.patches(history=[]):
            self.sim.validate(doc)
        message = self.frappe.msgprint.call_args.args[0]
        self.assertIn('No enabled sales items found in Item Group CATRIDGES', message)
        self.assertIn('Untick Load Only Items Sold in Period', message)

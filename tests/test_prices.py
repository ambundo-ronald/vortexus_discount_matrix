import importlib
import types
import unittest
from unittest.mock import Mock
import test_approval


class PriceTests(unittest.TestCase):
    setUp = test_approval.ApprovalTests.setUp
    tearDown = test_approval.ApprovalTests.tearDown

    def inputs(self):
        self.prices = importlib.import_module('vortexus_discount_matrix.prices')
        doc = Mock(currency='KES')
        doc.get.side_effect = lambda key: {'transaction_date': '2026-09-21'}.get(key)
        row = types.SimpleNamespace(item_code='PUMP', uom='Nos', conversion_factor=1, idx=1)
        self.frappe.get_cached_doc = Mock(return_value=types.SimpleNamespace(enabled=1, selling=1, currency='KES'))
        self.frappe.db.get_value.side_effect = lambda dt, name, field: 'Nos' if field == 'stock_uom' else None
        self.frappe.get_all = Mock(return_value=[self.price()])
        return doc, row

    def price(self, **changes):
        data = dict(name='PRICE-1', uom='Nos', price_list_rate=100000, currency='KES', customer='', supplier='', batch_no='', valid_from='2026-01-01', valid_upto='', packing_unit=0)
        data.update(changes)
        return types.SimpleNamespace(**data)

    def test_general_price_ignores_transaction_price_fields(self):
        doc, row = self.inputs()
        row.price_list_rate = 1
        self.assertEqual(self.prices.reference_rate(doc, row), (100000, 'PRICE-1'))

    def test_customer_specific_price_cannot_replace_baseline(self):
        doc, row = self.inputs()
        self.frappe.get_all.return_value = [self.price(customer='CUSTOMER-A')]
        with self.assertRaisesRegex(ValueError, 'no valid general'):
            self.prices.reference_rate(doc, row)

    def test_expired_and_future_prices_excluded(self):
        doc, row = self.inputs()
        self.frappe.get_all.return_value = [self.price(valid_upto='2026-09-20'), self.price(valid_from='2026-09-22')]
        with self.assertRaisesRegex(ValueError, 'no valid general'):
            self.prices.reference_rate(doc, row)

    def test_ambiguous_prices_fail(self):
        doc, row = self.inputs()
        self.frappe.get_all.return_value = [self.price(), self.price(name='PRICE-2', price_list_rate=100)]
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.prices.reference_rate(doc, row)

    def test_unconfigured_uom_cannot_default_to_one(self):
        doc, row = self.inputs()
        row.uom = 'Box'
        with self.assertRaisesRegex(ValueError, 'UOM conversion'):
            self.prices.reference_rate(doc, row)

    def test_stock_uom_price_converts_to_box(self):
        doc, row = self.inputs()
        row.uom = 'Box'
        row.conversion_factor = 10
        self.frappe.db.get_value.side_effect = lambda dt, name, field: 'Nos' if field == 'stock_uom' else 10
        self.assertEqual(self.prices.reference_rate(doc, row), (1000000, 'PRICE-1'))

    def test_cross_currency_fails_explicitly(self):
        doc, row = self.inputs()
        doc.currency = 'USD'
        with self.assertRaisesRegex(ValueError, 'currency'):
            self.prices.reference_rate(doc, row)

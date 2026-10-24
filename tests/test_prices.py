import importlib
import types
import unittest
from unittest.mock import Mock, patch
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


    def exchange_module(self, rate):
        module = types.ModuleType('erpnext.setup.utils')
        module.get_exchange_rate = Mock(return_value=rate)
        return module

    def test_cross_currency_uses_server_selling_rate_and_reference_currency(self):
        import sys
        doc, row = self.inputs()
        doc.currency = 'USD'
        doc.conversion_rate = 999
        doc.plc_conversion_rate = 999
        module = self.exchange_module(0.008)
        with patch.dict(sys.modules, {module.__name__: module}):
            self.assertEqual(self.prices.reference_rate(doc, row), (800, 'PRICE-1'))
        module.get_exchange_rate.assert_called_once_with('KES', 'USD', '2026-09-21', args='for_selling')

    def test_cross_currency_and_uom_conversion(self):
        import sys
        doc, row = self.inputs()
        doc.currency = 'EUR'
        row.uom = 'Box'
        row.conversion_factor = 10
        self.frappe.db.get_value.side_effect = lambda dt, name, field: 'Nos' if field == 'stock_uom' else 10
        module = self.exchange_module(0.007)
        with patch.dict(sys.modules, {module.__name__: module}):
            self.assertEqual(self.prices.reference_rate(doc, row), (7000, 'PRICE-1'))

    def test_missing_or_invalid_exchange_rate_blocks(self):
        import sys
        for rate in [None, 0, -1, float('nan'), float('inf')]:
            doc, row = self.inputs()
            doc.currency = 'USD'
            module = self.exchange_module(rate)
            with patch.dict(sys.modules, {module.__name__: module}):
                with self.assertRaisesRegex(ValueError, 'no valid selling exchange rate'):
                    self.prices.reference_rate(doc, row)

    def test_same_currency_does_not_fetch_exchange_rate(self):
        import sys
        doc, row = self.inputs()
        module = self.exchange_module(999)
        with patch.dict(sys.modules, {module.__name__: module}):
            self.assertEqual(self.prices.reference_rate(doc, row), (100000, 'PRICE-1'))
        module.get_exchange_rate.assert_not_called()

    def test_invoice_uses_posting_date(self):
        import sys
        doc, row = self.inputs()
        doc.currency = 'USD'
        doc.get.side_effect = lambda key: {'posting_date': '2026-09-25'}.get(key)
        module = self.exchange_module(0.008)
        with patch.dict(sys.modules, {module.__name__: module}):
            self.prices.reference_rate(doc, row)
        module.get_exchange_rate.assert_called_once_with('KES', 'USD', '2026-09-25', args='for_selling')

    def cost_inputs(self, bin_qty=0, fifo_rate=0, company=(0, 0), item_rate=70, purchase_rate=0,
                    currency='KES', company_currency='KES', qty=1):
        import sys
        self.prices = importlib.import_module('vortexus_discount_matrix.prices')
        doc = Mock(currency=currency)
        doc.get.side_effect = lambda key: {'transaction_date': '2026-09-21', 'company': 'CO'}.get(key)
        row = types.SimpleNamespace(item_code='PUMP', uom='Nos', conversion_factor=1, idx=1, qty=qty,
                                    get=lambda k: {'warehouse': 'Stores', 'qty': qty}.get(k))
        def get_value(dt, name, field):
            if field == 'stock_uom':
                return 'Nos'
            if dt == 'Bin' and field == 'actual_qty':
                return bin_qty
            if dt == 'Item' and field == 'valuation_rate':
                return item_rate  # stale master value: must never be used
            if dt == 'Item' and field == 'last_purchase_rate':
                return purchase_rate
            return 10
        self.frappe.db.get_value.side_effect = get_value
        self.frappe.db.sql = Mock(return_value=[{'value': company[0], 'qty': company[1]}])
        self.frappe.get_cached_value = Mock(return_value=company_currency)
        self.frappe.utils.nowtime = lambda: '12:00:00'
        self.frappe.log_error = Mock()
        stock = types.ModuleType('erpnext.stock.utils')
        stock.get_incoming_rate = Mock(return_value=fifo_rate)
        self.incoming = stock.get_incoming_rate
        patcher = patch.dict(sys.modules, {stock.__name__: stock})
        patcher.start()
        self.addCleanup(patcher.stop)
        return doc, row

    def test_cost_is_erpnext_fifo_cost_from_the_row_warehouse(self):
        doc, row = self.cost_inputs(bin_qty=10, fifo_rate=80, item_rate=70, purchase_rate=60, qty=3)
        self.assertEqual(self.prices.cost_rate(doc, row), (80, 'System cost (FIFO)'))
        args = self.incoming.call_args.args[0]
        self.assertEqual((args['item_code'], args['warehouse'], args['qty'], args['company']), ('PUMP', 'Stores', -3, 'CO'))
        self.assertEqual(self.incoming.call_args.kwargs, dict(raise_error_if_no_rate=False, fallbacks=False))

    def test_empty_warehouse_uses_company_stock_valuation(self):
        doc, row = self.cost_inputs(bin_qty=0, company=(1000, 10), purchase_rate=60)
        self.assertEqual(self.prices.cost_rate(doc, row), (100, 'Company stock valuation'))
        self.incoming.assert_not_called()  # no stock here: ERPNext's master-rate fallbacks are never reached

    def test_item_master_valuation_rate_is_never_used(self):
        doc, row = self.cost_inputs(item_rate=70, purchase_rate=0)
        self.assertEqual(self.prices.cost_rate(doc, row), (None, None))

    def test_cost_falls_back_to_last_purchase_rate(self):
        doc, row = self.cost_inputs(purchase_rate=60)
        self.assertEqual(self.prices.cost_rate(doc, row), (60, 'Last Purchase Rate'))
        row.get = lambda k: None  # no warehouse on the row
        self.assertEqual(self.prices.cost_rate(doc, row), (60, 'Last Purchase Rate'))

    def test_higher_of_basis_uses_last_purchase_when_higher(self):
        from vortexus_discount_matrix.core import HIGHER_COST
        doc, row = self.cost_inputs(bin_qty=5, fifo_rate=80, purchase_rate=95)
        self.assertEqual(self.prices.cost_rate(doc, row, HIGHER_COST), (95, 'Last Purchase Rate (higher than system cost)'))
        self.assertEqual(self.prices.cost_rate(doc, row), (80, 'System cost (FIFO)'))

    def test_older_erpnext_without_fallbacks_argument(self):
        doc, row = self.cost_inputs(bin_qty=5)
        self.incoming.side_effect = lambda args, raise_error_if_no_rate=True, **kw: (_ for _ in ()).throw(TypeError('fallbacks')) if kw else 77
        self.assertEqual(self.prices.cost_rate(doc, row), (77, 'System cost (FIFO)'))

    def test_costing_helper_failure_falls_back_instead_of_blocking(self):
        doc, row = self.cost_inputs(bin_qty=5, purchase_rate=60)
        self.incoming.side_effect = RuntimeError('boom')
        self.assertEqual(self.prices.cost_rate(doc, row), (60, 'Last Purchase Rate'))
        self.frappe.log_error.assert_called_once()

    def test_cost_uses_row_uom_conversion(self):
        doc, row = self.cost_inputs(purchase_rate=80)
        row.uom, row.conversion_factor = 'Box', 10
        self.assertEqual(self.prices.cost_rate(doc, row), (800, 'Last Purchase Rate'))

import unittest
from unittest.mock import Mock
from test_enforcement import Record, SalesDoc
from vortexus_discount_matrix.carry_forward import inherited_rows


class CarryForwardTests(unittest.TestCase):
    def setUp(self):
        self.source_row = Record(name='QI-1', idx=1, item_code='FILTER', qty=10, uom='Nos', conversion_factor=1, net_rate=150)
        self.source = SalesDoc(doctype='Quotation', name='Q-1', docstatus=1, quotation_to='Customer', party_name='C-1', company='Company', currency='KES', items=[self.source_row])
        self.row = Record(name='SOI-1', idx=1, item_code='FILTER', qty=5, uom='Nos', conversion_factor=1, net_rate=150, prevdoc_docname='Q-1', quotation_item='QI-1')
        self.doc = SalesDoc(doctype='Sales Order', name='SO-1', docstatus=0, customer='C-1', company='Company', currency='KES', items=[self.row])
        self.api = Mock()
        self.api.db.exists.return_value = True
        self.api.db.sql.return_value = []
        self.api.get_doc.return_value = self.source
        self.inspect = Mock(return_value={'status': 'Approved Exception', 'fingerprint': 'verified-source'})

    def check(self):
        return inherited_rows(self.doc, [{'row': 1}], self.inspect, self.api)

    def test_partial_quantity_at_approved_price_passes(self):
        self.assertEqual(self.check()[1]['source_name'], 'Q-1')

    def test_better_price_passes(self):
        self.row.net_rate = 200
        self.assertIn(1, self.check())

    def test_lower_final_price_requires_new_approval(self):
        self.row.net_rate = 149
        self.assertEqual(self.check(), {})

    def test_other_customer_or_currency_cannot_reuse(self):
        for field, value in [('customer', 'Other'), ('currency', 'USD'), ('company', 'Other')]:
            old = self.doc[field]
            self.doc[field] = value
            self.assertEqual(self.check(), {})
            self.doc[field] = old

    def test_draft_or_cancelled_source_cannot_reuse(self):
        for status in (0, 2):
            self.source.docstatus = status
            self.assertEqual(self.check(), {})

    def test_wrong_item_or_row_or_uom_cannot_reuse(self):
        for field, value in [('item_code', 'OTHER'), ('quotation_item', 'OTHER'), ('uom', 'Box'), ('conversion_factor', 10)]:
            old = self.row[field]
            self.row[field] = value
            self.assertEqual(self.check(), {})
            self.row[field] = old

    def test_source_without_valid_exception_cannot_reuse(self):
        for status in ('Adjust Price', 'Within Limit', 'Not Applicable'):
            self.inspect.return_value['status'] = status
            self.assertEqual(self.check(), {})

    def test_prior_allocations_limit_partial_documents(self):
        self.api.db.sql.return_value = [{'qty': 6}]
        self.assertEqual(self.check(), {})
        self.api.db.sql.return_value = [{'qty': 5}]
        self.assertIn(1, self.check())

    def test_duplicate_target_rows_cannot_multiply_quantity(self):
        self.doc.items.append(Record(self.row, idx=2, qty=6))
        self.assertEqual(self.check(), {})

    def test_invoice_accepts_order_with_inherited_exception(self):
        self.source.doctype = 'Sales Order'
        self.source.name = 'SO-1'
        self.source.customer = 'C-1'
        self.source_row.name = 'SOI-1'
        self.doc.doctype = 'Sales Invoice'
        self.doc.name = 'SI-1'
        self.row.sales_order = 'SO-1'
        self.row.so_detail = 'SOI-1'
        self.inspect.return_value['status'] = 'Inherited Exception'
        self.assertEqual(self.check()[1]['source_doctype'], 'Sales Order')

    def test_missing_links_require_normal_approval(self):
        self.row.quotation_item = ''
        self.assertEqual(self.check(), {})

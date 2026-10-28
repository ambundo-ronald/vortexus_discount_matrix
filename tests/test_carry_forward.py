import unittest
from unittest.mock import Mock
from test_enforcement import Record, SalesDoc
from vortexus_discount_matrix.carry_forward import inherited_rows, approval_level, same_party


class CarryForwardTests(unittest.TestCase):
    def setUp(self):
        self.source_row = Record(name='QI-1', idx=1, item_code='FILTER', qty=10, uom='Nos', conversion_factor=1, net_rate=150)
        self.source = SalesDoc(doctype='Quotation', name='Q-1', docstatus=1, quotation_to='Customer', party_name='C-1',
                               company='Company', currency='KES', custom_vdm_status='Approved Exception', items=[self.source_row])
        self.row = Record(name='SOI-1', idx=1, item_code='FILTER', qty=5, uom='Nos', conversion_factor=1, net_rate=150, prevdoc_docname='Q-1', quotation_item='QI-1')
        self.doc = SalesDoc(doctype='Sales Order', name='SO-1', docstatus=0, customer='C-1', company='Company', currency='KES', items=[self.row])
        self.docs = {'Q-1': self.source}
        self.api = Mock()
        self.api.db.exists.side_effect = lambda dt, name=None: name in self.docs
        self.api.db.sql.return_value = []
        self.api.get_doc.side_effect = lambda dt, name: self.docs[name]
        self.values = {}
        self.api.db.get_value.side_effect = lambda dt, name, field: self.values.get((dt, str(name), field))
        self.approvals = {'Q-1': [{'approval_level': 'Sales Manager'}]}
        self.api.get_all.side_effect = lambda dt, filters, fields: [
            r for name in filters['reference_name'][1] for r in self.approvals.get(name, [])]

    def check(self, violations=None):
        return inherited_rows(self.doc, violations or [{'row': 1}], self.api)

    def test_partial_quantity_at_approved_price_passes(self):
        result = self.check()[1]
        self.assertEqual(result['source_name'], 'Q-1')
        self.assertEqual(result['source_level'], 'Sales Manager')

    def test_approval_is_judged_by_submission_state_not_todays_prices(self):
        # Nothing re-inspects the source: price-list, cost or matrix changes after approval do not matter.
        self.assertIn(1, self.check())
        self.api.get_doc.assert_called_once_with('Quotation', 'Q-1')

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

    def test_source_without_approved_exception_cannot_reuse(self):
        for status in ('Adjust Price', 'Within Limit', 'Not Applicable', 'Below Cost', None):
            self.source.custom_vdm_status = status
            self.assertEqual(self.check(), {})

    def test_copied_status_without_approval_record_cannot_reuse(self):
        self.approvals = {}
        self.assertEqual(self.check(), {})

    def test_margin_level_approval_is_reported(self):
        self.approvals = {'Q-1': [{'approval_level': None}, {'approval_level': 'Margin Approver'}]}
        self.assertEqual(self.check()[1]['source_level'], 'Margin Approver')

    def test_approval_on_amended_original_counts(self):
        self.source.name = 'Q-1-1'
        self.docs = {'Q-1-1': self.source}
        self.row.prevdoc_docname = 'Q-1-1'
        self.values[('Quotation', 'Q-1-1', 'amended_from')] = 'Q-1'
        self.assertIn(1, self.check())

    def test_prior_allocations_limit_partial_documents(self):
        self.api.db.sql.return_value = [{'qty': 6}]
        self.assertEqual(self.check(), {})
        self.api.db.sql.return_value = [{'qty': 5}]
        self.assertIn(1, self.check())

    def test_duplicate_target_rows_cannot_multiply_quantity(self):
        self.doc.items.append(Record(self.row, idx=2, qty=6))
        self.assertEqual(self.check(), {})

    def test_invoice_inherits_through_order_that_inherited_from_quotation(self):
        order_row = Record(name='SOI-1', idx=1, item_code='FILTER', qty=10, uom='Nos', conversion_factor=1, net_rate=150,
                           prevdoc_docname='Q-1', quotation_item='QI-1')
        order = SalesDoc(doctype='Sales Order', name='SO-1', docstatus=1, customer='C-1', company='Company', currency='KES',
                         custom_vdm_status='Inherited Exception', items=[order_row])
        self.docs['SO-1'] = order
        self.approvals = {'Q-1': [{'approval_level': 'Margin Approver'}]}  # only the quotation was approved
        self.doc.doctype, self.doc.name = 'Sales Invoice', 'SI-1'
        self.row.sales_order, self.row.so_detail = 'SO-1', 'SOI-1'
        result = self.check()[1]
        self.assertEqual(result['source_doctype'], 'Sales Order')
        self.assertEqual(result['source_level'], 'Margin Approver')
        self.source.custom_vdm_status = 'Adjust Price'  # the chain must reach a real approval
        self.assertEqual(self.check(), {})

    def test_missing_links_require_normal_approval(self):
        self.row.quotation_item = ''
        self.assertEqual(self.check(), {})


class PartyMatchTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.values = {}
        self.api.db.get_value.side_effect = lambda dt, name, field: self.values.get((dt, str(name), field))
        self.order = SalesDoc(doctype='Sales Order', customer='CUST-NEW', company='Co', currency='KES', items=[])

    def quote(self, to, party):
        return SalesDoc(doctype='Quotation', quotation_to=to, party_name=party, company='Co', currency='KES', items=[])

    def test_crm_deal_matches_the_customer_it_became_or_any_when_unrecorded(self):
        quote = self.quote('CRM Deal', 'CRM-DEAL-1')
        self.assertTrue(same_party(self.order, quote, self.api))  # deal not yet linked: row link is the proof
        self.values[('CRM Deal', 'CRM-DEAL-1', 'erpnext_customer')] = 'CUST-NEW'
        self.assertTrue(same_party(self.order, quote, self.api))
        self.values[('CRM Deal', 'CRM-DEAL-1', 'erpnext_customer')] = 'SOMEONE-ELSE'
        self.assertFalse(same_party(self.order, quote, self.api))

    def test_lead_matches_customer_created_from_it(self):
        quote = self.quote('Lead', 'LEAD-1')
        self.assertTrue(same_party(self.order, quote, self.api))
        self.values[('Customer', str({'lead_name': 'LEAD-1'}), 'name')] = 'SOMEONE-ELSE'
        self.assertFalse(same_party(self.order, quote, self.api))
        self.values[('Customer', str({'lead_name': 'LEAD-1'}), 'name')] = 'CUST-NEW'
        self.assertTrue(same_party(self.order, quote, self.api))

    def test_company_currency_and_blank_customer_still_required(self):
        quote = self.quote('CRM Deal', 'CRM-DEAL-1')
        for field, value in [('company', 'Other'), ('currency', 'USD'), ('customer', None)]:
            old = self.order[field]
            self.order[field] = value
            self.assertFalse(same_party(self.order, quote, self.api))
            self.order[field] = old

    def test_unknown_party_types_do_not_match(self):
        self.assertFalse(same_party(self.order, self.quote('Prospect', 'P-1'), self.api))


class ApprovalLevelTests(unittest.TestCase):
    def test_returned_or_deep_sources_are_not_authorities(self):
        api = Mock()
        api.get_all.return_value = [{'approval_level': 'Sales Manager'}]
        api.db.get_value.return_value = None
        doc = SalesDoc(doctype='Quotation', name='Q', docstatus=1, custom_vdm_status='Approved Exception', items=[])
        self.assertEqual(approval_level(doc, api), 'Sales Manager')
        doc.is_return = 1
        self.assertIsNone(approval_level(doc, api))
        doc.is_return = 0
        self.assertIsNone(approval_level(doc, api, depth=4))

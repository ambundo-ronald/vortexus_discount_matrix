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
        from vortexus_discount_matrix.core import limits_from_rows, default_limit_rows
        settings.active_limits = lambda: getattr(self, 'active', None) or (
            'Discount Matrix', getattr(self, 'item_limits', None) or limits_from_rows(default_limit_rows()))
        def enforced():
            if getattr(self, 'enforced', None):
                return self.enforced
            mode, limits = settings.active_limits()
            return (mode, limits, None) if mode == 'Discount Matrix' else (mode, None, limits)
        settings.enforced_limits = enforced
        settings.control_options = lambda: dict(dict(block_below_cost=False, cost_basis='System cost (FIFO)',
            cost_tolerance=5.0, approver_role='MD'), **getattr(self, 'controls', {}))
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
        # The quotation was approved and submitted as an approved exception.
        quote.custom_vdm_status = 'Approved Exception'
        def approvals(dt, filters=None, fields=None, order_by=None):
            names = filters['reference_name']
            names = names[1] if isinstance(names, list) else [names]
            return [{'approval_level': 'Sales Manager', 'name': 'APP-1'}] if 'Q-1' in names and 'snapshot' not in fields else []
        self.frappe.get_all.side_effect = approvals
        item_group = self.frappe.db.get_value.side_effect
        self.frappe.db.get_value.side_effect = lambda dt, name, field: None if field == 'amended_from' else item_group(dt, name, field)
        self.frappe.db.exists.side_effect = lambda dt, value=None: False if dt == 'VDM Approval' else value in docs
        with self.inspect_patches():
            self.v.before_submit(order)
            self.assertEqual(order.custom_vdm_status, 'Inherited Exception')
            self.v.before_submit(invoice)
            self.assertEqual(invoice.custom_vdm_status, 'Inherited Exception')
            self.assertIn('carried forward from Sales Order SO-1', invoice.custom_vdm_summary)
        # Standard Selling rose after approval: the order and invoice still inherit, no new approvals.
        with self.inspect_patches(), patch.object(self.v, 'reference_rate', return_value=(900, 'PRICE-2')):
            self.v.before_submit(order)
            self.assertEqual(order.custom_vdm_status, 'Inherited Exception')
            self.v.before_submit(invoice)
            self.assertEqual(invoice.custom_vdm_status, 'Inherited Exception')
        with self.inspect_patches():
            invoice.items[0].rate = 149  # below the approved price: needs its own approval
            with self.assertRaises(ValueError):
                self.v.before_submit(invoice)
        self.frappe.get_all.side_effect = None

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


    def test_foreign_currency_floor_and_approval_recheck_for_all_documents(self):
        import json
        for doctype in self.v.DOCTYPES:
            doc = self.scenario(doctype, rate=3.20)
            doc.currency = 'USD'
            # KES 500 converted at 0.01 USD/KES gives USD 5 reference.
            with self.inspect_patches(), patch.object(self.v, 'reference_rate', return_value=(5, 'PRICE-1')):
                self.v.before_submit(doc)
                self.assertEqual(doc.custom_vdm_status, 'Within Limit')
                doc.items[0].rate = 3.19
                with self.assertRaises(ValueError):
                    self.v.before_submit(doc)
                approved = self.v.inspect(doc)['snapshot']
                self.frappe.get_all.return_value = [{'name': 'FX-APPROVAL', 'snapshot': json.dumps(approved)}]
                self.v.before_submit(doc)
                self.assertEqual(doc.custom_vdm_status, 'Approved Exception')
                with patch.object(self.v, 'reference_rate', return_value=(6, 'PRICE-1')):
                    with self.assertRaises(ValueError):
                        self.v.before_submit(doc)
            self.frappe.get_all.return_value = []


    def test_lead_quotation_uses_lead_group_and_checks_limits(self):
        doc = self.scenario('Quotation', rate=320)
        doc.quotation_to = 'Lead'
        doc.party_name = 'LEAD-1'
        doc.customer = None
        with self.inspect_patches():
            self.v.before_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Within Limit')
            self.assertIn(unittest.mock.call('Lead', 'LEAD-1', 'custom_customer_group'),
                          self.frappe.db.get_value.call_args_list)
            doc.items[0].rate = 150
            with self.assertRaises(ValueError):
                self.v.before_submit(doc)

    def test_lead_requires_group_for_mapped_items(self):
        doc = self.scenario('Quotation')
        doc.quotation_to = 'Lead'
        self.frappe.db.get_value.side_effect = lambda dt, name, field: 'Ro Systems' if dt == 'Item' else None
        with self.inspect_patches(), self.assertRaisesRegex(ValueError, 'Set Customer Group on the Lead'):
            self.v.before_submit(doc)

    def test_lead_approval_stays_bound_to_lead_and_group(self):
        import json
        doc = self.scenario('Quotation')
        doc.quotation_to = 'Lead'
        doc.party_name = 'LEAD-1'
        doc.customer = None
        with self.inspect_patches():
            snapshot = self.v.inspect(doc)['snapshot']
            self.frappe.get_all.return_value = [{'name': 'APPROVAL', 'snapshot': json.dumps(snapshot)}]
            doc.customer = 'transient alias'
            self.v.before_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Approved Exception')
            doc.party_name = 'LEAD-2'
            with self.assertRaises(ValueError):
                self.v.before_submit(doc)
            doc.party_name = 'LEAD-1'
            import vortexus_discount_matrix.settings as settings
            settings.customer_mappings = lambda: {'Dealers': 'Dealers'}
            self.frappe.db.get_value.side_effect = lambda dt, name, field: 'Ro Systems' if dt == 'Item' else 'Dealers'
            with self.assertRaises(ValueError):
                self.v.before_submit(doc)


    def test_credit_notes_skip_price_lookup_on_save_and_submit(self):
        for linked in [None, 'ORIGINAL-INVOICE']:
            doc = self.scenario('Sales Invoice', rate=0)
            doc.is_return = 1
            doc.return_against = linked
            doc.items[0].qty = -1
            doc.custom_vdm_status = 'Adjust Price'
            with patch.object(self.v, 'reference_rate', side_effect=AssertionError('No reference price needed')):
                self.v.validate(doc)
                self.v.before_submit(doc)
                self.v.on_submit(doc)
                result = self.v.inspect(doc)
            self.assertEqual(result['status'], 'Not Applicable')
            self.assertEqual(result['violations'], [])
            self.assertIn('Credit note', result['message'])
            self.assertEqual(doc.custom_vdm_status, 'Not Applicable')
            self.frappe.db.get_value.assert_not_called()

    def test_negative_normal_sale_is_not_exempt(self):
        doc = self.scenario('Sales Invoice')
        doc.items[0].qty = -1
        with self.inspect_patches(), self.assertRaisesRegex(ValueError, 'positive quantities'):
            self.v.before_submit(doc)

    def test_consolidated_sales_remain_unsupported(self):
        doc = self.scenario('Sales Invoice')
        doc.is_consolidated = 1
        with self.inspect_patches(), self.assertRaisesRegex(ValueError, 'consolidated'):
            self.v.before_submit(doc)

    def test_edited_settings_percentage_changes_the_floor(self):
        from decimal import Decimal
        from vortexus_discount_matrix.core import limits_from_rows, default_limit_rows
        rows = default_limit_rows()
        for row in rows:
            if row['item_group'] == 'Ro Systems':
                row['technicians'] = 70
        self.item_limits = limits_from_rows(rows)
        doc = self.scenario(rate=150)
        with self.inspect_patches():
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Within Limit')
        self.assertEqual(result['lines'][0]['max_discount'], 70)
        self.assertEqual(result['lines'][0]['minimum_net_rate'], 150)

    def test_group_removed_from_settings_is_outside_control(self):
        from vortexus_discount_matrix.core import limits_from_rows, default_limit_rows
        self.item_limits = limits_from_rows([r for r in default_limit_rows() if r['item_group'] != 'Ro Systems'])
        doc = self.scenario(rate=1)
        with self.inspect_patches():
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Not Applicable')
        self.assertEqual(result['excluded_rows'][0]['item_group'], 'Ro Systems')

    def margin_patches(self, minimum_margin=55, cost=100):
        from vortexus_discount_matrix.core import LIMIT_FIELDS, limits_from_rows
        row = dict(item_group='Ro Systems', **{f: minimum_margin for f in LIMIT_FIELDS.values()})
        self.active = ('Margin Matrix', limits_from_rows([row], 'Margin Matrix'))
        stack = self.inspect_patches()
        stack.enter_context(patch.object(self.v, 'cost_rate', return_value=(cost, 'Warehouse Valuation Rate')))
        stack.enter_context(patch.object(self.v, 'reference_rate', side_effect=AssertionError('Margin mode needs no selling price')))
        return stack

    def test_margin_mode_blocks_below_minimum_gross_margin(self):
        for doctype in self.v.DOCTYPES:
            doc = self.scenario(doctype, rate=200)
            with self.margin_patches():
                result = self.v.inspect(doc)
                self.assertEqual(result['status'], 'Adjust Price')
                line = result['lines'][0]
                self.assertEqual(line['min_margin'], 55)
                self.assertEqual(line['minimum_net_rate'], 222.23)  # 100 / 0.45 rounded up
                self.assertEqual(line['actual_margin'], 50)
                self.assertEqual(line['cost_source'], 'Warehouse Valuation Rate')
                self.assertIn('Margin is below', result['message'])
                self.assertEqual(result['snapshot']['matrix_mode'], 'Margin Matrix')
                self.v.validate(doc)
                self.assertIn('minimum margin 55%', doc.custom_vdm_summary)
                with self.assertRaisesRegex(ValueError, 'Increase the selling price'):
                    self.v.before_submit(doc)

    def test_margin_mode_allows_price_at_or_above_floor(self):
        for rate in (222.23, 300):
            doc = self.scenario(rate=rate)
            with self.margin_patches():
                self.v.before_submit(doc)
                self.assertEqual(doc.custom_vdm_status, 'Within Limit')

    def test_margin_mode_counts_additional_discount(self):
        doc = self.scenario(rate=250)
        doc.discount_amount = 40  # net 210 < 222.23
        with self.margin_patches():
            self.assertEqual(self.v.inspect(doc)['status'], 'Adjust Price')

    def test_margin_mode_free_row_is_a_violation(self):
        doc = self.scenario(rate=0)
        with self.margin_patches():
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Adjust Price')
        self.assertIsNone(result['lines'][0]['actual_margin'])

    def test_margin_mode_uses_margin_table_scope(self):
        doc = self.scenario(rate=1)
        with self.margin_patches():
            self.active = ('Margin Matrix', {})
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Not Applicable')
        self.assertIn('margin matrix', result['message'])

    def test_discount_snapshot_shape_is_unchanged(self):
        doc = self.scenario()
        with self.inspect_patches():
            self.assertNotIn('matrix_mode', self.v.inspect(doc)['snapshot'])

    def crm_quotation(self, rate=320, group=None, converted=None):
        doc = self.scenario('Quotation', rate=rate)
        doc.quotation_to, doc.party_name, doc.customer = 'CRM Deal', 'CRM-DEAL-1', None
        doc.customer_group = group
        def get_value(dt, name, field):
            if dt == 'Item':
                return 'Ro Systems'
            if dt == 'CRM Deal':
                return converted
            if dt == 'Customer':
                return 'Technician'
            return None
        self.frappe.db.get_value.side_effect = get_value
        self.frappe.db.exists.side_effect = lambda dt, name=None: dt == 'Customer' and name == converted
        return doc

    def test_crm_deal_quotation_uses_quotation_customer_group(self):
        doc = self.crm_quotation(group='Technician')
        with self.inspect_patches():
            result = self.v.inspect(doc)
        self.assertEqual(result['status'], 'Within Limit')
        self.assertEqual(result['snapshot']['customer_group'], 'Technician')
        doc.items[0].rate = 150
        with self.inspect_patches(), self.assertRaisesRegex(ValueError, 'Increase the selling price'):
            self.v.before_submit(doc)

    def test_crm_deal_without_group_explains_what_to_set(self):
        doc = self.crm_quotation(group=None)
        with self.inspect_patches(), self.assertRaisesRegex(ValueError, r'Set Customer Group on this quotation \(quoted to CRM Deal\)'):
            self.v.before_submit(doc)

    def test_converted_crm_deal_uses_erpnext_customer_group(self):
        doc = self.crm_quotation(group='Dealers', converted='CUST-CRM')
        with self.inspect_patches():
            result = self.v.inspect(doc)
        self.assertEqual(result['snapshot']['customer_group'], 'Technician')  # customer's group, not the typed one

    def test_crm_deal_with_only_unmapped_items_needs_no_group(self):
        doc = self.crm_quotation(group=None)
        self.frappe.db.get_value.side_effect = lambda dt, name, field: 'Unmapped Group' if dt == 'Item' else None
        with self.inspect_patches():
            self.v.before_submit(doc)
        self.assertEqual(doc.custom_vdm_status, 'Not Applicable')

    def test_lead_falls_back_to_quotation_customer_group(self):
        doc = self.scenario('Quotation', rate=320)
        doc.quotation_to, doc.party_name, doc.customer, doc.customer_group = 'Lead', 'LEAD-1', None, 'Technician'
        self.frappe.db.get_value.side_effect = lambda dt, name, field: 'Ro Systems' if dt == 'Item' else None
        with self.inspect_patches():
            self.assertEqual(self.v.inspect(doc)['snapshot']['customer_group'], 'Technician')

    def test_crm_deal_approval_ignores_transient_customer_alias(self):
        import json
        doc = self.crm_quotation(rate=150, group='Technician')
        with self.inspect_patches():
            snapshot = self.v.inspect(doc)['snapshot']
            self.frappe.get_all.return_value = [{'name': 'APPROVAL', 'snapshot': json.dumps(snapshot)}]
            doc.customer = 'transient alias'
            self.v.before_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Approved Exception')
            doc.party_name = 'CRM-DEAL-2'
            with self.assertRaises(ValueError):
                self.v.before_submit(doc)
            self.frappe.get_all.return_value = []

    def test_amended_document_keeps_approval_of_original(self):
        import json
        doc = self.scenario()
        with self.inspect_patches():
            snapshot = self.v.inspect(doc)['snapshot']  # approved on TEST-1
            records = [{'name': 'APPROVAL', 'snapshot': json.dumps(snapshot), 'approval_level': 'Sales Manager',
                        'reference_name': 'TEST-1'}]
            def approvals(dt, filters=None, fields=None, order_by=None):
                names = filters['reference_name']
                names = names[1] if isinstance(names, list) else [names]
                return [r for r in records if r['reference_name'] in names]
            self.frappe.get_all.side_effect = approvals
            item_group = self.frappe.db.get_value.side_effect
            self.frappe.db.get_value.side_effect = lambda dt, name, field: None if field == 'amended_from' else item_group(dt, name, field)
            doc.name, doc.amended_from = 'TEST-1-1', 'TEST-1'
            self.v.before_submit(doc)
            self.assertEqual(doc.custom_vdm_status, 'Approved Exception')
            doc.items[0].rate = 140  # different terms from the approval
            with self.assertRaises(ValueError):
                self.v.before_submit(doc)
            doc.items[0].rate, doc.amended_from = 150, None  # not an amendment: no approval
            with self.assertRaises(ValueError):
                self.v.before_submit(doc)
        self.frappe.get_all.side_effect = None

    def test_invoice_price_changed_from_approved_order_needs_reapproval(self):
        order = self.scenario('Sales Order', rate=150)
        order.name, order.docstatus = 'SO-9', 1
        order.items[0].name = 'SOI-9'
        order.custom_vdm_status = 'Approved Exception'  # approved directly on the order
        invoice = copy.deepcopy(order)
        invoice.doctype, invoice.name, invoice.docstatus = 'Sales Invoice', 'SI-9', 0
        invoice.custom_vdm_status = None
        invoice.items[0].sales_order, invoice.items[0].so_detail = 'SO-9', 'SOI-9'
        docs = {'SO-9': order, 'SI-9': invoice}
        self.frappe.get_doc.side_effect = lambda *args: copy.deepcopy(args[0]) if isinstance(args[0], dict) else docs[args[1]]
        self.frappe.db.sql.return_value = []
        def approvals(dt, filters=None, fields=None, order_by=None):
            names = filters['reference_name']
            names = names[1] if isinstance(names, list) else [names]
            return [{'approval_level': 'Sales Manager'}] if 'SO-9' in names and 'snapshot' not in fields else []
        self.frappe.get_all.side_effect = approvals
        item_group = self.frappe.db.get_value.side_effect
        self.frappe.db.get_value.side_effect = lambda dt, name, field: None if field == 'amended_from' else item_group(dt, name, field)
        self.frappe.db.exists.side_effect = lambda dt, value=None: False if dt == 'VDM Approval' else value in docs
        with self.inspect_patches():
            self.v.before_submit(invoice)  # same price as approved: inherits
            self.assertEqual(invoice.custom_vdm_status, 'Inherited Exception')
            invoice.items[0].rate = 140  # changed below what was approved
            with self.assertRaisesRegex(ValueError, 'net price 140 is below the 150 approved on Sales Order SO-9'):
                self.v.before_submit(invoice)
            self.assertEqual(invoice.custom_vdm_status, 'Adjust Price')
            invoice.items[0].rate = 160  # above the approved price, still below the matrix floor: covered
            self.v.before_submit(invoice)
            self.assertEqual(invoice.custom_vdm_status, 'Inherited Exception')
            invoice.items[0].rate, invoice.items[0].qty = 150, 2  # more quantity than approved
            with self.assertRaisesRegex(ValueError, 'quantity exceeds the 1 approved on Sales Order SO-9'):
                self.v.before_submit(invoice)
        self.frappe.get_all.side_effect = None

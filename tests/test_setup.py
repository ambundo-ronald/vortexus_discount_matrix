import importlib
import sys
import types
import unittest
from unittest.mock import patch


class InstallerTests(unittest.TestCase):
    def test_own_fields_install_with_unrelated_invalid_site_link(self):
        frappe = types.ModuleType('frappe')
        custom = types.ModuleType('frappe.custom.doctype.custom_field.custom_field')
        existing = {('Sales Invoice', 'custom_delivery_personnel'): {'fieldtype': 'Link', 'options': None}}
        before = dict(existing[('Sales Invoice', 'custom_delivery_personnel')])
        calls = []

        def create(fields, ignore_validate=False, update=True):
            if not ignore_validate:
                raise ValueError('Delivery Personnel has invalid options')
            calls.append(fields)
            for doctype, definitions in fields.items():
                for definition in definitions:
                    key = (doctype, definition['fieldname'])
                    if update or key not in existing:
                        existing[key] = dict(definition)

        custom.create_custom_fields = create
        with patch.dict(sys.modules, {'frappe': frappe, custom.__name__: custom}):
            sys.modules.pop('vortexus_discount_matrix.setup', None)
            setup = importlib.import_module('vortexus_discount_matrix.setup')
            try:
                setup.install_transaction_fields()
                setup.install_transaction_fields()
            finally:
                sys.modules.pop('vortexus_discount_matrix.setup', None)
        self.assertEqual(existing[('Sales Invoice', 'custom_delivery_personnel')], before)
        self.assertEqual(len(existing), 10)  # nine app fields, one untouched site field
        self.assertEqual(set(calls[0]), {'Quotation', 'Sales Order', 'Sales Invoice'})
        for fields in calls[0].values():
            self.assertEqual({f['fieldname'] for f in fields}, {'custom_vdm_section', 'custom_vdm_status', 'custom_vdm_summary'})
            self.assertTrue(all(f['fieldtype'] in ('Section Break', 'Data', 'Small Text') for f in fields))
            self.assertTrue(all('options' not in f for f in fields))

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


class NavigationTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        self.frappe = types.ModuleType('frappe')
        self.frappe.db = Mock()
        self.frappe.get_doc = Mock()
        self.frappe.clear_cache = Mock()
        custom = types.ModuleType('frappe.custom.doctype.custom_field.custom_field')
        custom.create_custom_fields = Mock()
        self.modules = patch.dict(sys.modules, {'frappe': self.frappe, custom.__name__: custom})
        self.modules.start()
        sys.modules.pop('vortexus_discount_matrix.setup', None)
        self.setup = importlib.import_module('vortexus_discount_matrix.setup')

    def tearDown(self):
        sys.modules.pop('vortexus_discount_matrix.setup', None)
        self.modules.stop()

    def test_upgrade_moves_checkbox_before_mapping_table_and_preserves_fields(self):
        from unittest.mock import Mock
        names = ['enabled', 'price_list', 'customer_mappings', 'mappings_initialized',
                 'allow_manager_approvals', 'site_custom_field']
        fields = [types.SimpleNamespace(fieldname=name, hidden=1) for name in names]
        doc = types.SimpleNamespace(fields=fields)
        doc.set = lambda key, value: setattr(doc, key, value)
        self.setup.order_settings_fields(doc)
        self.setup.order_settings_fields(doc)
        self.assertEqual([f.fieldname for f in doc.fields],
                         ['enabled', 'allow_manager_approvals', 'price_list',
                          'customer_mappings', 'mappings_initialized', 'site_custom_field'])
        self.assertEqual(doc.fields[1].hidden, 0)
        self.assertEqual({id(f) for f in doc.fields}, {id(f) for f in fields})
        self.frappe.get_doc.assert_not_called()  # no singleton values rewritten

    def test_sidebar_migration_keeps_existing_links_without_duplicates(self):
        from unittest.mock import Mock
        sidebar = types.SimpleNamespace(items=[types.SimpleNamespace(
            link_type='DocType', link_to='VDM Settings'), types.SimpleNamespace(
            link_type='DocType', link_to='Customer')], save=Mock())
        sidebar.append = lambda key, value: getattr(sidebar, key).append(types.SimpleNamespace(**value))
        self.frappe.db.exists.return_value = True
        self.frappe.get_doc.return_value = sidebar
        self.setup.install_sidebar()
        self.setup.install_sidebar()
        targets = [(r.link_type, r.link_to) for r in sidebar.items]
        self.assertEqual(len(targets), len(set(targets)))
        self.assertEqual(len(targets), 12)
        self.assertIn(('DocType', 'Customer'), targets)
        self.assertIn(('Report', 'Items Outside Discount Matrix'), targets)
        self.assertIn(('DocType', 'VDM Approval'), targets)
        self.assertNotIn(('DocType', 'VDM Customer Mapping'), targets)

    def test_new_sidebar_uses_module_title(self):
        from unittest.mock import Mock
        sidebar = types.SimpleNamespace(items=[], save=Mock())
        sidebar.append = lambda key, value: getattr(sidebar, key).append(types.SimpleNamespace(**value))
        self.frappe.db.exists.return_value = False
        self.frappe.get_doc.return_value = sidebar
        self.setup.install_sidebar()
        definition = self.frappe.get_doc.call_args.args[0]
        self.assertEqual(definition['title'], 'Vortexus Discount Matrix')
        self.assertEqual(definition['module'], 'Vortexus Discount Matrix')
        self.assertEqual(definition['app'], 'vortexus_discount_matrix')
        self.assertEqual(len(sidebar.items), 11)
        sidebar.save.assert_called_once_with(ignore_permissions=True)


    def test_repair_patch_verifies_created_field_and_propagates_failure(self):
        from unittest.mock import Mock
        module_name = 'vortexus_discount_matrix.migrations.repair_approval_settings'
        sys.modules.pop(module_name, None)
        try:
            with patch.object(self.setup, 'install') as install:
                repair = importlib.import_module(module_name)
                self.frappe.db.exists.return_value = True
                repair.execute()
                install.assert_called_once_with()
                self.frappe.db.exists.assert_called_with('DocField', {
                    'parent': 'VDM Settings', 'fieldname': 'allow_manager_approvals'})
                self.frappe.db.exists.return_value = False
                self.frappe.throw = Mock(side_effect=ValueError('upgrade failed'))
                with self.assertRaisesRegex(ValueError, 'upgrade failed'):
                    repair.execute()
                install.side_effect = RuntimeError('installer failed')
                with self.assertRaisesRegex(RuntimeError, 'installer failed'):
                    repair.execute()
        finally:
            sys.modules.pop(module_name, None)

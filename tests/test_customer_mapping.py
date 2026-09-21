import unittest
from vortexus_discount_matrix.core import mapping_from_rows, limit, policy, fingerprint


class CustomerMappingTests(unittest.TestCase):
    def test_new_live_group_can_use_existing_matrix_column(self):
        group = next(iter(policy()[0]))
        configured = mapping_from_rows([{'customer_group': 'New Contractors', 'matrix_column': 'Dealers'}])
        self.assertEqual(limit(group, 'New Contractors', configured), limit(group, 'Dealers'))

    def test_setting_overrides_bundled_mapping(self):
        group = next(iter(policy()[0]))
        self.assertEqual(limit(group, 'Dealers', {'Dealers': 'End Users / Retail'}), limit(group, 'Individual'))

    def test_empty_settings_do_not_fallback_to_csv(self):
        group = next(iter(policy()[0]))
        self.assertIsNone(limit(group, 'Dealers', {}))

    def test_duplicate_groups_rejected(self):
        with self.assertRaisesRegex(ValueError, 'more than once'):
            mapping_from_rows([{'customer_group': 'Dealers', 'matrix_column': c} for c in ('Dealers', 'Traders')])

    def test_blank_and_invalid_columns_rejected(self):
        for row in ({'customer_group': '', 'matrix_column': 'Dealers'}, {'customer_group': 'Dealers', 'matrix_column': 'Wrong'}, {'customer_group': 'Dealers'}):
            with self.assertRaises(ValueError):
                mapping_from_rows([row])

    def test_multiple_customer_groups_may_share_a_column(self):
        mappings = mapping_from_rows([{'customer_group': g, 'matrix_column': 'Corporates'} for g in ('Corporate', 'Commercial')])
        self.assertEqual(len(mappings), 2)

    def test_changed_mapping_invalidates_approval_even_if_rate_is_same(self):
        self.assertNotEqual(fingerprint({'matrix_column': 'Corporates', 'limit': 10}), fingerprint({'matrix_column': 'NGOs / Parastatals', 'limit': 10}))

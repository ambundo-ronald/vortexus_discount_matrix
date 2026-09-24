import unittest
from decimal import Decimal
from vortexus_discount_matrix.core import minimum_price, effective_discount, fingerprint, policy, limit


class MatrixTests(unittest.TestCase):
    def test_accepted_scope(self):
        groups, customers = policy()
        self.assertEqual(len(groups), 94)
        self.assertEqual(len(customers), 11)
        self.assertNotIn('Intercompany', customers)
        self.assertNotIn('All Customer Groups', customers)
        self.assertNotIn('POOL PUMP', groups)

    def test_all_group_columns_obey_workbook_progression(self):
        groups, _ = policy()
        for group, row in groups.items():
            expected = Decimal(row['Dealers Max Discount %'])
            for column, factor in [('Dealers', '1'), ('Traders', '.8'), ('Technicians', '.9'), ('NGOs / Parastatals', '.95'), ('Corporates', '1'), ('End Users / Retail', '.9')]:
                expected *= Decimal(factor)
                self.assertAlmostEqual(Decimal(row[column + ' Max Discount %']), expected, places=6, msg=group)

    def test_price_floor_and_increases(self):
        self.assertEqual(minimum_price(100000, 40), Decimal('60000.00'))
        self.assertEqual(effective_discount(100000, 110000), Decimal('-10.0'))
        self.assertEqual(effective_discount(100000, 59000), Decimal('41.00'))

    def test_round_floor_up_not_below_ceiling(self):
        self.assertEqual(minimum_price('123.45', '24.624'), Decimal('93.06'))

    def test_invalid_reference_and_limits_fail(self):
        for price, discount in [(0, 40), (-1, 40), (100, 101), (100, -1), ('NaN', 10)]:
            with self.assertRaises(ValueError):
                minimum_price(price, discount)

    def test_exact_group_matching_and_customer_aliases(self):
        groups, _ = policy()
        group = next(iter(groups))
        self.assertEqual(limit(group, 'Government'), limit(group, 'Government/Parastatals'))
        self.assertEqual(limit(group, 'Non Profit'), limit(group, "NGO'S /Social Enterprises"))
        self.assertIsNone(limit(group, 'Intercompany'))
        self.assertIsNone(limit('POOL PUMP', 'Dealers'))
        self.assertIsNone(limit(group + ' child', 'Dealers'))

    def test_additional_discount_can_breach_floor(self):
        # 35% item discount followed by 10% invoice discount totals 41.5%.
        actual = Decimal(100000) * Decimal('.65') * Decimal('.9')
        self.assertLess(actual, minimum_price(100000, 40))
        self.assertEqual(effective_discount(100000, actual), Decimal('41.500'))

    def test_approval_bound_to_document_and_terms(self):
        base = {'document': 'SO-001', 'qty': 1, 'rate': 55000, 'customer': 'A', 'cap': 40}
        self.assertEqual(fingerprint(base), fingerprint(dict(reversed(list(base.items())))))
        for field, value in [('document', 'INV-001'), ('qty', 2), ('rate', 50000), ('customer', 'B'), ('cap', 30)]:
            self.assertNotEqual(fingerprint(base), fingerprint({**base, field: value}))


if __name__ == '__main__':
    unittest.main()


class StableApprovalTests(unittest.TestCase):
    def test_equivalent_representations_preserve_approval(self):
        from vortexus_discount_matrix.core import terms_fingerprint
        a = {'document': '001', 'items': [{'qty': 1, 'rate': 220.22, 'warehouse': None, 'item_tax_rate': '{"VAT":16.0}'}]}
        b = {'document': '001', 'items': [{'qty': 1.0, 'rate': '220.220', 'warehouse': '', 'item_tax_rate': '{ "VAT": 16 }'}]}
        self.assertEqual(terms_fingerprint(a), terms_fingerprint(b))

    def test_real_changes_are_not_normalized_away(self):
        from vortexus_discount_matrix.core import terms_fingerprint, changed_term_paths
        a = {'items': [{'qty': 1, 'rate': 220.22}], 'document': '001'}
        b = {'items': [{'qty': 1, 'rate': 220.21}], 'document': '001'}
        self.assertNotEqual(terms_fingerprint(a), terms_fingerprint(b))
        self.assertEqual(changed_term_paths(a, b), ['items[1].rate'])
        self.assertNotEqual(terms_fingerprint(a), terms_fingerprint({**a, 'document': '1'}))

import unittest
from decimal import Decimal
from vortexus_discount_matrix.core import (LIMIT_FIELDS, MATRIX_COLUMNS, MARGIN_MODE, default_limit_rows,
    limits_from_rows, limit, policy, margin_minimum_price, gross_margin)


def row(group='Ro Systems', **values):
    return dict(item_group=group, **{f: values.get(f, 10) for f in LIMIT_FIELDS.values()})


class DiscountLimitTests(unittest.TestCase):
    def test_seed_rows_reproduce_accepted_policy(self):
        rows = default_limit_rows()
        self.assertEqual(len(rows), 94)
        limits = limits_from_rows(rows)
        groups, customers = policy()
        for group in groups:
            for customer in customers:
                self.assertEqual(limit(group, customer, None, limits), limit(group, customer), (group, customer))
        self.assertEqual(rows[0]['solution_line'], groups[rows[0]['item_group']]['Solution Line'])

    def test_edited_percentage_is_used(self):
        limits = limits_from_rows([row(dealers=55.5)])
        self.assertEqual(limit('Ro Systems', 'Dealers', None, limits), Decimal('55.5'))
        self.assertEqual(limit('Ro Systems', 'Technician', None, limits), Decimal('10'))

    def test_new_group_and_zero_discount(self):
        limits = limits_from_rows([row('Brand New Group', dealers=0)])
        self.assertEqual(limit('Brand New Group', 'Dealers', None, limits), Decimal('0'))

    def test_missing_group_is_outside_control(self):
        self.assertIsNone(limit('Ro Systems', 'Dealers', None, {}))

    def test_invalid_rows_rejected(self):
        for bad, message in [(row(''), 'requires an Item Group'), (row(dealers=101), 'between 0 and 100'),
                             (row(traders=-1), 'between 0 and 100'), (row(corporates=None), 'Corporates'),
                             (row(technicians='NaN'), 'Technicians')]:
            with self.assertRaisesRegex(ValueError, message):
                limits_from_rows([bad])
        with self.assertRaisesRegex(ValueError, 'more than once'):
            limits_from_rows([row(), row(' Ro Systems ')])

    def test_every_matrix_column_has_a_field(self):
        self.assertEqual(tuple(LIMIT_FIELDS), MATRIX_COLUMNS)


class MarginLimitTests(unittest.TestCase):
    def test_gross_margin_on_price(self):
        self.assertEqual(margin_minimum_price(100, 55), Decimal('222.23'))
        self.assertEqual(margin_minimum_price(100, 0), Decimal('100.00'))
        self.assertEqual(margin_minimum_price(100, 50), Decimal('200.00'))
        self.assertEqual(gross_margin(100, 200), Decimal('50'))
        self.assertEqual(gross_margin(100, 80), Decimal('-25'))
        self.assertIsNone(gross_margin(100, 0))

    def test_floor_reaches_requested_margin(self):
        for cost, margin in [(123.45, 37.5), (1, 99.9), (99999, 12.345)]:
            floor = margin_minimum_price(cost, margin)
            self.assertGreaterEqual(gross_margin(cost, floor), Decimal(str(margin)))
            self.assertLess(gross_margin(cost, floor - Decimal('0.01')), Decimal(str(margin)))

    def test_invalid_margin_inputs(self):
        for cost, margin in [(0, 10), (-5, 10), (100, 100), (100, -1), ('NaN', 10)]:
            with self.assertRaises(ValueError):
                margin_minimum_price(cost, margin)

    def test_margin_rows_reject_100_and_accept_99_9(self):
        with self.assertRaisesRegex(ValueError, 'below 100'):
            limits_from_rows([row(dealers=100)], MARGIN_MODE)
        with self.assertRaisesRegex(ValueError, 'margin matrix'):
            limits_from_rows([row(), row()], MARGIN_MODE)
        limits = limits_from_rows([row(dealers=99.9)], MARGIN_MODE)
        self.assertEqual(limit('Ro Systems', 'Dealers', None, limits), Decimal('99.9'))
        self.assertEqual(limits_from_rows([row(dealers=100)])['Ro Systems']['Dealers'], 100)

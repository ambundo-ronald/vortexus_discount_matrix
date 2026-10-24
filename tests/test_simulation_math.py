import unittest
from vortexus_discount_matrix.simulation_math import (simulate_item, history_by_group, assumed_discount,
    margin, HISTORICAL, MAXIMUM, KEEP, UNMAPPED, NO_GROUP)

MAX = {'Dealers': 50, 'Traders': 40, 'Technicians': 36, 'NGOs / Parastatals': 34.2, 'Corporates': 34.2, 'End Users / Retail': 30.78}
MAPPINGS = {'Dealers': 'Dealers', 'Distributor': 'Dealers', 'Traders': 'Traders', 'Technician': 'Technicians'}


def sold(qty, revenue, list_amount=None, list_revenue=None):
    return dict(qty=qty, revenue=revenue, list_amount=revenue if list_amount is None else list_amount,
                list_revenue=revenue if list_revenue is None else list_revenue)


class SimulationMathTests(unittest.TestCase):
    def line(self, result, group):
        return next(c for c in result['columns'] if c['customer_group'] == group)

    def test_margin_is_gross_margin_on_price(self):
        self.assertEqual(margin(200, 100), 50)
        self.assertIsNone(margin(0, 100))
        self.assertIsNone(margin(200, None))

    def test_historical_basis_uses_past_discount_capped_at_maximum(self):
        self.assertEqual(assumed_discount(HISTORICAL, 20, 50), 20)
        self.assertEqual(assumed_discount(HISTORICAL, 60, 50), 50)
        self.assertEqual(assumed_discount(HISTORICAL, None, 50), 50)
        self.assertEqual(assumed_discount(HISTORICAL, None, None), 0)
        self.assertEqual(assumed_discount(HISTORICAL, -5, 50), 0)  # sold above list: assume list price, never more
        self.assertEqual(assumed_discount(HISTORICAL, -772, None), 0)
        self.assertEqual(assumed_discount(HISTORICAL, 130, None), 100)
        self.assertEqual(assumed_discount(MAXIMUM, 20, 50), 50)
        self.assertEqual(assumed_discount(MAXIMUM, 20, None), 20)

    def test_every_mapped_customer_group_is_simulated_with_its_column(self):
        result = simulate_item(100, 40, {}, MAPPINGS, MAX, {}, HISTORICAL)
        self.assertEqual([c['customer_group'] for c in result['columns']], list(MAPPINGS))
        distributor = self.line(result, 'Distributor')
        self.assertEqual(distributor['column'], 'Dealers')
        self.assertEqual(distributor['max_discount'], 50)
        self.assertEqual(self.line(result, 'Technician')['max_discount'], 36)

    def test_groups_sharing_a_column_keep_their_own_buying_history(self):
        # Dealers bought 10 at 80 from a 100 list (20% off); Distributors 5 at 95 (5% off).
        history = {'Dealers': sold(10, 800, list_amount=1000), 'Distributor': sold(5, 475, list_amount=500),
                   'Traders': sold(5, 450, list_amount=500)}
        result = simulate_item(120, 60, history, MAPPINGS, MAX, {}, HISTORICAL)
        dealers, distributor = self.line(result, 'Dealers'), self.line(result, 'Distributor')
        self.assertAlmostEqual(dealers['history_discount'], 20)
        self.assertAlmostEqual(dealers['expected_price'], 96)
        self.assertAlmostEqual(dealers['projected_profit'], 360)
        self.assertAlmostEqual(distributor['history_discount'], 5)
        self.assertAlmostEqual(distributor['expected_price'], 114)
        self.assertAlmostEqual(distributor['projected_revenue'], 570)
        self.assertAlmostEqual(self.line(result, 'Traders')['expected_price'], 108)
        self.assertAlmostEqual(result['projected_revenue'], 960 + 570 + 540)
        self.assertAlmostEqual(result['projected_profit'], 360 + 270 + 240)
        self.assertEqual(result['history_qty'], 20)
        self.assertAlmostEqual(result['history_profit'], 1725 - 20 * 60)

    def test_worst_case_basis_and_floor_margins(self):
        result = simulate_item(100, 60, {'Dealers': sold(10, 800, 1000)}, MAPPINGS, MAX, {}, MAXIMUM)
        dealers = self.line(result, 'Dealers')
        self.assertAlmostEqual(dealers['expected_price'], 50)
        self.assertAlmostEqual(dealers['floor_price'], 50)
        self.assertAlmostEqual(dealers['floor_margin'], -20)
        self.assertAlmostEqual(result['lowest_floor_margin'], -20)
        below = [w for w in result['warnings'] if 'below cost' in w]
        # Dealers and Distributor share the Dealers column: one warning. Traders' floor (60) equals cost.
        self.assertEqual(len(below), 1)
        self.assertTrue(below[0].startswith('Dealers'))

    def test_margin_matrix_minimum_flagged(self):
        result = simulate_item(100, 40, {}, MAPPINGS, MAX, {'Dealers': 30}, HISTORICAL)
        self.assertTrue(any(w.startswith('Dealers') and '30% Margin Matrix minimum' in w for w in result['warnings']))
        self.assertFalse(any(w.startswith('Traders') for w in result['warnings']))
        self.assertEqual(result['projected_revenue'], 0)  # no sales history, no projected volume

    def test_unmapped_groups_with_sales_are_projected_without_matrix_limit(self):
        result = simulate_item(100, 50, {'Intercompany': sold(2, 180, 200)}, MAPPINGS, MAX, {}, HISTORICAL)
        unmapped = self.line(result, 'Intercompany')
        self.assertEqual(unmapped['column'], UNMAPPED)
        self.assertIsNone(unmapped['max_discount'])
        self.assertAlmostEqual(unmapped['expected_price'], 90)
        self.assertNotIn('floor_price', unmapped)
        self.assertEqual(result['columns'][-1]['customer_group'], 'Intercompany')

    def test_missing_cost_and_price(self):
        result = simulate_item(100, None, {'Dealers': sold(1, 90, 100)}, MAPPINGS, MAX, {}, HISTORICAL)
        self.assertIsNone(result['projected_profit'])
        self.assertIsNone(result['projected_margin'])
        self.assertAlmostEqual(result['projected_revenue'], 90)
        self.assertTrue(any('No valuation rate' in w for w in result['warnings']))
        result = simulate_item(0, 50, {'Dealers': sold(1, 90, 100)}, MAPPINGS, MAX, {}, HISTORICAL)
        self.assertEqual(result['projected_revenue'], 0)
        self.assertTrue(any('proposed price' in w for w in result['warnings']))

    def test_rows_without_list_price_have_no_past_discount(self):
        result = simulate_item(100, 50, {'Dealers': sold(1, 90, 0, 0)}, MAPPINGS, MAX, {}, HISTORICAL)
        self.assertIsNone(self.line(result, 'Dealers')['history_discount'])
        self.assertAlmostEqual(self.line(result, 'Dealers')['expected_price'], 50)  # falls back to maximum

    def test_invalid_basis(self):
        with self.assertRaises(ValueError):
            simulate_item(100, 50, {}, MAPPINGS, MAX, {}, 'Guess')

    def test_history_grouped_by_customer_group(self):
        rows = [dict(item_code='A', customer_group='Dealers', qty=2, revenue=100, list_amount=120, list_revenue=100),
                dict(item_code='A', customer_group='Dealers', qty=1, revenue=60, list_amount=60, list_revenue=60),
                dict(item_code='A', customer_group=None, qty=3, revenue=10, list_amount=0, list_revenue=0)]
        grouped = history_by_group(rows)
        self.assertEqual(grouped['A']['Dealers'], dict(qty=3, revenue=160, list_amount=180, list_revenue=160))
        self.assertEqual(grouped['A'][NO_GROUP]['qty'], 3)


class CurrentPriceDiscountTests(unittest.TestCase):
    """0.10.2: past discount is measured against today's Standard Selling price per stock UOM."""
    def line(self, result, group):
        return next(c for c in result['columns'] if c['customer_group'] == group)

    def test_raised_list_price_does_not_inflate_expected_price(self):
        # Invoices showed a 14,800 list and 12,000 paid (19% off). Today's list is 25,000:
        # past discount against today's list is 52%, capped at the 15% maximum.
        history = {'Dealers': sold(10, 120000, list_amount=148000, list_revenue=120000)}
        result = simulate_item(25000, 10000, history, MAPPINGS, {'Dealers': 15}, {}, HISTORICAL, current=25000)
        dealers = self.line(result, 'Dealers')
        self.assertAlmostEqual(dealers['history_discount'], 52)
        self.assertAlmostEqual(dealers['assumed_discount'], 15)
        self.assertAlmostEqual(dealers['expected_price'], 21250)

    def test_invoice_uom_mismatch_cannot_create_absurd_discounts(self):
        # Invoice list amount recorded in another UOM: the invoice method gives -772%.
        history = {'Commercial': sold(2, 15064, list_amount=1726, list_revenue=15064)}
        old = simulate_item(7350, 6215, history, {}, {}, {}, HISTORICAL)
        self.assertLess(self.line(old, 'Commercial')['history_discount'], -700)
        self.assertAlmostEqual(self.line(old, 'Commercial')['expected_price'], 7350)  # clamped: never above list
        new = simulate_item(7350, 6215, history, {}, {}, {}, HISTORICAL, current=7350)
        self.assertAlmostEqual(self.line(new, 'Commercial')['history_discount'], -2.476, places=2)
        self.assertAlmostEqual(self.line(new, 'Commercial')['expected_price'], 7350)

    def test_keep_price_paid_basis_models_lower_list_same_net_price(self):
        history = {'Dealers': sold(10, 800, 1000), 'Traders': sold(4, 360, 400), 'Technician': sold(2, 100, 200)}
        # List cut from 100 to 90: Dealers keep paying 80, Traders paid 90 and keep 90,
        # Technicians paid 50 but the floor at 36% off 90 is 57.6.
        result = simulate_item(90, 40, history, MAPPINGS, MAX, {}, KEEP, current=100)
        self.assertAlmostEqual(self.line(result, 'Dealers')['expected_price'], 80)
        self.assertAlmostEqual(self.line(result, 'Traders')['expected_price'], 90)
        self.assertAlmostEqual(self.line(result, 'Technician')['expected_price'], 57.6)
        self.assertAlmostEqual(self.line(result, 'Dealers')['assumed_discount'], 100 / 9, places=4)
        self.assertAlmostEqual(result['projected_revenue'], 800 + 360 + 115.2)

    def test_keep_price_paid_never_above_proposed_and_falls_back_without_history(self):
        result = simulate_item(70, 40, {'Dealers': sold(10, 800, 1000)}, MAPPINGS, MAX, {}, KEEP, current=100)
        self.assertAlmostEqual(self.line(result, 'Dealers')['expected_price'], 70)
        self.assertAlmostEqual(self.line(result, 'Traders')['expected_price'], 42)  # no history: maximum discount

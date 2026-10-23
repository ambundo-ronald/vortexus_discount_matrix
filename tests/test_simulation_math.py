import unittest
from vortexus_discount_matrix.simulation_math import (simulate_item, history_by_column, assumed_discount,
    margin, HISTORICAL, MAXIMUM, UNMAPPED)

MAX = {'Dealers': 50, 'Traders': 40, 'Technicians': 36, 'NGOs / Parastatals': 34.2, 'Corporates': 34.2, 'End Users / Retail': 30.78}


def sold(qty, revenue, list_amount=None, list_revenue=None):
    return dict(qty=qty, revenue=revenue, list_amount=revenue if list_amount is None else list_amount,
                list_revenue=revenue if list_revenue is None else list_revenue)


class SimulationMathTests(unittest.TestCase):
    def column(self, result, name):
        return next(c for c in result['columns'] if c['column'] == name)

    def test_margin_is_gross_margin_on_price(self):
        self.assertEqual(margin(200, 100), 50)
        self.assertIsNone(margin(0, 100))
        self.assertIsNone(margin(200, None))

    def test_historical_basis_uses_past_discount_capped_at_maximum(self):
        self.assertEqual(assumed_discount(HISTORICAL, 20, 50), 20)
        self.assertEqual(assumed_discount(HISTORICAL, 60, 50), 50)
        self.assertEqual(assumed_discount(HISTORICAL, None, 50), 50)
        self.assertEqual(assumed_discount(HISTORICAL, None, None), 0)
        self.assertEqual(assumed_discount(HISTORICAL, -5, 50), -5)  # sold above list
        self.assertEqual(assumed_discount(MAXIMUM, 20, 50), 50)
        self.assertEqual(assumed_discount(MAXIMUM, 20, None), 20)

    def test_projection_uses_history_quantities_and_discounts(self):
        # Dealers bought 10 at 80 each from a 100 list price: 20% discount.
        history = {'Dealers': sold(10, 800, list_amount=1000), 'Traders': sold(5, 450, list_amount=500)}
        result = simulate_item(120, 60, history, MAX, {}, HISTORICAL)
        dealers = self.column(result, 'Dealers')
        self.assertAlmostEqual(dealers['history_discount'], 20)
        self.assertAlmostEqual(dealers['expected_price'], 96)
        self.assertAlmostEqual(dealers['projected_revenue'], 960)
        self.assertAlmostEqual(dealers['projected_profit'], 360)
        self.assertAlmostEqual(dealers['history_profit'], 200)
        traders = self.column(result, 'Traders')
        self.assertAlmostEqual(traders['expected_price'], 108)
        self.assertAlmostEqual(result['projected_revenue'], 960 + 540)
        self.assertAlmostEqual(result['projected_profit'], 360 + 240)
        self.assertAlmostEqual(result['projected_margin'], 600 / 1500 * 100)
        self.assertEqual(result['history_qty'], 15)
        self.assertAlmostEqual(result['history_profit'], 1250 - 15 * 60)

    def test_worst_case_basis_and_floor_margins(self):
        result = simulate_item(100, 60, {'Dealers': sold(10, 800, 1000)}, MAX, {}, MAXIMUM)
        dealers = self.column(result, 'Dealers')
        self.assertAlmostEqual(dealers['expected_price'], 50)
        self.assertAlmostEqual(dealers['floor_price'], 50)
        self.assertAlmostEqual(dealers['floor_margin'], -20)
        self.assertAlmostEqual(result['lowest_floor_margin'], -20)
        self.assertTrue(any('below cost' in w for w in result['warnings']))

    def test_margin_matrix_minimum_flagged(self):
        result = simulate_item(100, 40, {}, MAX, {'Dealers': 30}, HISTORICAL)
        # Dealers floor 50, margin 20% < 30% minimum; Traders floor 60 gives 33.3%.
        self.assertTrue(any(w.startswith('Dealers') and '30% Margin Matrix minimum' in w for w in result['warnings']))
        self.assertFalse(any(w.startswith('Traders') for w in result['warnings']))
        self.assertEqual(result['projected_revenue'], 0)  # no sales history, no projected volume

    def test_unmapped_sales_are_projected_without_matrix_limit(self):
        result = simulate_item(100, 50, {UNMAPPED: sold(2, 180, 200)}, MAX, {}, HISTORICAL)
        unmapped = self.column(result, UNMAPPED)
        self.assertIsNone(unmapped['max_discount'])
        self.assertAlmostEqual(unmapped['expected_price'], 90)
        self.assertNotIn('floor_price', unmapped)

    def test_missing_cost_and_price(self):
        result = simulate_item(100, None, {'Dealers': sold(1, 90, 100)}, MAX, {}, HISTORICAL)
        self.assertIsNone(result['projected_profit'])
        self.assertIsNone(result['projected_margin'])
        self.assertAlmostEqual(result['projected_revenue'], 90)
        self.assertTrue(any('No valuation rate' in w for w in result['warnings']))
        result = simulate_item(0, 50, {'Dealers': sold(1, 90, 100)}, MAX, {}, HISTORICAL)
        self.assertEqual(result['projected_revenue'], 0)
        self.assertTrue(any('proposed price' in w for w in result['warnings']))

    def test_rows_without_list_price_have_no_past_discount(self):
        result = simulate_item(100, 50, {'Dealers': sold(1, 90, 0, 0)}, MAX, {}, HISTORICAL)
        self.assertIsNone(self.column(result, 'Dealers')['history_discount'])
        self.assertAlmostEqual(self.column(result, 'Dealers')['expected_price'], 50)  # falls back to maximum

    def test_invalid_basis(self):
        with self.assertRaises(ValueError):
            simulate_item(100, 50, {}, MAX, {}, 'Guess')

    def test_history_grouped_by_matrix_column(self):
        rows = [dict(item_code='A', customer_group='Dealers', qty=2, revenue=100, list_amount=120, list_revenue=100),
                dict(item_code='A', customer_group='Distributor', qty=1, revenue=60, list_amount=60, list_revenue=60),
                dict(item_code='A', customer_group='Intercompany', qty=3, revenue=10, list_amount=0, list_revenue=0)]
        grouped = history_by_column(rows, {'Dealers': 'Dealers', 'Distributor': 'Dealers'})
        self.assertEqual(grouped['A']['Dealers'], dict(qty=3, revenue=160, list_amount=180, list_revenue=160))
        self.assertEqual(grouped['A'][UNMAPPED]['qty'], 3)

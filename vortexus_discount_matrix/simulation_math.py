"""Price simulation calculations; no Frappe dependencies.

All amounts are per stock UOM in company currency. Margins are gross margin on
price, (price - cost) / price, matching the Margin Matrix.
"""
from vortexus_discount_matrix.core import MATRIX_COLUMNS

UNMAPPED = 'Unmapped customer groups'
HISTORICAL, MAXIMUM = 'Historical discount', 'Maximum matrix discount'
BASES = (HISTORICAL, MAXIMUM)


def margin(price, cost):
    if cost is None or not price or price <= 0:
        return None
    return (price - cost) / price * 100


def assumed_discount(basis, historical, maximum):
    """Discount % expected on future sales for one matrix column.

    Historical: the column's realised discount, capped at the matrix maximum
    because larger discounts would be blocked. Maximum: the matrix ceiling,
    the worst case the matrix allows without a manager exception."""
    if basis == MAXIMUM:
        return maximum if maximum is not None else (historical or 0)
    value = historical if historical is not None else (maximum if maximum is not None else 0)
    return min(value, maximum) if maximum is not None else value


def simulate_item(proposed, cost, history, max_discounts, min_margins, basis=HISTORICAL):
    """Project one item at a proposed price.

    history: {column: dict(qty, revenue, list_amount, list_revenue)} where revenue is
    net sales, list_amount is list price x quantity for rows sold from a list price and
    list_revenue is net sales of those rows. max_discounts/min_margins: {column: %}.
    """
    if basis not in BASES:
        raise ValueError(f'Projection basis must be one of: {", ".join(BASES)}.')
    columns, warnings = [], []
    if cost is None:
        warnings.append('No valuation rate or last purchase rate: profit and margins cannot be calculated.')
    if not proposed or proposed <= 0:
        warnings.append('Enter a proposed price above zero.')
    names = list(MATRIX_COLUMNS) + ([UNMAPPED] if UNMAPPED in history else [])
    totals = dict(history_qty=0.0, history_revenue=0.0, history_profit=0.0 if cost is not None else None,
                  projected_revenue=0.0, projected_profit=0.0 if cost is not None else None)
    floor_margins = []
    for name in names:
        sold = history.get(name) or {}
        qty, revenue = float(sold.get('qty') or 0), float(sold.get('revenue') or 0)
        list_amount = float(sold.get('list_amount') or 0)
        historical = (1 - float(sold.get('list_revenue') or 0) / list_amount) * 100 if list_amount > 0 else None
        maximum = max_discounts.get(name)
        maximum = None if maximum is None else float(maximum)
        minimum_margin = min_margins.get(name)
        minimum_margin = None if minimum_margin is None else float(minimum_margin)
        line = dict(column=name, qty=qty, history_revenue=revenue,
                    history_price=revenue / qty if qty else None, history_discount=historical,
                    history_profit=None if cost is None else revenue - qty * cost,
                    max_discount=maximum, min_margin=minimum_margin)
        if proposed and proposed > 0:
            discount = assumed_discount(basis, historical, maximum)
            price = proposed * (1 - discount / 100)
            line.update(assumed_discount=discount, expected_price=price, expected_margin=margin(price, cost),
                        projected_revenue=qty * price,
                        projected_profit=None if cost is None else qty * (price - cost))
            if maximum is not None:
                floor = proposed * (1 - maximum / 100)
                floor_margin = margin(floor, cost)
                line.update(floor_price=floor, floor_margin=floor_margin)
                if floor_margin is not None:
                    floor_margins.append(floor_margin)
                    if floor < cost:
                        warnings.append(f'{name}: the maximum discount allows selling below cost.')
                    elif minimum_margin is not None and floor_margin < minimum_margin:
                        warnings.append(f'{name}: the maximum discount gives {floor_margin:.1f}% margin, '
                                        f'below the {minimum_margin:g}% Margin Matrix minimum.')
            totals['projected_revenue'] += line['projected_revenue']
            if cost is not None:
                totals['projected_profit'] += line['projected_profit']
        totals['history_qty'] += qty
        totals['history_revenue'] += revenue
        if cost is not None:
            totals['history_profit'] += line['history_profit']
        columns.append(line)
    totals['projected_margin'] = (None if totals['projected_profit'] is None or not totals['projected_revenue']
                                  else totals['projected_profit'] / totals['projected_revenue'] * 100)
    totals['lowest_floor_margin'] = min(floor_margins) if floor_margins else None
    return dict(columns=columns, warnings=warnings, **totals)


def history_by_column(rows, mappings):
    """Group sales rows {item_code, customer_group, qty, revenue, list_amount, list_revenue} by item and matrix column."""
    result = {}
    for row in rows:
        column = mappings.get(row.get('customer_group')) or UNMAPPED
        bucket = result.setdefault(row['item_code'], {}).setdefault(
            column, dict(qty=0.0, revenue=0.0, list_amount=0.0, list_revenue=0.0))
        for key in bucket:
            bucket[key] += float(row.get(key) or 0)
    return result

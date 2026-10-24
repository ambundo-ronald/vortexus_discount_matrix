"""Price simulation calculations; no Frappe dependencies.

All amounts are per stock UOM in company currency. Margins are gross margin on
price, (price - cost) / price, matching the Margin Matrix.
"""

UNMAPPED = 'Unmapped'
NO_GROUP = '(No Customer Group)'
HISTORICAL, MAXIMUM, KEEP = 'Historical discount', 'Maximum matrix discount', 'Keep price paid'
BASES = (HISTORICAL, MAXIMUM, KEEP)


def margin(price, cost):
    if cost is None or not price or price <= 0:
        return None
    return (price - cost) / price * 100


def assumed_discount(basis, historical, maximum):
    """Discount % expected on future sales for one customer group.

    Historical: the group's realised discount, capped at the matrix maximum
    because larger discounts would be blocked. A group that bought above the
    list price is assumed to pay the list price (0%), never more.
    Maximum: the matrix ceiling, the worst case the matrix allows without a
    manager exception."""
    if basis == MAXIMUM:
        return maximum if maximum is not None else clamp(historical or 0)
    value = clamp(historical) if historical is not None else (maximum if maximum is not None else 0)
    return min(value, maximum) if maximum is not None else value


def clamp(discount):
    return min(max(discount, 0.0), 100.0)


def keep_price(paid, proposed, maximum):
    """Keep price paid basis: the group keeps paying what it paid, but never above
    the proposed price and never below the deepest discount the matrix allows."""
    floor = proposed * (1 - maximum / 100) if maximum is not None else 0.0
    return min(max(paid, floor), proposed)


def simulate_item(proposed, cost, history, mappings, max_discounts, min_margins, basis=HISTORICAL, current=None):
    """Project one item at a proposed price for every customer group.

    history: {customer group: dict(qty, revenue, list_amount, list_revenue)} where revenue
    is net sales, list_amount is list price x quantity for rows sold from a list price and
    list_revenue is net sales of those rows. mappings: {customer group: matrix column}.
    max_discounts/min_margins: {matrix column: %} for the item's Item Group.
    current: today's Standard Selling price per stock UOM. When given, a group's past
    discount is measured as 1 - average net price paid / current price, so it does not
    depend on the list price printed on old invoices (which may since have changed) or
    on the invoice UOM. Without it, the invoice list prices are used.
    Every mapped customer group is simulated, plus unmapped groups with sales history.
    """
    if basis not in BASES:
        raise ValueError(f'Projection basis must be one of: {", ".join(BASES)}.')
    lines, warnings = [], []
    if cost is None:
        warnings.append('No valuation rate or last purchase rate: profit and margins cannot be calculated.')
    if not proposed or proposed <= 0:
        warnings.append('Enter a proposed price above zero.')
    groups = list(mappings) + sorted(g for g in history if g not in mappings)
    totals = dict(history_qty=0.0, history_revenue=0.0, history_profit=0.0 if cost is not None else None,
                  projected_revenue=0.0, projected_profit=0.0 if cost is not None else None)
    floor_margins, warned = [], set()
    for group in groups:
        column = mappings.get(group)
        sold = history.get(group) or {}
        qty, revenue = float(sold.get('qty') or 0), float(sold.get('revenue') or 0)
        list_amount = float(sold.get('list_amount') or 0)
        if current and current > 0:
            historical = (1 - revenue / qty / current) * 100 if qty > 0 else None
        else:
            historical = (1 - float(sold.get('list_revenue') or 0) / list_amount) * 100 if list_amount > 0 else None
        maximum = max_discounts.get(column) if column else None
        maximum = None if maximum is None else float(maximum)
        minimum_margin = min_margins.get(column) if column else None
        minimum_margin = None if minimum_margin is None else float(minimum_margin)
        line = dict(customer_group=group, column=column or UNMAPPED, qty=qty, history_revenue=revenue,
                    history_price=revenue / qty if qty else None, history_discount=historical,
                    history_profit=None if cost is None else revenue - qty * cost,
                    max_discount=maximum, min_margin=minimum_margin)
        if proposed and proposed > 0:
            if basis == KEEP and qty > 0:
                price = keep_price(revenue / qty, proposed, maximum)
                discount = (1 - price / proposed) * 100
            else:
                discount = assumed_discount(HISTORICAL if basis == KEEP else basis, historical, maximum)
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
                    if column not in warned and floor < cost:
                        warned.add(column)
                        warnings.append(f'{column}: the maximum discount allows selling below cost.')
                    elif column not in warned and minimum_margin is not None and floor_margin < minimum_margin:
                        warned.add(column)
                        warnings.append(f'{column}: the maximum discount gives {floor_margin:.1f}% margin, '
                                        f'below the {minimum_margin:g}% Margin Matrix minimum.')
            totals['projected_revenue'] += line['projected_revenue']
            if cost is not None:
                totals['projected_profit'] += line['projected_profit']
        totals['history_qty'] += qty
        totals['history_revenue'] += revenue
        if cost is not None:
            totals['history_profit'] += line['history_profit']
        lines.append(line)
    totals['projected_margin'] = (None if totals['projected_profit'] is None or not totals['projected_revenue']
                                  else totals['projected_profit'] / totals['projected_revenue'] * 100)
    totals['lowest_floor_margin'] = min(floor_margins) if floor_margins else None
    return dict(columns=lines, warnings=warnings, **totals)


def history_by_group(rows):
    """Group sales rows {item_code, customer_group, qty, revenue, list_amount, list_revenue} by item and customer group."""
    result = {}
    for row in rows:
        bucket = result.setdefault(row['item_code'], {}).setdefault(
            row.get('customer_group') or NO_GROUP, dict(qty=0.0, revenue=0.0, list_amount=0.0, list_revenue=0.0))
        for key in bucket:
            bucket[key] += float(row.get(key) or 0)
    return result

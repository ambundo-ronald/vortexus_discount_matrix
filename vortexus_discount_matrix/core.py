"""Pure calculations and exact-match policy loading; no Frappe dependencies."""
import csv
import hashlib
import json
from decimal import Decimal, ROUND_CEILING
from functools import lru_cache
from pathlib import Path


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("A finite number is required")
    return result


def minimum_price(reference, maximum, precision=2):
    reference, maximum = decimal(reference), decimal(maximum)
    if reference <= 0 or not 0 <= maximum <= 100:
        raise ValueError("Invalid reference price or discount limit")
    return (reference * (1 - maximum / 100)).quantize(
        Decimal(1).scaleb(-precision), rounding=ROUND_CEILING
    )


def effective_discount(reference, actual):
    return (1 - decimal(actual) / decimal(reference)) * 100


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=1)
def policy():
    folder = Path(__file__).parent / "data"
    def read(name):
        with (folder / name).open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    customers = {r['ERPNext Customer Group']: r['Matrix Column'] for r in read('customer_group_mapping_accepted.csv')}
    groups = {r['ERPNext Item Group']: r for r in read('item_group_mapping_accepted.csv')}
    return groups, customers


def limit(item_group, customer_group, customer_mappings=None):
    groups, defaults = policy()
    customers = defaults if customer_mappings is None else customer_mappings
    if item_group not in groups or customer_group not in customers:
        return None
    return decimal(groups[item_group][customers[customer_group] + ' Max Discount %'])


MATRIX_COLUMNS = ('Dealers', 'Traders', 'Technicians', 'NGOs / Parastatals', 'Corporates', 'End Users / Retail')


def mapping_from_rows(rows):
    result = {}
    for row in rows:
        group = (row.get('customer_group') or '').strip()
        column = row.get('matrix_column')
        if not group or column not in MATRIX_COLUMNS:
            raise ValueError('Every mapping requires a Customer Group and a valid matrix column.')
        if group in result:
            raise ValueError(f'Customer Group {group} is mapped more than once.')
        result[group] = column
    return result

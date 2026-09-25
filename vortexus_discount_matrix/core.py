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


NUMERIC_TERMS = set('row qty conversion_factor rate net_rate net_amount discount_percentage discount_amount additional_discount_percentage conversion_rate reference_price reference_net_rate max_discount minimum_net_rate actual_net_rate effective_discount tax_amount included_in_print_rate row_id'.split())


def canonical_terms(value, key=None):
    if isinstance(value, dict):
        # Quotation persists its Customer in party_name. The selling controller
        # may also populate a transient customer alias during validation.
        # Normalize only a blank/matching alias, never a conflicting identity.
        header = value.get('header')
        if value.get('doctype') == 'Quotation' and isinstance(header, dict):
            party = header.get('party_name')
            if (header.get('quotation_to') == 'Customer' and party
                    and header.get('customer') in (None, '', party)):
                value = {**value, 'header': {**header, 'customer': party}}
        return {k: canonical_terms(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical_terms(v) for v in value]
    if key == 'item_tax_rate' and isinstance(value, str) and value.strip():
        try:
            rates = json.loads(value)
            return {k: str(decimal(v).normalize()) for k, v in sorted(rates.items())}
        except (ValueError, TypeError, AttributeError):
            return value
    if value is None or value == '':
        return None
    if key in NUMERIC_TERMS:
        return str(decimal(value).normalize())
    return str(value) if not isinstance(value, str) else value


def terms_fingerprint(snapshot):
    return fingerprint(canonical_terms(snapshot))


def changed_term_paths(previous, current, path=''):
    previous, current = canonical_terms(previous), canonical_terms(current)
    def walk(a, b, p):
        if a == b:
            return []
        if isinstance(a, dict) and isinstance(b, dict):
            return [x for k in sorted(set(a) | set(b)) for x in walk(a.get(k), b.get(k), f'{p}.{k}' if p else k)]
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            return [x for i, (left, right) in enumerate(zip(a, b), 1) for x in walk(left, right, f'{p}[{i}]')]
        return [p]
    return walk(previous, current, path)

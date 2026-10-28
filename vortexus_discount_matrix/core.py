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


def margin_minimum_price(cost, margin, precision=2):
    """Lowest net price whose gross margin on price, (price - cost) / price, reaches margin%."""
    cost, margin = decimal(cost), decimal(margin)
    if cost <= 0 or not 0 <= margin < 100:
        raise ValueError("Invalid cost or margin limit")
    return (cost / (1 - margin / 100)).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_CEILING)


def gross_margin(cost, actual):
    """Gross margin on price as a percentage; None when the price is not positive."""
    actual = decimal(actual)
    if actual <= 0:
        return None
    return (actual - decimal(cost)) / actual * 100


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


MATRIX_COLUMNS = ('Dealers', 'Traders', 'Technicians', 'NGOs / Parastatals', 'Corporates', 'End Users / Retail')
# Matrix column -> fieldname on the editable VDM Discount Limit rows.
LIMIT_FIELDS = dict(zip(MATRIX_COLUMNS, ('dealers', 'traders', 'technicians', 'ngos_parastatals', 'corporates', 'end_users_retail')))
DISCOUNT_MODE, MARGIN_MODE, BOTH_MODE = 'Discount Matrix', 'Margin Matrix', 'Discount and Margin'
MATRIX_MODES = (DISCOUNT_MODE, MARGIN_MODE, BOTH_MODE)

# Who may authorise a line. Below cost cannot be authorised when the block is on.
SALES_MANAGER, MARGIN_APPROVER, BELOW_COST = 'Sales Manager', 'Margin Approver', 'Below Cost'
LEVEL_RANK = {None: 0, SALES_MANAGER: 1, MARGIN_APPROVER: 2, BELOW_COST: 3}
SYSTEM_COST, HIGHER_COST = 'System cost (FIFO)', 'Higher of system cost and last purchase rate'
COST_BASES = (SYSTEM_COST, HIGHER_COST)
DEFAULT_APPROVER_ROLE = 'MD'


def required_level(lines):
    """Highest approval level any line needs (None when every line is within limits)."""
    return max((line.get('level') for line in lines), key=lambda level: LEVEL_RANK.get(level, 0), default=None)


def covers(approved_level, needed_level):
    """An approval covers lines needing the same or a lower level. Old approvals have no level: Sales Manager."""
    if needed_level == BELOW_COST:
        return False
    return LEVEL_RANK.get(approved_level or SALES_MANAGER, 1) >= LEVEL_RANK.get(needed_level, 0)


def cost_within_tolerance(approved_lines, current_lines, tolerance):
    """[] when no line's cost rose by more than tolerance% since approval, else descriptions."""
    approved = {(line.get('row'), line.get('item_code')): line for line in approved_lines or [] if isinstance(line, dict)}
    risen = []
    for line in current_lines:
        old = approved.get((line.get('row'), line.get('item_code')))
        if not old or line.get('cost_rate') is None:
            continue
        before = old.get('cost_rate')
        if before is None:
            if line.get('min_margin') is not None:
                risen.append(f"row {line['row']} has a cost now but had none when approved")
            continue
        if decimal(line['cost_rate']) > decimal(before) * (1 + decimal(tolerance) / 100):
            risen.append(f"row {line['row']} cost rose from {decimal(before):f} to {decimal(line['cost_rate']):f}")
    return risen


def default_limit_rows():
    """Accepted CSV policy as VDM Discount Limit rows; used only to seed settings."""
    return [dict(item_group=group, solution_line=row['Solution Line'], category=row['Category'],
                 **{field: float(row[column + ' Max Discount %']) for column, field in LIMIT_FIELDS.items()})
            for group, row in policy()[0].items()]


def limits_from_rows(rows, mode=DISCOUNT_MODE):
    margin = mode == MARGIN_MODE
    table, label, bounds = (('margin matrix', 'minimum margin', 'at least 0 and below 100') if margin
                            else ('discount matrix', 'maximum discount', 'between 0 and 100'))
    result = {}
    for row in rows:
        group = (row.get('item_group') or '').strip()
        if not group:
            raise ValueError(f'Every {table} row requires an Item Group.')
        if group in result:
            raise ValueError(f'Item Group {group} appears more than once in the {table}.')
        limits = {}
        for column, field in LIMIT_FIELDS.items():
            value = row.get(field)
            try:
                value = decimal(value)
            except (ValueError, TypeError, ArithmeticError):
                raise ValueError(f'Item Group {group}: enter a {column} {label}; it must be {bounds}.') from None
            if value < 0 or value > 100 or (margin and value == 100):
                raise ValueError(f'Item Group {group}: {column} {label} must be {bounds}.')
            limits[column] = value
        result[group] = limits
    return result


@lru_cache(maxsize=1)
def default_limits():
    return limits_from_rows(default_limit_rows())


def limit(item_group, customer_group, customer_mappings=None, item_limits=None):
    customers = policy()[1] if customer_mappings is None else customer_mappings
    groups = default_limits() if item_limits is None else item_limits
    if item_group not in groups or customer_group not in customers:
        return None
    return groups[item_group][customers[customer_group]]


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


NUMERIC_TERMS = set('row qty conversion_factor rate net_rate net_amount discount_percentage discount_amount additional_discount_percentage conversion_rate reference_price reference_net_rate max_discount minimum_net_rate actual_net_rate effective_discount tax_amount included_in_print_rate row_id cost_rate min_margin actual_margin margin_floor'.split())
# Cost moves with every stock receipt. Approved terms are the prices, quantities and
# limits; cost is checked separately against a tolerance (cost_within_tolerance).
COST_TERMS = ('cost_rate', 'cost_source', 'actual_margin', 'margin_floor', 'below_cost', 'level', 'description')


def approval_terms(snapshot):
    """Snapshot without cost-derived values, for fingerprints and mismatch messages."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('lines'), list):
        return snapshot
    lines = []
    for line in snapshot['lines']:
        if isinstance(line, dict):
            line = {k: v for k, v in line.items() if k not in COST_TERMS}
            if line.get('min_margin') is not None and line.get('max_discount') is None:
                line.pop('minimum_net_rate', None)  # margin-only floor = cost / (1 - margin)
        lines.append(line)
    return {**snapshot, 'lines': lines}


def canonical_terms(value, key=None):
    if isinstance(value, dict):
        # Quotation persists its Customer in party_name. The selling controller
        # may also populate a transient customer alias during validation.
        # Normalize only a blank/matching alias, never a conflicting identity.
        header = value.get('header')
        if value.get('doctype') == 'Quotation' and isinstance(header, dict):
            if header.get('quotation_to') not in (None, '', 'Customer') and header.get('party_name'):
                # A Lead or CRM Deal identity is party_name, not a transient customer alias.
                value = {**value, 'header': {**header, 'customer': None}}
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
    return fingerprint(canonical_terms(approval_terms(snapshot)))


def changed_term_paths(previous, current, path=''):
    previous, current = canonical_terms(approval_terms(previous)), canonical_terms(approval_terms(current))
    def walk(a, b, p):
        if a == b:
            return []
        if isinstance(a, dict) and isinstance(b, dict):
            return [x for k in sorted(set(a) | set(b)) for x in walk(a.get(k), b.get(k), f'{p}.{k}' if p else k)]
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            return [x for i, (left, right) in enumerate(zip(a, b), 1) for x in walk(left, right, f'{p}[{i}]')]
        return [p]
    return walk(previous, current, path)

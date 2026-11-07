"""User rules that correct /recurring.

Cadence-only detection (knowledge 003) can get a real bill wrong in ways no
constant fixes: Plaid can categorize a bill as a transfer, and normalization
strips the masked digits of a transfer and the number of a check, so one payee
can sit inside a group shared with many others. A rule names the rows the user
means — raw description substring, direction, optional amount range — and says
whether they recur.

`apply_rules` is pure: it takes the detection groups (plain rows) and the rules
and returns the groups left over plus, per rule, the rows it won. Detection
(app/bills.py) then builds one stream per rule from those rows.
"""

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import os.path

from app.subscriptions import _display_name

DIRECTIONS = ('outflow', 'inflow')
ACTIONS = ('recurring', 'not_recurring')
PATTERN_MIN_LENGTH = 3
TEXT_MAX_LENGTH = 255
AMOUNT_MAX = Decimal('99999999.99')   # Numeric(10, 2)
_CENTS = Decimal('0.01')
_HINT_TRIM = '0123456789#*- '


@dataclass
class Claim:
    """What one rule won: its rows and, per source group, how many it took."""
    rule: object
    rows: list = field(default_factory=list)
    sources: list = field(default_factory=list)


@dataclass
class RulesResult:
    groups: list
    claims: list


def has_range(rule):
    return rule.amount_min is not None or rule.amount_max is not None


def _precedence(rule):
    """Sort key, best first: a ranged rule, then the longest pattern, then the
    lowest id. An unsaved candidate (id None) ranks after every saved rule —
    where it lands once saved."""
    return (
        0 if has_range(rule) else 1,
        -len(rule.pattern),
        float('inf') if rule.id is None else rule.id,
    )


def matches(rule, row):
    """True when `row` is one `rule` could claim."""
    if rule.direction == 'outflow':
        if not row.amount > 0:
            return False
    elif not row.amount < 0:
        return False
    if rule.pattern.lower() not in (row.description or '').lower():
        return False
    magnitude = abs(row.amount)
    if rule.amount_min is not None and magnitude < rule.amount_min:
        return False
    if rule.amount_max is not None and magnitude > rule.amount_max:
        return False
    return True


def _sort_key(row):
    return (row.date, row.description or '', row.amount)


def apply_rules(groups, rules):
    """Partition the rows of `groups` between `rules` and what is left over.

    Each row goes to at most one rule that matches it — the first by
    `_precedence`. Rows are partitioned by position, never by value, so two
    identical same-day rows are both claimed or both kept. Claimed rows leave
    their groups and emptied groups are dropped. Returns a RulesResult whose
    `claims` follow the order of `rules`.

    Pure: the inputs are not mutated, and which rows a rule wins does not depend
    on the order of the groups or of the rules.
    """
    ranked = sorted(range(len(rules)), key=lambda i: _precedence(rules[i]))
    claims = [Claim(rule) for rule in rules]
    leftover = []
    for group in groups:
        kept = []
        taken = {}
        for row in group:
            winner = next((i for i in ranked if matches(rules[i], row)), None)
            if winner is None:
                kept.append(row)
            else:
                claims[winner].rows.append(row)
                taken.setdefault(winner, []).append(row)
        if kept:
            leftover.append(kept)
        if taken:
            name = _display_name(group)
            for i, rows in taken.items():
                claims[i].sources.append({
                    'name': name,
                    'taken': len(rows),
                    'total': len(group),
                    'descriptions': sorted({r.description or '' for r in rows}),
                    'amount_low': min(abs(r.amount) for r in rows),
                    'amount_high': max(abs(r.amount) for r in rows),
                })
    for claim in claims:
        claim.rows.sort(key=_sort_key)
        claim.sources.sort(key=lambda s: (s['name'], -s['total'], s['descriptions']))
    return RulesResult(groups=leftover, claims=claims)


def preview(groups, saved_rules, candidate):
    """What saving `candidate` alongside `saved_rules` would do.

    Returns a dict:
      won      — rows the candidate would claim,
      sources  — per source group, "taken of total" for those rows,
      taken    — per saved rule (label, pattern, rows) it would take rows from,
      lost     — per saved rule that keeps rows the candidate matches.
    """
    before = apply_rules(groups, saved_rules)
    owner_before = {id(r): c.rule for c in before.claims for r in c.rows}
    after = apply_rules(groups, list(saved_rules) + [candidate])
    mine = after.claims[-1]
    owner_after = {id(r): c.rule for c in after.claims[:-1] for r in c.rows}

    def tally(owners):
        # Keyed by rule id: labels need not be unique.
        counts = Counter(rule.id for rule in owners)
        by_id = {rule.id: rule for rule in owners}
        return [
            {'label': by_id[i].label, 'pattern': by_id[i].pattern, 'rows': n}
            for i, n in sorted(counts.items())
        ]

    taken = [owner_before[id(r)] for r in mine.rows if id(r) in owner_before]
    lost = [
        owner_after[id(r)]
        for group in groups for r in group
        if matches(candidate, r) and id(r) in owner_after
    ]
    return {
        'won': len(mine.rows),
        'sources': mine.sources,
        'taken': tally(taken),
        'lost': tally(lost),
    }


def pattern_hint(txns):
    """A starting pattern for a Flag link: the longest common prefix of the
    stream's distinct raw descriptions, without the trailing digits and
    `#*-`/spaces that vary per row (so numbered checks give `Check`). Falls back
    to the most common description when that leaves under 3 characters."""
    descriptions = [t.description or '' for t in txns]
    if not descriptions:
        return ''
    prefix = os.path.commonprefix(sorted(set(descriptions))).rstrip(_HINT_TRIM)
    if len(prefix) >= PATTERN_MIN_LENGTH:
        return prefix
    return Counter(descriptions).most_common(1)[0][0].strip()


def _parse_amount(text, name, errors):
    text = (text or '').strip().replace(',', '').lstrip('$')
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        errors.append(f'{name} must be a number.')
        return None
    if not value.is_finite():
        errors.append(f'{name} must be a number.')
        return None
    if value < 0:
        errors.append(f'{name} cannot be negative; amounts are compared without sign.')
        return None
    if value > AMOUNT_MAX:
        errors.append(f'{name} is too large.')
        return None
    return value.quantize(_CENTS)


def _clean(text):
    """Trimmed text without control characters (Postgres rejects NUL)."""
    return ''.join(ch for ch in (text or '') if ch >= ' ' or ch == '\t').strip()


def parse_rule_form(form, defaults=False):
    """(fields, errors) from a rule form. `fields` always holds what was typed
    (trimmed) so the form can re-render; amounts are parsed Decimals or None.

    `defaults` fills a missing direction (money out) and action (recurring) —
    for opening the form from a link. A submitted rule must state both.
    """
    errors = []
    label = _clean(form.get('label'))
    pattern = _clean(form.get('pattern'))
    direction = form.get('direction') or ('outflow' if defaults else '')
    action = form.get('action') or ('recurring' if defaults else '')
    if not label:
        errors.append('Give the rule a name.')
    elif len(label) > TEXT_MAX_LENGTH:
        errors.append('The name is too long.')
    if len(pattern) < PATTERN_MIN_LENGTH:
        errors.append(f'The description text must be at least {PATTERN_MIN_LENGTH} characters.')
    elif len(pattern) > TEXT_MAX_LENGTH:
        errors.append('The description text is too long.')
    if direction not in DIRECTIONS:
        errors.append('Choose money out or money in.')
    if action not in ACTIONS:
        errors.append('Choose recurring or not recurring.')
    amount_min = _parse_amount(form.get('amount_min'), 'Minimum amount', errors)
    amount_max = _parse_amount(form.get('amount_max'), 'Maximum amount', errors)
    if amount_min is not None and amount_min == 0:
        amount_min = None   # "from 0" filters nothing; it must not rank as a range
    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        errors.append('The minimum amount is larger than the maximum.')
    fields = {
        'label': label,
        'pattern': pattern,
        'direction': direction,
        'action': action,
        'amount_min': amount_min,
        'amount_max': amount_max,
        'amount_min_text': (form.get('amount_min') or '').strip(),
        'amount_max_text': (form.get('amount_max') or '').strip(),
    }
    return fields, errors

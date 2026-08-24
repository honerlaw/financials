# Scratchpad: investment-vested-unvested

## Quick decisions 2026-08-23

- [decided] pre-flight: unit 014 reads in-flight (promote marker absent) but is Shipped and its knowledge is promoted; goal (liability due dates) does not overlap the seed (investment vesting) — no collision
- [decided] open-issue match: `gh issue list --state open` returns `[]` — no match, no ask
- [decided] scope check: single work unit — two nullable columns + one Plaid call + one card row, the same shape as unit 014
- [decided] approach: aggregate vested/unvested onto `Account` from `/investments/holdings/get` in sync (rejected: full Holding/Security tables — new subsystem for two numbers; render-time Plaid call — breaks the piggyback rule of 001; derive unvested from `current_balance` — wrong, that balance includes cash and non-equity positions)
- [decided] proposal soundness: additive nullable columns, non-fatal fetch, no public interface change; the one cross-cutting effect (new consented product needs a re-connect per 015) is documented in Open Questions rather than worked around

## Review triage 2026-08-23

- [FIX] `_vested_value`'s derived `quantity * price` product was unrounded; Postgres rounds a Numeric(12,2) insert and SQLite does not, so the value read back differently per environment. Added `_money` + a fractional-input test.
- [FIX] A holding with a vested figure but no `institution_value` silently contributed 0 unvested; behavior kept (unknown ≠ zero) but the reasoning was undocumented. Comment added.
- [TODO] Neither `_refresh_liabilities` nor `_refresh_investments` clears its columns when an account drops out of the payload. Matched the existing behavior rather than diverging mid-unit; filed as #28.
- [IGNORE] The template's `—` fallbacks for a single null half are unreachable in practice (both columns are always written together). Harmless defensiveness.
- [note] Card shipped as two rows, not the draft's single row — 240px is too narrow for two labels and two amounts. Proposal `## Approach` rewritten to match.

## Completion verification 2026-08-23

1. Nullable columns + migration up/down — YES (`e9c2b7d41a58`, verified on scratch SQLite).
2. Both link-token paths consent to `investments` — YES (asserted in test_plaid_client.py).
3. `get_investment_holdings` calls the endpoint — YES (asserts request access_token).
4. Sync populates both / leaves null with no vested figure — YES (4 sync tests).
5. All four benign codes silent, unexpected recorded non-fatally — YES (parametrized + unexpected-code test).
6. Card renders when present, unchanged when null — YES (3 route tests).
7. `pytest` — YES, 248 passed.

# Scratchpad: investment-vested-unvested

## Quick decisions 2026-08-23

- [decided] pre-flight: unit 014 reads in-flight (promote marker absent) but is Shipped and its knowledge is promoted; goal (liability due dates) does not overlap the seed (investment vesting) — no collision
- [decided] open-issue match: `gh issue list --state open` returns `[]` — no match, no ask
- [decided] scope check: single work unit — two nullable columns + one Plaid call + one card row, the same shape as unit 014
- [decided] approach: aggregate vested/unvested onto `Account` from `/investments/holdings/get` in sync (rejected: full Holding/Security tables — new subsystem for two numbers; render-time Plaid call — breaks the piggyback rule of 001; derive unvested from `current_balance` — wrong, that balance includes cash and non-equity positions)
- [decided] proposal soundness: additive nullable columns, non-fatal fetch, no public interface change; the one cross-cutting effect (new consented product needs a re-connect per 015) is documented in Open Questions rather than worked around

## Scratchpad — 006-bills-view

## Panel decisions 2026-06-13
- [skipped — small] scope check: single additive unit (evidence: new module bills.py, new route /bills, new template bills.html, nav link in base.html, tests/test_bills.py — no schema changes, no shared-contract mutations)
- [skipped — small] approach selection: Approach A (bills.py imports subscriptions.py internals) strictly dominant (rejected: B — loses raw transactions needed for payment-status computation; C — subscriptions.py multi-purpose, harder to test)
- [skipped — small] whole-proposal acceptance: every section trivially sound, single-surface new page with no cross-cutting contract changes
- [1/3 accept → revision → 3/3 accept] completion verification: initial vote failed (Skeptic/Arbiter: revise) on 3 issues — (1) inactive streams showing as 'unpaid' false alarms, (2) missing route integration tests, (3) wrong test count 82→87; revision added inactive status override + opacity-50 dimming, 3 route tests, corrected counts; revision vote 3/3 accept

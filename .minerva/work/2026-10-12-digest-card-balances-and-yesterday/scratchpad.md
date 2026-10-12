# Scratchpad: digest-card-balances-and-yesterday

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-10-12
- [hardcoded check — clear] pre-flight: no collision — units 014/020/022 flagged by in_flight are shipped (PRs #30, #38 merged; 014 shipped), adjacent digest work only; no open PRs; peer discovery skipped (no authorization); open-issue match: none (#37 is adjacent — becomes moot, closed by this unit) (tier: hardcoded check, no trigger)
- [reviewed — clean] scope check: one unit, one PR, no phases (tier: reviewer — not provably small, multi-file surface; parallel wave). Skeptic accepted; noted _week_totals must expose the yesterday aggregate (folded as write-up into Approach 1) and the 024 supersession at promote (Approach 8) — neither load-bearing for scope
- [reviewed — clean] approach: A — pure aggregation over the existing single fetch; rejected B (SQL aggregates: third spend definition, extra queries) and C (keep exclusion list for cards: dead config) (tier: reviewer — interface-clause doubt on removing NET_WORTH_EXCLUDED_ACCOUNTS passed to the Skeptic; it answered no: single in-repo reader, var unset in prod per #37, read via getenv default; parallel wave). Noted-but-dismissed: SMS length — worst case estimated ~1,480 chars < 1600; handled as a length success criterion via the whole-proposal fixes
- [panel — 3/3 accept, 3 with fixes] whole-proposal: accepted (tier: panel — genuine-ambiguity doubt: over-$100/category window yesterday vs week; parallel wave; no restart — scope and approach unchanged)
    - fix (arbiter/skeptic): Open Questions gain "net worth removed outright" and "transactions = purchases (is_spend)"
    - fix (arbiter/skeptic): promote step to write a decision entry superseding 024; #37 verified open
    - fix (arbiter/skeptic): category lines capped at top 5 + Other; worst-case length criterion added; truncation form stated
    - fix (proponent): "a week total printed in the text" (Saturday falls in history week)
    - fix (arbiter/skeptic): opt-in/terms wording drift called out explicitly; A2P samples cover no-purchases and none-over-$100 days
    - fix (arbiter/skeptic): negative per-card balance format specified (`$-X`, unchanged) and tested; pending inclusion stated as deliberate (sync flags the pending row removed — verified app/sync.py:_mark_removed)
    - fix (proponent): deletion targets named; whole-dollar vs cents rounding accepted
- [reviewed — clean] completion verification: Verifier reproduced all 10 criteria (re-ran suite 317 passed, grep, sample generator byte-identical) (tier: reviewer floor — no interface change beyond what the proposal approved; code review dispatched alongside)
- [solo] review triage: 4 FIX / 1 SUGGEST / 3 IGNORE + #2 routed to replan-vs-FIX (tier: default-solo row — #2 had one dominant disposition (FIX: wrong output, writable failure scenario); IGNOREs are dispositions the whole-proposal panel already accepted or the scheduled promote step)
- [panel — 3/3 accept, 3 with fixes] replan-vs-FIX #2: REPLAN — key Yesterday on authorized_date or date (tier: panel floor; quorum 2/3)
    - fix (skeptic/arbiter): fetch-window re-derivation recorded (authorized_date <= date <= today)
    - fix (skeptic/arbiter): orchestrator's Sat/Mon-in-Sunday example was impossible — weakened invariant restated precisely (Sunday digest, Saturday purchase posted Sunday)
    - fix (skeptic/arbiter/proponent): residuals recorded — null authorized_date on posted rows; differing authorized_date between pending and posted; "never counted twice" softened
    - fix (arbiter): criterion 3 reworded + three-case pending→posted test; purchase_date() helper; knowledge note that Yesterday's key differs from the budget key
- [panel — 3/3 accept, 3 with fixes] new-plan acceptance: replan "Key the Yesterday section on the purchase date" (tier: panel floor; quorum 3/3)
    - fix (skeptic/arbiter): invariant restated — every Yesterday row is in some printed week total, possibly a different bucket than its label; vacuous "or current week" dropped
    - fix (proponent/skeptic/arbiter): superseded proposal passages (Approach 1, criterion 3, late-arrival Open Question) edited in the same change; replan.md governs on conflict
    - fix (skeptic/arbiter): residual (c) named — purchase first synced after its day is never shown; omission judged lesser than duplication; reported-state / pending_transaction_id dedupe rejected as out of scope
    - fix (all): authorized_date <= date labelled an assumption; getattr wording clarified; 022 decision 3 explicitly not superseded; residual frequency recorded as a follow-up standing fact
- [solo] review triage (re-run after replan): #2 FIXED via replan; #1 #3 #6 #9 FIXED; #7 SUGGESTED; #4 #5 #8 IGNORED unchanged (tier: default-solo row — no disposition gained a second defensible option)

## Work notes

- A2P sample fixtures (criterion 9). The three samples in `docs/twilio-a2p-campaign-resubmission.md` are the verbatim output of this script, run from the worktree root with `PYTHONPATH=.`; a substring check confirmed the doc contains them byte-for-byte:

```python
import sys
from datetime import date
from decimal import Decimal as D
from app.notifications import digest_body
from app.spending import DaySpend

H = lambda *pairs: [(date(2026, m, d), D(t)) for m, d, t in pairs]
hist1 = H((9, 13, '842'), (9, 20, '1130'), (9, 27, '655'), (10, 4, '918'))
cards = [('Amex', 'Gold Card', '1008', D('1204.33')),
         ('Citi', 'Double Cash', '1234', D('612.40'), True)]
s1 = digest_body(date(2026, 10, 12), D('412'), hist1, cards, D('1816.73'),
                 DaySpend(date(2026, 10, 11), 6, D('287.40'), [('Whole Foods Market', D('142.18'))],
                          [('FOOD_AND_DRINK', D('201.30')), ('GENERAL_MERCHANDISE', D('86.10'))]))
cards2 = [('Amex', 'Gold Card', '1008', D('1247.61')),
          ('Citi', 'Double Cash', '1234', D('612.40'))]
s2 = digest_body(date(2026, 10, 13), D('455'), hist1, cards2, D('1860.01'),
                 DaySpend(date(2026, 10, 12), 2, D('43.28'), [], [('FOOD_AND_DRINK', D('43.28'))]))
hist3 = H((9, 20, '1130'), (9, 27, '655'), (10, 4, '918'), (10, 11, '1043'))
cards3 = [('Citi', 'Double Cash', '1234', D('204.17'))]
s3 = digest_body(date(2026, 10, 19), D('0'), hist3, cards3, D('204.17'),
                 DaySpend(date(2026, 10, 18), 0, D('0'), [], []))
for i, s in enumerate((s1, s2, s3), 1):
    print(f'## Sample message #{i}\n\n```\n{s}\n```\n')
```

- Opt-in script drift (compliance flag for the final report): the consent script quoted at docs/twilio-a2p-campaign-resubmission.md (published at onerlaw.com/terms) still says the text carries "the balances of your linked accounts". It is the published wording, so the repo copy is left matching the live page; if the campaign is filed, re-submit the description + samples and bring the terms page in line.
- `_week_totals` renamed `_spend_totals`; it now returns a third aggregate (`day_spend` for yesterday) from the same row list. `_digest_parts` lost its `config` parameter — nothing in the message reads config any more.

## Review triage 2026-10-12
Minerva audit (inline) + code review (local-diff mode, fresh-context subagent — no PR yet).
- [FIXED]   #2 med  app/spending.py day_spend — Yesterday keyed on Transaction.date (Plaid POSTED date): a purchase shown pending under its purchase day is shown again under its posting day in a later digest, and posted-only rows are labelled with the posting day → FIX by keying on `authorized_date or date`; changes Approach 1's stated definition → replan-vs-FIX panel → replan 2026-10-12 (purchase_date)
- [FIXED]   #1 low  app/spending.py:1 — module docstring omits day_spend (doc for touched behavior)
- [FIXED]   #3 low  .env.example:47 — Twilio comment still says the digest carries every account's balance
- [FIXED]   #6 low  app/notifications.py digest_body/_spend_totals — "yesterday" derived twice; carry `day` in DaySpend so header and numbers cannot disagree
- [FIXED]   #9 low  tests/test_spending.py — day_spend tie-sort promise untested
- [SUGGESTED] #7 low  app/notifications.py — card lines/names uncapped; length test is worst-case only for the Yesterday section (standing fact: ~25+ cards needed to near 1600 chars)
- [IGNORE]  #4 low  whole-dollar rounding of day/category totals — accepted in proposal Approach 2 by the whole-proposal panel
- [IGNORE]  #5 low  `$-12.34` card line vs `-$` total — deliberate (Approach 3; line matches dashboard, 016 decision 5)
- [IGNORE]  #8 low  knowledge 024 not yet superseded — scheduled promote step (Approach 8)

## Review finding 2026-10-12
- #7 Card lines and institution/account names are uncapped; the length test is worst-case only for the Yesterday section. At ~45 characters per card line, roughly 25+ cards would be needed to approach Twilio's 1600-character limit together with a worst-case Yesterday section.

- Review fix: app/spending.py — module docstring names day_spend; DaySpend carries `day` so the Yesterday header and numbers cannot disagree.
- Review fix: .env.example — Twilio comment describes card balances + yesterday's purchases.
- Review fix: tests/test_spending.py — day_spend tie-sort covered.
- Review fix (via replan): Yesterday keyed on spending.purchase_date (authorized_date or date); three-case pending→posted test.


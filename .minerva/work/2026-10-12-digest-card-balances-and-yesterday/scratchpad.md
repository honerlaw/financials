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
                 DaySpend(6, D('287.40'), [('Whole Foods Market', D('142.18'))],
                          [('FOOD_AND_DRINK', D('201.30')), ('GENERAL_MERCHANDISE', D('86.10'))]))
cards2 = [('Amex', 'Gold Card', '1008', D('1247.61')),
          ('Citi', 'Double Cash', '1234', D('612.40'))]
s2 = digest_body(date(2026, 10, 13), D('455'), hist1, cards2, D('1860.01'),
                 DaySpend(2, D('43.28'), [], [('FOOD_AND_DRINK', D('43.28'))]))
hist3 = H((9, 20, '1130'), (9, 27, '655'), (10, 4, '918'), (10, 11, '1043'))
cards3 = [('Citi', 'Double Cash', '1234', D('204.17'))]
s3 = digest_body(date(2026, 10, 19), D('0'), hist3, cards3, D('204.17'),
                 DaySpend(0, D('0'), [], []))
for i, s in enumerate((s1, s2, s3), 1):
    print(f'## Sample message #{i}\n\n```\n{s}\n```\n')
```

- Opt-in script drift (compliance flag for the final report): the consent script quoted at docs/twilio-a2p-campaign-resubmission.md (published at onerlaw.com/terms) still says the text carries "the balances of your linked accounts". It is the published wording, so the repo copy is left matching the live page; if the campaign is filed, re-submit the description + samples and bring the terms page in line.
- `_week_totals` renamed `_spend_totals`; it now returns a third aggregate (`day_spend` for yesterday) from the same row list. `_digest_parts` lost its `config` parameter — nothing in the message reads config any more.

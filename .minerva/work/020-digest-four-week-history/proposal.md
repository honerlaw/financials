# Proposal: digest-four-week-history

**Date**: 2026-08-23
**Status**: Shipped (2026-08-23)

## Goal

Add a four-week spend history to the daily digest SMS: the total spend for each
of the four **completed** Sun–Sat weeks preceding the current one, one line per
week, between the budget block and the balances block.

## Why

The digest today answers "where does this week stand" (budget line) and "what is
in each account" (balances). It has no answer to "is this week normal" — a $750
week reads very differently against four $650 weeks than against four $1,200
weeks. Four completed weeks is the smallest window that shows a trend rather
than a comparison against a single prior week.

The current week is deliberately **not** in the list. It is already the headline
of the message, its total is partial until Saturday, and mixing a partial week
into a column of finished weeks invites reading the trend wrong. (User decision
this run — the alternative, "this week + 3 prior", was offered and declined.)

## Approach (as shipped)

### 1. A pure aggregate in `app/spending.py`

New `recent_week_spend(transactions, today, weeks=4)` → `[(week_start, total)]`,
oldest first, covering the `weeks` complete Sun–Sat weeks **before** the week
containing `today`. Zero-spend weeks are emitted with `Decimal('0')` rather than
skipped, exactly as `daily_spend` emits empty days, so the digest always shows
four rows and a quiet week is visible as a quiet week rather than as a gap.

It reuses `is_spend` and `week_start`, so the history counts spend by the same
definition as the budget line, the dashboard chart and the weekly tracker
([[008-decision-dashboard-spend-and-weekly-budget]]) — including that
definition's known limitation that a null-category outflow counts as spend.

`_week_label` in the same module is promoted to public `week_label` and reused
for the SMS row labels (`Jul 5–11`, `Jul 26 – Aug 1`), so the text and the
dashboard's weekly tracker name a week the same way. `routes._week_label` is a
separate, year-carrying variant for the transactions table and is left alone.

### 2. One query feeds both numbers — `app/notifications.py`

`_week_spent` (current week only) is replaced by `_week_totals(session, today)`,
which fetches transactions across the whole five-week span once and returns
`(current_week_spend, history)`. Both consumers already re-filter defensively,
so the wider fetch cannot inflate either number, and the digest still costs one
transaction query.

### 3. The body carries it — `digest_body`

`history` becomes a **required** positional parameter (`digest_body(today,
spent, accounts, history, budget=...)`), rendered as:

```
Last 4 weeks
Jul 5–11: $842
Jul 12–18: $1,130
Jul 19–25: $655
Jul 26 – Aug 1: $1,204
```

Required, not defaulted to empty: a default would let a caller silently ship a
digest with the section missing. Amounts use the budget line's whole-dollar
format (`$1,130`), not the balances' cents — a weekly total is a magnitude, and
cents on four extra rows is noise.

Both send paths get it for free: `send_digest_now` builds the identical body, so
the "Text me this" button and the 7am text stay byte-identical
([[018-decision-on-demand-digest-trigger]]).

### 4. A2P sample messages are regenerated — `docs/twilio-a2p-campaign-resubmission.md`

Carrier traffic has to match the samples filed with the campaign, and that doc
is the source for a filing that has **not been submitted yet** (brand step
pending as of 2026-08-09). Sample messages #1–#3 are regenerated from the new
`digest_body`, and the campaign description gains a clause for the four-week
history, so what gets filed describes what actually sends.

### Rejected alternatives

- **Aggregate the weeks in SQL** (`GROUP BY` a computed week key). Faster in
  principle, but week bucketing is date arithmetic that differs between SQLite
  and Postgres, and it would have to re-implement `is_spend`'s category
  exclusions in SQL — two ways to compute spend is exactly what
  [[008-decision-dashboard-spend-and-weekly-budget]] warns about. At four weeks
  of one household's transactions, the Python pass is free.
- **Reuse `weekly_budget()`.** It is month-anchored and returns budget dicts
  (pct, remaining, over) the digest does not want; bending it to "last N weeks"
  would complicate the dashboard's helper for a different caller.
- **Default `history=()` in `digest_body`.** Smaller test diff, but it turns a
  forgotten argument into a silently truncated message instead of a `TypeError`.

## Success criteria

1. The daily digest contains a `Last 4 weeks` section listing the four complete
   Sun–Sat weeks before the current week, oldest first, each with its total
   spend.
2. The current (partial) week appears only in the budget line, never in the list.
3. A week with no spend renders as `$0`; the list is always four rows.
4. History totals use the same `is_spend` definition as the budget line, and a
   transaction outside the four-week window never lands in it.
5. The on-demand "Text me this" body is identical to the scheduled one.
6. The digest still issues one transaction query.
7. `docs/twilio-a2p-campaign-resubmission.md`'s three sample messages and its
   campaign description match what `digest_body` now produces.
8. `pytest` passes, with new coverage for the pure aggregate (window edges,
   zero-spend weeks, category exclusions) and for the section appearing in a
   real send.

## Open Questions

None blocking. The body grew by ~110 characters (samples now run 254–287), so a
typical digest bills roughly two more UCS-2 segments — the known billing
footnote from unit 016, still pennies a month at one recipient, and still far
under Twilio's 1600-character ceiling.

## Verification

`pytest`: 246 passed (+14). New coverage: `recent_week_spend` window edges
(the Saturday before the window and the current week both excluded), zero-spend
weeks, the shared `is_spend` exclusions, a configurable window, the public
`week_label`; `history_line` formatting; the block's position between the budget
line and the balances; the current week never appearing in it; the history built
end-to-end from seeded transactions; and a `before_cursor_execute` listener
pinning the digest at exactly one `FROM transactions` query.

The three A2P sample messages in the doc were regenerated by calling
`digest_body` directly, not hand-edited, and are mutually consistent (sample
#3's `Aug 9–15: $1,043` is sample #2's budget line).

Found and fixed in review: `_week_totals`'s summary line had nested double
backticks, which is not valid RST — reworded (F1).

Note for the merge: `docs/twilio-a2p-campaign-resubmission.md` also has
uncommitted edits on `main` (the 2026-08-09 brand-registration status update).
They touch the checklist and step 1–2 prose; this unit touches the sample
messages, the campaign description and the step-5 coupling note, so they should
merge cleanly, but the two want reconciling in one place.

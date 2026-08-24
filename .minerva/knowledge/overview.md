# Knowledge overview

## Plaid data flow: piggyback, then refresh

Account metadata is never fetched on its own round-trip:
[[001-decision-plaid-accounts-piggyback-on-sync]] established that
`transactions/sync` already carries the accounts array, so the sync path
upserts accounts from its last non-empty page instead of calling
`accounts/get`. That decision still stands, but read it with
[[023-bug-transactions-sync-is-not-the-only-account-source]] beside it: the
premise that the piggyback sees *every* account turned out to be false, and the
paragraph below is the correction. The piggybacked balances are treated as
cached snapshots —
[[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] layers a
dedicated `/accounts/balance/get` call after sync to overwrite balance
fields with authoritative values. Together: metadata freshness is bounded by
the sync schedule; balance freshness is not.

[[014-decision-plaid-liabilities-piggyback-on-sync]] extends the same shape a
third time: due dates and statement balances are liability attributes that
exist on no other payload, so a `/liabilities/get` call follows the balance
refresh and writes three nullable `Account` columns.
[[021-decision-plaid-vested-value-piggyback-on-sync]] is the fourth and, by
now, a template rather than a fresh design — `/investments/holdings/get` after
the liability refresh, two more nullable `Account` columns, the same benign
error set. What it adds is that the endpoint's payload is per-*holding* while
the columns are per-*account*, so the refresh aggregates: only holdings the
institution reports a vested figure for participate at all, and unvested is
the clamped remainder of `institution_value` rather than a field Plaid returns.
That aggregation sets a trap for its consumers, and
[[024-decision-digest-net-worth]] is where one was caught before shipping:
because only equity-comp holdings participate, `vested_value` is **not** "this
account's balance, vested-adjusted" — a plain brokerage position in the same
account lands in neither total. Anything that *substitutes* the column for the
balance therefore deletes that position silently. Subtracting `unvested_value`
is the operation that composes; substituting `vested_value` is the one that
looks equivalent and is not.

[[023-bug-transactions-sync-is-not-the-only-account-source]] is where the
layering broke, and it inverts one assumption the three entries above share.
Each of them treats the piggyback as the thing that *creates* accounts and the
dedicated endpoint as the thing that *decorates* them — so all three refreshes
skipped any `account_id` they had no row for. Plaid's transactions product does
not cover brokerage accounts, so an investment-only Item's accounts arrive on no
payload the piggyback can see, and the account was structurally unreachable:
connected, syncing `✓ OK` hourly, and absent from the dashboard for as long as it
had been linked. `/accounts/balance/get` and `/investments/holdings/get` are
therefore account **sources**, not just field refreshers, and both now create the
rows they used to discard. Two details generalise. The creates are deliberately
**create-only** — an existing row still takes the old update path — which is what
keeps 002's metadata/balance ownership split intact instead of silently
reversing it. And **creating rows introduced a write race that updating never
had**: `plaid_account_id` is unique and syncs overlap, so the losing INSERT's
`IntegrityError` — not a `plaid.ApiException` — would have escaped the
never-fatal contract below and taken the whole institution's sync down with it.
The savepoint around the insert, not the `except`, is what makes that safe.

The recurring contract across all four layers is that **a post-sync refresh is
never fatal** — a Plaid `ApiException` annotates `SyncLog.error` and the
transactions still land. The corollary is a noise problem: an error that
recurs on every sync for a structural reason buries the real ones, so "this
Item has no liabilities" responses are classified benign and dropped. A second
corollary, visible once the columns are nullable across three features at
once: **null means "not applicable", never zero**. A $0 vested balance would
read as "nothing has vested"; a null renders no row at all.

## Plaid product consent, and update mode as the tool for both

When Plaid returns `ITEM_LOGIN_REQUIRED`, sync flips the institution to
`status='login_required'` and stops importing. [[007-decision-plaid-reconnect-update-mode]]
records the hard-won rule for getting it back: reconnect must use Plaid
**update mode** (`create_update_link_token`, built with `access_token` and
without `products`/`transactions`), *never* the new-connection flow — the
latter mints a new Item and always trips the slug-uniqueness guard, so it is
structurally incapable of reconnecting. Update mode keeps the access token, so
`onSuccess` performs no token exchange; the reconnect endpoint sets
`status='active'` **before** kicking a sync (sync filters on `active`), and a
still-invalid Item simply re-trips `ITEM_LOGIN_REQUIRED` and flips back —
self-healing. Visibility is a context processor injecting a warning banner on
every authenticated page.

[[015-decision-liability-consent-requires-update-mode]] found update mode's
second job, and with it the general rule for adding a Plaid product to a live
integration. Consent is fixed at link time, so making `liabilities` an
additional consented product only helped Items linked *afterwards*; every
older Item returned `ADDITIONAL_CONSENT_REQUIRED` on every sync. There is no
server-side way to grant it — the user must re-consent through update mode,
which is why `create_update_link_token` now carries
`additional_consented_products` and why "Re-connect" is offered for healthy
institutions rather than only failed ones. Budget for that per-Item migration
whenever a new product is consented. The entry also corrects 014's guess at
which error code the never-consented case returns, and notes the cost of
suppressing it: nothing now signals *which* institutions still lack consent,
only that their liability columns stay null.

[[021-decision-plaid-vested-value-piggyback-on-sync]] is that rule applied
prospectively rather than discovered — consenting to `investments` shipped
with `ADDITIONAL_CONSENT_REQUIRED` already in the benign set and the
per-Item re-connect named in the proposal, so the second product cost no
log-noise incident. That is what 015 was for: the migration step is now
budgeted at design time, not diagnosed from production logs.

## Deriving views from stored transactions

Higher-level views are computed from the transactions table rather than new
Plaid products. [[003-decision-subscriptions-cadence-only-detection]] records
the design stance of the `/subscriptions` recurring-stream detector: cadence
regularity is the only detection gate (amount similarity must never gate, or
card payments and utilities vanish), median-bucket fit alone is insufficient
without a per-gap regularity requirement, and the "varies" badge uses MAD so
single price hikes don't false-flag. Its numeric thresholds are provisional
pending real synced data.

The `/bills` page extends this pattern with a monthly payment-status layer.
[[006-decision-bills-payment-status-algorithm]] records the algorithm: expected
day-of-month is the median of historical transaction `.day` values; a bill is
`paid` if any current-month transaction falls within ±6 days of that expected
date, `upcoming` if the window hasn't opened yet, and `unpaid` otherwise. The
±6-day window matches the monthly cadence tolerance already in `CADENCES`.
[[005-decision-bills-inactive-override]] records the safety rule that prevents
false alarms: a stream past 1.5× its cadence age-out boundary gets
`payment_status='inactive'` (with dimmed rendering) instead of `'unpaid'` — a
lapsed cancelled bill must never surface as an overdue obligation.

The dashboard spend chart and weekly budget tracker are the third derived view.
[[008-decision-dashboard-spend-and-weekly-budget]] records its load-bearing
rules: "spend" is a positive `amount` **excluding** Plaid `TRANSFER*` /
`LOAN_PAYMENTS` categories (so credit-card payments and transfers don't
double-count against the budget), with null-category outflows counted as spend
(and therefore potentially over-counting older, uncategorized data). The
weekly $1000 tracker sums each Sun–Sat week in **full** — padding the query to
whole week boundaries so edge weeks straddling the month aren't undercounted —
and flags the current week only when it overlaps the displayed month. The
spending section defaults to the current month on a self-labeled header rather
than changing the transactions table's all-time default.

Those charts are also interactive. [[009-decision-chart-click-window-filter]]
records that clicking a week card or day bar filters the transactions table to a
`?start`/`?end` date window (a day click = 1 day, a week click = the 7-day
Sun–Sat window), computed with **local** date math so negative-UTC zones don't
roll back a day. The window takes precedence over `?month=` for the table, its
infinite-scroll pages, and the account-totals strip (via
`_table_date_bounds`), while the spending chart itself deliberately stays
month-scoped so it remains a stable picker. A day-bar click filters to *all*
transactions that day, not only spend-classified ones.

All three views were computed live on every request until the grouping behind
`/subscriptions` and `/bills` outgrew that.
[[029-decision-merchant-grouping-precomputed-at-sync]] records the change and
the measurements that forced it, and is picked up under *Derived state and its
invalidation* below.

## Derived state and its invalidation

The first thing in this project to be genuinely precomputed rather than derived
per request is merchant grouping, and most of what was learned doing it is about
invalidation rather than speed.
[[029-decision-merchant-grouping-precomputed-at-sync]] records the decision.
Grouping compared every distinct merchant key against every group found so far —
one `SequenceMatcher` per pair, 99.4% of page compute, and 20s at 2000 distinct
merchants growing to 45s at 3000. The cost tracked *distinct merchants*, not
transaction count, so it degraded permanently as one-off purchases accumulated
and no retention policy would have helped. Grouping now happens once at sync
time into `merchant_groups` / `merchant_group_keys`, and a warm page load
measures 0.06s. Deliberately **not** stored: anything date-dependent — `active`,
`next_date`, bills' `payment_status` — because the refresh trigger is
"transactions changed", which never fires for a subscription that simply stopped
being charged.

Two of the three correctness bugs found in that work are the same mistake at
different layers, and both are worth reading before building another cache.
[[030-bug-derived-index-needs-a-nothing-to-compute-state]]: a lazily-computed
column needs three states, not two — computed, not-computed, and
*not-applicable*. Collapsing the third into the second made an unsatisfiable
precondition, and one transaction with no usable merchant name left the index
permanently unusable, so every page load paid a failed rebuild *plus* the
original quadratic scan. The symptom was silent degradation, never an error.
[[031-pattern-version-stamp-must-invalidate-derived-inputs]]: the version stamp
guarding the index deleted the groups but regrouped the stale per-row keys the
old normalizer had produced, so a rebuild reported success while reproducing
exactly the grouping it existed to replace. When invalidating, enumerate every
artifact downstream of what changed — "delete the output and recompute" is only
correct when the inputs were not themselves derived by the code that changed.

The third is about running one rule twice.
[[032-constraint-plaid-entity-ids-must-never-fuzzy-merge]] records that the
persisted path could merge two distinct `merchant_entity_id`s whose display
names fuzzy-matched, while the in-memory grouper never compares entity groups
against each other — so two sub-threshold streams became one that cleared
`MIN_OCCURRENCES`, and a subscription existed or not depending on cache warmth.
A `merchant_entity_id` is an identity assertion from Plaid, not a display
string. The general lesson: where the same rule is implemented twice, the
divergences are not where the differences were designed, and both found here
came from differential-testing the two paths against identical corpora rather
than from reading them.

## Acting on synced data: the daily digest

Beyond deriving views, the app sends outbound SMS. The shape of that notifier has
changed once already, and the two entries should be read in order.

[[010-decision-budget-alert-notifier]] built it as a *reactive* alert: after
every sync, each recipient was texted once per Sun–Sat week for each
newly-crossed 50/75/100% threshold of the week's household spend.
[[016-decision-daily-digest-notifier]] supersedes that cadence. Threshold
alerting had two properties nobody wanted — a quiet week produced **zero**
texts, so there was no "where do we stand" signal unless spending was already
high; and the send landed on whichever sync first observed the crossing —
the 7am job, a reconnect, or a press of the "Sync now" button — so the arrival
time was unpredictable. It is now one digest per recipient per day —
budget status *and* every account's balance — and `newly_crossed`, `THRESHOLDS`
and the `BudgetAlert` model are gone.

What survived the rewrite is the notifier's *shape*, and that part of 010 is
still live rationale: per-recipient dedup, no-double-send from a module-level
lock **plus** a unique constraint (correct only under the `--workers 1`
invariant the APScheduler already assumes, and still not runtime-enforced),
record-after-send so a failed send retries rather than silently dropping a
milestone (duplicate > miss), soft-disable to a clean no-op unless every Twilio
var is set, and a non-fatal hook that can never abort a sync.

Three things 016 adds are worth carrying forward. **Only the scheduled job
notifies** — `sync_all_institutions()` (what `/api/sync` calls) is now silent
and `run_daily_sync()` is the single notifying path, which is what buys
predictable timing. **A wall-clock schedule needs an explicit timezone**: the container sets
no `TZ`, so the pre-existing `hour=7` cron had been firing at 07:00 UTC — 3am
Eastern — and both the scheduler and the digest's notion of "today" now resolve
through `APP_TIMEZONE`, falling back to the configured default rather than to
UTC when the name is junk. **Stale data must be labelled when it leaves the
app**: sync skips institutions that are not `status='active'`
([[007-decision-plaid-reconnect-update-mode]]), so their balances are frozen at
the last good sync, and the dashboard gets away with showing that number only
because a reconnect banner sits beside it. An SMS has no such context, so those
lines are suffixed `(reconnect needed)`. Balance freshness is bounded by sync
cadence in the first place — see
[[002-decision-plaid-balance-refresh-via-dedicated-endpoint]].

[[018-decision-on-demand-digest-trigger]] adds a second *trigger* for that same
artifact — a dashboard button that texts the digest now — and its load-bearing
choice is that the manual path neither reads nor writes `DailyDigest`. It is
dedup-independent in both directions: a press works after the morning digest
already went out, and never suppresses tomorrow's. Recording a row would have
made the button quietly "claim" the day, giving a control labelled *send now* an
invisible second effect. The scheduled path was left untouched — the two share
only the pure message builders, so both texts are byte-identical for the same
data. `is_configured` is the single soft-disable predicate both the button's
rendered state and the endpoint must consult; re-deriving it is how they drift.

[[022-decision-digest-four-week-spend-history]] is the first change to what the
message *says* rather than when or why it sends, and it adds a rule about
changing message content at all. The body now carries a `Last 4 weeks` block —
the four **complete** Sun–Sat weeks behind the current one — while the running
week stays exclusively in the budget line, because it is partial until Saturday
and a partial week in a column of finished ones reads as a drop that is not
real. The history reuses `is_spend` rather than aggregating in SQL, keeping one
spend definition shared with the dashboard
([[008-decision-dashboard-spend-and-weekly-budget]]), and both aggregates come
out of a single widened query. The new constraint is external: A2P 10DLC
registration files sample messages, and traffic that stops matching them is a
violation, so **anything that changes what the digest says forces those samples
to be re-filed** — a coupling the doc previously pinned to the `BRAND` constant
and that now names `digest_body` itself.

[[024-decision-digest-net-worth]] is the second change to what the message says,
and it closes the Balances block with the number that block was implicitly
asking for. Three of its decisions generalise past the digest. **A total cannot
stay sign-agnostic**: every other surface prints `current_balance` raw and never
flips a sign (016 above), but Plaid reports a card's or a loan's balance as the
amount *owed*, so net worth is the first place in the app to read `Account.type`
for meaning — a deliberate exception to the raw-printing rule rather than a
violation of it, and one pinned by fixture-backed tests precisely because it is
the only one. **A note and the arithmetic it describes must come off the same
predicate**: the display flag marking a discounted balance was first derived
independently of the sign check, so a liability carrying an unvested value would
have advertised a discount the total never applied; one shared `_is_liability`
is the fix, and the shape recurs anywhere a message annotates a number it also
computes. **Two failure modes, two different mitigations**: an exclusion pattern
matching *nothing* is logged, because a silently-counted account is the failure
this feature exists to prevent, while a pattern matching *too much* is caught by
the excluded account staying in the message marked `(not counted)` — which is
why excluded accounts are not hidden. Configuration follows
[[011-decision-doppler-hybrid-config]], with the operational consequence that
the list must be set in Doppler and not merely documented; until it is, the
feature fails *open* and counts everything.

It also widens 022's external constraint. Re-filing A2P samples is not only
about adding or removing a section: a new parenthetical on one balance line is a
body-shape change too, and the campaign **description** moves with the samples,
since both are filed claims about what the traffic contains.

## Configuration and secrets

All config is read through `os.getenv` in `app/__init__.py`, which made moving to
a secrets manager a pure deployment change. [[011-decision-doppler-hybrid-config]]
records the Doppler migration: the CLI is baked into the image (pinned, signed apt
repo) and the app runs via `doppler run` **only when `DOPPLER_TOKEN` is set** —
otherwise it falls back to plain environment variables, so the same image boots
either way and the production cutover is staged and reversible (and fail-closed:
a bad token aborts boot). It is a **hybrid**: `DATABASE_URL`/`DATABASE_ADMIN_URL`
stay injected by DigitalOcean's managed-database binding rather than Doppler, and
the entrypoint passes `--preserve-env` for exactly those so the DO values always
win. Application code did not change — Doppler only populates the environment.

## Client-side gotchas

[[012-pattern-fetch-content-type-session-detection]] records why `fetch()`
against a `@login_required` route cannot detect session expiry with `!r.ok`:
the browser follows the 302 to `/login` transparently, so the JS sees a 200
with an HTML body, `r.json()` throws, and an infinite-scroll observer retries
the same broken request forever. Check the response `Content-Type` for
`application/json` *before* parsing, and redirect to `/login` when it isn't.

[[019-bug-non-json-response-conflated-with-session-expiry]] is the correction to
the *other half* of that rule, learned the hard way when the digest button
redirected to `/login` on every press with the session perfectly valid. The
Content-Type check is a **parsing-safety** rule, not an **identification** rule:
it tells you not to hand HTML to `r.json()`, but it cannot tell you *why* the
body is HTML — and a crashed endpoint is non-JSON exactly like a login redirect.
Treating every non-JSON response as expiry turns each server error into a
phantom logout, the worst possible disguise: it blames the user's session and
destroys the message that would have explained the failure. The precise signal
is `res.redirected` plus a final URL of `/login`; everything else non-JSON is an
error to display. The server side of the same rule: an API endpoint must fail as
JSON, naming the exception, rather than letting Flask's HTML 500 page escape.

## The presentation layer

For most of the app's life the UI was stock Bootstrap 5 from a CDN plus two lines
of inline override, and the question that finally forced a decision was whether
making it look good required moving to React.
[[025-decision-hand-authored-design-system]] records that it did not, and why:
seven Jinja templates of mostly read-only tables were not held back by the
absence of a framework but by the absence of design — no type scale, no spacing
rhythm, no palette, no dark mode, and money rendered with `"%.2f"` so a real
account read `$615966.75` while the SMS digest
([[022-decision-digest-four-week-spend-history]]) had been saying
`$615,966.75` all along. The replacement is a hand-authored token-driven
stylesheet: `:root` holds the light set, a `prefers-color-scheme` block redefines
the same names for dark, and no component rule contains a literal colour, so
re-theming is a token edit and the two themes cannot drift apart.

Tailwind lost on two counts that are worth separating, because only one of them
is about this repo's size. The toolchain cost is ordinary — a Node stage in a
`Dockerfile` that is otherwise a clean `pip install`
([[011-decision-doppler-hybrid-config]]). The other is
[[026-constraint-css-class-names-cross-the-json-boundary]], and it is the more
interesting constraint: `app/routes.py` puts the literal strings `text-danger` /
`text-success` into the `/api/transactions` payload, and the infinite-scroll
script applies them verbatim to appended rows. A presentation-layer name is
therefore chosen by Python, travels through JSON, and is resolved by CSS. Those
are not stock Tailwind utilities, so Tailwind would have needed a custom theme
existing solely to satisfy a line of Python — and nothing would have caught it
breaking, since the tests assert only that the payload *key* is present, never
its value. The visible failure is that the first page of transactions is coloured
correctly and every lazily-appended row after it is not.

Two rules from elsewhere in this wiki survived the rewrite by being named as
design-system states rather than left as styling. Null is not zero
([[021-decision-plaid-vested-value-piggyback-on-sync]]): a missing balance
renders an em dash and an account with no vesting schedule renders no vested row
at all, because `$0.00` asserts that nothing has vested, which is a different and
false claim. Lapsed is not unpaid ([[005-decision-bills-inactive-override]]): a
cancelled stream stays dimmed with a neutral badge, never the danger treatment. A
design pass is precisely the operation that tends to normalise both away, which
is why they were written down as acceptance criteria before the markup was
touched.

[[027-pattern-utility-classes-lose-to-element-qualified-rules]] is the defect
class the rewrite kept producing, and it belongs beside the testing blind spots
below rather than apart from them. `.table th { text-align: left }` has
specificity (0,1,1) and beats a bare `.right` utility at (0,1,0), so a numeric
column header sat visibly out of line with its own column while all 268 tests
passed. Class attributes were present and correct in the HTML; only the computed
style was wrong. Neither a text-assertion suite nor a subagent reading the diff
can observe that — a screenshot found it, and a contrast regression that put
2.58:1 grey on every table header in the app. For visual work, rendering the page
and looking at it is not a nicety layered on the tests; it is the only instrument
that sees this category at all.

## Testing and local verification

[[004-pattern-seed-relative-dates-in-time-sensitive-tests]] is the
cross-cutting testing rule: any test exercising a code path that calls
`date.today()` must seed fixtures relative to today (or freeze the clock) —
fixed calendar dates drift across behavioral boundaries and turn green tests
into delayed-fuse failures. Pure functions sidestep this by taking the
reference date as a parameter — the stance `spending.py`, `bills.py`, and
`subscriptions.py` all follow, and which the digest's message builders extend.

[[017-pattern-migration-chain-is-postgres-only]] covers the blind spot the test
suite leaves. `conftest.py` builds its schema with `db.create_all()` from the
models, never through Alembic, and the chain cannot be replayed on SQLite anyway
because an early revision issues Postgres `GRANT`s — so **a migration can be
wrong in a way no test catches**. The workaround is to exercise a new revision
in isolation: stamp its parent, hand-create the tables it touches, upgrade,
assert the schema, downgrade, assert the inverse. Good for portable DDL only.

[[020-pattern-injected-fakes-hide-construction-failures]] is the third blind
spot, and the one that let a real bug ship. Dependency injection makes the
notifier testable, but every test passed a fake sender, so the factory that
builds the *real* client never ran — the whole suite passed on a machine with
`twilio` not installed, and production failed on exactly that line. The seam
that makes code testable is the seam the tests never cross: injection proves
behaviour *given* a working dependency, never that one can be built. Stub the
third-party module in `sys.modules` and assert both halves — construction
succeeds with complete config, and a construction failure propagates to the
caller.

[[023-bug-transactions-sync-is-not-the-only-account-source]] is the same blind
spot in its fixture form, and it also let a real bug ship. Every investments test
seeded the brokerage account into the `transactions/sync` accounts array by hand,
so the suite exercised — and passed against — code that could never create that
account itself. Where 020's fake stood in for a dependency that was never built,
here the fixture stood in for a payload Plaid never sends. The general rule is one
step up from both: **a test that supplies the thing whose absence is the bug
cannot detect the bug**. The unit that shipped it had asserted the payload's
contents in its proposal as fact, without checking; the correction was verified
against the live production dashboard, not against a mock.

[[028-pattern-byte-assertions-are-contracts-or-snapshots]] is the fourth, and
unlike the three above it is a blind spot in the *reader* rather than the suite.
The route tests assert literal substrings of rendered HTML, and those assertions
are two different kinds wearing one syntax. Some are **contracts** —
`b'Vested' not in res.data` guards 021's null-is-not-zero rule, `b'Due ' not in`
does the same for liabilities (note the trailing space, and that it matches
anywhere on the page), and `'Total $950.00' in body` proves the month total is
institution-scoped, where the word `Total` is the anchor that stops the probe
matching any figure at all. Others are **formatting snapshots** — `b'$12345.67'`
pins an incidental rendering and broke by design the moment thousands separators
landed. Editing a snapshot to get green is correct; editing a contract to get
green ships the regression the contract existed to catch. The asymmetry is the
whole point, and it cuts both ways: refusing to edit *any* test forces real
formatting work to be abandoned or faked. Classify before you edit, and say in
the diff which kind you decided it was.

[[033-pattern-sqlite-tests-cannot-catch-postgres-transaction-aborts]] is the
fifth, and it is the backend itself. Tests run on SQLite, production on
Postgres, and the two disagree about what a failed statement does to an open
transaction: Postgres aborts it, so every later statement raises until someone
rolls back, while SQLite carries on. A bare `try/except` around a best-effort
write is therefore not error handling on production — it is a second, worse
failure, and the suite passes with and without the fix (verified by removing the
savepoint and re-running). Wrap best-effort DB steps in
`db.session.begin_nested()`; `_create_account_if_missing` is the reference
implementation. This is the same SQLite-vs-Postgres gap
[[017-pattern-migration-chain-is-postgres-only]] describes for migrations,
reaching runtime behaviour instead of schema.

## Limitations

A link here attests synthesis **intent**, not body **content**: an entry can stay
linked from a narrative that no longer describes it, and nothing detects that.
Coverage is derived from the links themselves, so in-place edits to an entry this
file already links — a rewired `## Related` block, a supersession banner — leave
no signal. Entries promoted after this synthesis show as un-synthesized until the
next refresh.

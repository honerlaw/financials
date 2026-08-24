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

## Acting on synced data: the daily digest

Beyond deriving views, the app sends outbound SMS. The shape of that notifier has
changed once already, and the two entries should be read in order.

[[010-decision-budget-alert-notifier]] built it as a *reactive* alert: after
every sync, each recipient was texted once per Sun–Sat week for each
newly-crossed 50/75/100% threshold of the week's household spend.
[[016-decision-daily-digest-notifier]] supersedes that cadence. Threshold
alerting had two properties nobody wanted — a quiet week produced **zero**
texts, so there was no "where do we stand" signal unless spending was already
high; and the send landed on whichever sync first observed the crossing,
including the background sync `/api/sync` fires on every dashboard page load, so
the arrival time was unpredictable. It is now one digest per recipient per day —
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
notifies** — `sync_all_institutions()` (what page loads call) is now silent and
`run_daily_sync()` is the single notifying path, which is what buys predictable
timing. **A wall-clock schedule needs an explicit timezone**: the container sets
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

## Limitations

A link here attests synthesis **intent**, not body **content**: an entry can stay
linked from a narrative that no longer describes it, and nothing detects that.
Coverage is derived from the links themselves, so in-place edits to an entry this
file already links — a rewired `## Related` block, a supersession banner — leave
no signal. Entries promoted after this synthesis show as un-synthesized until the
next refresh.

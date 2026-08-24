# Proposal: investment-account-rows

**Date**: 2026-08-24
**Status**: Shipped (2026-08-24)

## Goal

An account Plaid reports on an Item but that `/transactions/sync` omits must
still get an `Account` row, so it renders a dashboard card. Concretely: the
linked E*TRADE from Morgan Stanley stock-plan account, which has been connected,
active and syncing cleanly since it was linked and has never appeared on the
dashboard.

## Why

`Account` rows are created in exactly one place — `_upsert_accounts` in
`app/sync.py` — fed exclusively by the `accounts` array that `/transactions/sync`
returns ([[001-decision-plaid-accounts-piggyback-on-sync]]). Plaid's transactions
product does not cover brokerage/stock-plan accounts, so for an investment-only
Item that array comes back without them and no row is ever written. The three
dedicated refreshes that *do* see the account — `_refresh_balances`,
`_refresh_liabilities`, `_refresh_investments` — each do `if row is None:
continue`, discarding it. The dashboard renders one card per `Account` row, so
the account is structurally unreachable.

Confirmed in production on 2026-08-24, not inferred:

- `/settings` lists `E*TRADE from Morgan Stanley`, Active, last synced 11:34 AM,
  **0 transactions**.
- Its SyncLog rows read `✓ OK` with no error — the loss is completely silent.
- The dashboard renders exactly three account cards: American Express, Citibank
  Online, SoFi. No E*TRADE card.
- Reproduced locally: a sync where `transactions/sync` returns no accounts while
  `balance/get` and `holdings/get` both return the account persists zero
  `Account` rows and annotates nothing.

Re-connecting the Item (which the user did) could never have fixed this. That
granted the `investments` consent per
[[015-decision-liability-consent-requires-update-mode]], which was a real
prerequisite — but consent was only ever half the problem.
`_refresh_investments` may now be receiving real holdings and throwing them away
for lack of a row to attach them to.

Unit 019 missed it because its proposal asserted "`transactions/sync` returns the
account and its balance; nothing else" — an unverified cross-endpoint assumption
that is false for an investment-only Item. Every investments test pre-seeds the
brokerage account into the `transactions/sync` array by hand, so the suite could
not catch it — the same shape as
[[020-pattern-injected-fakes-hide-construction-failures]]: the fixture supplies
the thing whose absence is the bug.

## Approach (as shipped)

The rule for both changes below is **create-only**: each new path may INSERT a
row for an account that has none, and may not change what happens to a row that
already exists. That keeps the metadata/balance ownership split of
[[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] intact — the
piggyback still owns metadata for every account it returns, `/accounts/balance/get`
still owns balances — and confines the blast radius to accounts that today do
not exist at all.

### 1. `_refresh_balances` creates rows it currently skips

`/accounts/balance/get` returns every account on the Item in the same payload
shape `_upsert_accounts` consumes. Where the current loop does `if row is None:
continue`, it instead calls `_upsert_accounts(institution.id, [acct])` and moves
on. For an account that already has a row, the existing balance-only update runs
unchanged — including its `if balances is None: continue` skip and its
conditional `iso_currency_code` write.

Those two guards are load-bearing and are why this is not a blanket
`_upsert_accounts(institution.id, accounts)` call: `_upsert_accounts` writes
`current_balance`/`available_balance`/`iso_currency_code` unconditionally, so a
response with an absent `balances` object would null a known balance, and Plaid
sets `iso_currency_code` to null whenever `unofficial_currency_code` is
populated — which would silently clobber a known currency code.

This is the general fix: it covers any account of any type that
`transactions/sync` omits.

### 2. `_refresh_investments` creates rows from the holdings payload

`InvestmentsHoldingsGetResponse` carries `accounts: [InvestmentAccount]` —
"the accounts associated with the Item" — alongside `holdings`.
`InvestmentAccount` composes `AccountBase` and exposes the same `account_id` /
`name` / `mask` / `subtype` / `balances` fields `_upsert_accounts` reads
(verified against plaid-python 39.2.0). This is the one payload **guaranteed by
schema** to carry investment accounts.

`PlaidClient.get_investment_holdings` is therefore **renamed** to
`get_investments` and returns `(accounts, holdings)`. The rename is deliberate:
a same-named method that silently changed from returning a list to returning a
tuple would let the seven existing `get_investment_holdings.return_value = [...]`
mocks destructure a two-element list of holdings into `accounts, holdings`
without raising. Renaming makes every stale mock fail loudly.

`_refresh_investments` upserts those accounts **before** its `if not holdings:
return None` early return, so an investment account whose holdings are empty
still gets a row.

### 3. Both creations go through a savepoint

Added in review. `plaid_account_id` is unique and syncs overlap — `/api/sync`
spawns an unsynchronized thread on every dashboard load, on top of the 7am job —
so two runs can both see a new account missing and the loser's `INSERT` raises
`IntegrityError`. That is not a `plaid.ApiException`, so it would escape both
refreshes' "never re-raises" contract *and* `_sync_institution`'s except clause:
the institution's already-upserted transactions discarded, its SyncLog row lost,
every institution after it skipped, silently, because the thread just dies.

`_create_account_if_missing` does the insert inside `db.session.begin_nested()`.
The savepoint is the load-bearing part, not the `except`: catching the error
without one leaves the session unusable and the sync dies one statement later.
Updating never had this race; creating does.

### Which of the two actually fixes E*TRADE is not yet known

Both are implemented because that question is open, and answering it wrong is
what caused this bug in the first place. (2) is schema-guaranteed to carry
investment accounts. (1) is schema-*permitted* to — `AccountType` includes
`investment` — but whether Plaid returns brokerage accounts from
`/accounts/balance/get` for this specific Item cannot be verified from the
workstation: it needs the Item's `access_token`, which lives in a Postgres whose
trusted-sources list admits only DO apps and tagged droplets. Neither path is
claimed as "the primary fix"; the post-deploy check in the success criteria is
what settles it.

### Rejected alternatives

- **A dedicated `/accounts/get` call.** The canonical account-metadata endpoint,
  and it would unambiguously return every account. Rejected because (1) and (2)
  reach the same data from responses the sync already fetches, so it buys an
  extra round-trip per institution per sync for nothing. Worth stating precisely
  why [[001-decision-plaid-accounts-piggyback-on-sync]] alone does *not* settle
  this: 001 rejected `accounts/get` as redundant *because* `transactions/sync`
  already returned the same accounts. For an investment-only Item that premise is
  false — 001 never considered this account class. The rejection stands on cost,
  not on precedent.
- **A blanket `_upsert_accounts(institution.id, accounts)` in `_refresh_balances`.**
  Fewer lines and a tidier-looking collapse of duplicated field writes, but it
  drops the two guards described above and widens a function documented as
  "force-refresh real-time balances" into one that rewrites `name`,
  `official_name`, `mask`, `type` and `subtype` on every account on every sync —
  reversing 002's metadata/balance split silently.
- **Fixing only (2).** Smaller, and it covers the confirmed failing account if
  balance/get turns out not to. But it leaves the general hole open: any
  non-investment account `transactions/sync` omits stays invisible.
- **Annotating the SyncLog when a payload names an unknown `account_id`.** The
  silent discard is why this took a day to find, and
  [[015-decision-liability-consent-requires-update-mode]] already recorded that
  suppressing feedback costs diagnosis. Deferred rather than done: with (1) in
  place the condition becomes unreachable on the balance and investment paths.
  It stays reachable in principle on the liability path, which gets no
  equivalent fallback here and still assumes a credit/loan account is always
  also transactions-covered. Filed as a follow-up rather than widened into.

## Success criteria

1. A sync where `transactions/sync` returns an empty accounts array and
   `/accounts/balance/get` returns an account persists an `Account` row carrying
   that account's name, mask, type, subtype and balance.
2. A sync where neither `transactions/sync` nor `/accounts/balance/get` returns
   the account, but `/investments/holdings/get` does, persists the row and
   writes its vested / unvested totals.
3. An investment account present in the holdings payload with **no** holdings
   still gets a row.
4. Neither new path changes any existing row: for an account that already has a
   row, `_refresh_balances` writes exactly the fields it writes today, still
   skipping when `balances` is absent and still leaving `iso_currency_code`
   untouched when the payload's is null.
5. `get_investments` returns `(accounts, holdings)`; every call site and mock is
   updated, and no stale `get_investment_holdings` mock survives.
6. No schema change and no migration — `Account` gains no columns.
7. `pytest` passes, including the seven existing investments tests rewritten for
   the new return shape.
8. **Post-deploy, in production**: after the change deploys and a sync runs, the
   dashboard renders an E*TRADE card. Recorded with it: which endpoint created
   the row — settling the open question above — and whether the card shows
   vested / unvested figures or a bare balance.

## Open Questions

**Does `/accounts/balance/get` return this Item's stock-plan account?** Settled
by criterion 8, not before. If it does not, path (2) is doing the real work and
the account's balance will only ever be written once, at creation — because
`_refresh_balances` will never see it again to update it. That would make
"let the investments refresh maintain balances for accounts balance/get omits" a
genuine follow-up, and criterion 8's observation of whether the card's balance
moves on the following sync is what detects it.

Review sharpened this: the vested-totals loop sets `last_synced_at = now` on
every sync regardless, so in that branch the card and the daily digest would
present a balance frozen at creation day *as freshly synced*, with no staleness
signal. That is the part worth acting on if criterion 8 lands that way — the
misreported freshness, more than the stale number itself. Not fixed here
because the fix differs depending on the answer (if balance/get does return the
account, there is nothing to fix), and the answer arrives minutes after deploy.

**Whether E*TRADE reports a `vested_value` at all** remains open from unit 019
and is untouched by this change. If the card appears with a bare balance and no
vested split, that is 019's open question surfacing — a separate matter from
this one, and no longer masked by the account being invisible.

**#28 is adjacent, not this.** "Plaid-derived `Account` columns are never cleared
when the institution stops reporting them" is about stale values on rows that
exist; this is about rows that never exist. Not adopted.

## Verification

`pytest`: 268 passed (260 on main; +8). New coverage: an account seen only in the
balance payload; an account seen only in the holdings payload, including its
vested/unvested totals landing once a row exists; an investment account with no
holdings at all; the create-only guard on both paths (metadata left alone for a
known account, on `_refresh_balances` and `_refresh_investments` alike); the two
guards the create-only design exists to preserve (`balances is None` skip, null
`iso_currency_code` not clobbering a known code); and `_create_account_if_missing`
swallowing a racing `IntegrityError` while leaving the session usable.

Found in review and fixed: the concurrent-insert race (§3) and the missing
create-only test on the investments path — without the latter, deleting that
guard as "redundant" would have kept the suite green while reversing 002's
metadata/balance split.

The rename to `get_investments` was load-bearing in practice, not just in
principle: it immediately failed 8 pre-existing tests that had never configured
the investments mock at all, relying on a bare `MagicMock` that `if not holdings`
happened to treat as falsy. Under the old name a two-element list mock would have
destructured into `accounts, holdings` without raising and those tests would have
kept passing while exercising nothing.

**Criterion 8 is not met at merge and cannot be** — it is a post-deploy
observation. Whether `/accounts/balance/get` returns this Item's stock-plan
account turns on the Item's own behavior, so no sandbox call settles it; it needs
the `access_token`, which lives in a Postgres whose trusted sources admit only DO
apps and tagged droplets. Both code paths ship for that reason. The check to run
after deploy: trigger a sync, confirm the dashboard renders an E*TRADE card, and
record which endpoint created the row and whether vested/unvested figures appear.

Deferred, contingent on that answer: if balance/get turns out to omit the
account, its balance is written once at creation and never refreshed while
`last_synced_at` is bumped every sync — a stale balance presented as fresh. The
follow-up is filed only if the post-deploy check lands that way; filing it now
would be speculative.

Filed regardless: #34 — the sync silently drops payload rows naming an unknown
`account_id`, which is why this bug was invisible for a day.

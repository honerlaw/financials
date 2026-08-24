# Scratchpad: investment-account-rows

## Balanced decisions 2026-08-24

- [decided] pre-flight: no in-flight collision (014, 020 unpromoted but disjoint in slug and goal); #28 judged adjacent, not a match — no adoption gate fired
- [decided] coordination: peer session financials-a5 is mid-propose on /subscriptions perf, holds no branch/worktree, edits disjoint at function level; agreed this unit goes first, tests/test_sync.py is the only shared file
- [reviewed — clean] scope check: single unit (Skeptic accept — both changes act on one causal layer, account-row creation). Two non-scope concerns carried into the approach gate: the KB 001/002 metadata-ownership reversal, and the unverified balance/get premise
- [reviewed — folded] approach: Skeptic returned `revise` on three high-severity points, all folded —
  (a) a blanket `_upsert_accounts` in `_refresh_balances` drops the `balances is None` guard and the conditional iso write, nulling known balances and clobbering a currency code where `unofficial_currency_code` is set → adopted **create-only**: insert when the row is missing, existing update path untouched. Same fold also resolves the scope Skeptic's 001/002 reversal and the "force-refresh balances" blast-radius widening
  (b) changing `get_investment_holdings`' return type silently mis-destructures the seven existing list mocks → **renamed** to `get_investments` so stale mocks fail loudly
  (c) A-as-primary framing may be backwards, since investment-account visibility could be consent-gated the way the product endpoints are → reframed: (2) is schema-guaranteed, (1) is schema-permitted but unverified for this Item; neither claimed as primary, settled by post-deploy criterion 8
- [decided] verification: schema-level confirmation only (plaid-python 39.2.0 — `InvestmentsHoldingsGetResponse.accounts: [InvestmentAccount]`, `AccountType` includes `investment`, `AccountBalance.iso_currency_code` "always null if `unofficial_currency_code` is non-null"). Runtime verification needs the Item's access_token from a Postgres whose trusted sources admit only DO apps/tagged droplets; deferred to post-deploy criterion 8 rather than escalating for a firewall change
- [decided] whole-proposal soundness: single subsystem, no schema change, one internal method rename, no public interface (solo gate)

## Implementation notes 2026-08-24

- The rename to `get_investments` paid for itself immediately: 8 pre-existing
  tests that never configured the investments mock at all (relying on a bare
  `MagicMock`, which `if not holdings` happened to treat as falsy) failed loudly
  on the tuple unpack instead of silently mis-destructuring. Each got an explicit
  `get_investments.return_value = ([], [])`. Under the old name they would have
  kept passing while exercising nothing.
- `_refresh_balances`'s row lookup had to move *above* the `balances is None`
  guard: an account with metadata but no balances object should still get a row.
  The guard now applies only to the existing-row update path, which is where it
  was always load-bearing.
- Suite: 266 passed (260 on main; +6 new).

- [reviewed — clean] completion verification: Verifier `accept`, all 7 pre-merge
  criteria independently reproduced (it re-ran the suite, re-grepped the rename,
  traced the `_refresh_balances` reordering against main line by line, and
  checked for duplicate rows / wrong `institution_id` across the two new
  creation paths — none found). Criterion 8 accepted as honestly deferred: it
  turns on this Item's behavior, not on schema, so a sandbox call could not have
  settled it pre-merge. It corrected the scratchpad's arithmetic — main is 260,
  not 259, and 6 tests were added, not 7; the two errors cancelled to the right
  total. Corrected above.

## Review triage 2026-08-24

Two finding sets: a minerva audit (spec fidelity + knowledge compliance) run by
the main model, and a `code-review:code-review` pass at effort `high` over
`main...HEAD`. Triaged solo.

- **C1 [medium] → SUGGEST (deferred, record strengthened).** An account created
  only from the holdings payload has its balance written once and never
  refreshed, while `last_synced_at` is bumped every sync — a stale balance
  presented as fresh. Already the proposal's open question; the `last_synced_at`
  half is new and now written into it. Deferred because the fix differs by which
  way criterion 8 lands, and that resolves minutes after deploy.
- **C2 [low → FIXED].** Triaged above its reported severity: the new INSERTs can
  race a concurrent sync (`/api/sync` spawns a thread per dashboard load), and
  the loser's `IntegrityError` is not a `plaid.ApiException`, so it escapes both
  refreshes' "never re-raises" contract and `_sync_institution`'s except clause —
  silently discarding that institution's already-upserted transactions, its
  SyncLog row, and every institution after it. Extracted
  `_create_account_if_missing`, which does the insert inside
  `db.session.begin_nested()` and swallows `IntegrityError`. The savepoint is the
  load-bearing part: catching the error without one leaves the session broken and
  the sync dies one statement later.
- **C3 [low → FIXED].** No test pinned the create-only guard on the investments
  path, so deleting it as "redundant" would have kept the suite green while
  reversing 002's metadata/balance split. Added the mirror test.
- **C4 [low] + M1/M2 → promote phase.** Knowledge 001 ("the piggyback is the sole
  account source"), 002 ("metadata comes from the piggyback") and 021 (documents
  `get_investment_holdings`, a method that no longer exists, and asserts the
  E*TRADE account "showed a single balance on the dashboard" — it never rendered
  a card at all) are all now wrong or partial. Handled by the promoted entry plus
  superseded-by pointers, not by code.
- **M3 → promote phase.** The proposal promises the SyncLog-annotation follow-up
  is filed; it has to actually be filed.
- **M4 [low] → IGNORE.** `_create_account_if_missing` queries, then
  `_upsert_accounts` queries again — only for accounts that do not exist yet, and
  it mirrors the existing per-account-lookup pattern in both other refreshes.

Note on the race test: the first version tried to stage a real two-writer race
and passed for the wrong reason — the fake inserted in the same session, so
`_upsert_accounts` saw the row and updated it and no `IntegrityError` ever
occurred. A genuine race needs a second session committing between our existence
check and our flush, which this suite cannot stage. The test now raises the
error directly and asserts what actually matters on this side of it: the helper
swallows it *and* the session is still usable afterwards.

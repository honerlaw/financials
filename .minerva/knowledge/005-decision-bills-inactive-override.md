# Bills view: inactive streams get 'inactive' status, not 'unpaid'

**Date**: 2026-06-13
**Type**: decision
**Summary**: Inactive recurring outflows get payment_status='inactive' in detect_bills(), not 'unpaid' — prevents false alarms for cancelled/lapsed streams
**Context**: .minerva/work/006-bills-view

## Context

Work unit 006 added the `/bills` page: a pure-function detector (`app/bills.py`)
that reuses `subscriptions.py`'s cadence detection to surface recurring outflows
and adds a per-calendar-month payment status (`paid`, `unpaid`, `upcoming`).

The detector shares `_build_stream()` from `subscriptions.py`, which already
computes an `active` flag: a stream is inactive when
`(today - last_date).days > 1.5 × cadence_days`.

## Finding

An inactive recurring outflow (e.g. a cancelled gym membership or a card
payment method that changed) has no current-month transaction by definition.
Naively applying `_payment_status()` to such a stream returns `'unpaid'` — a
false alarm that would appear as a red "Unpaid" badge on the bills page for an
obligation that no longer exists.

The correct behaviour is:

- If `stream['active'] is False` → set `payment_status = 'inactive'`; render
  the row dimmed (`opacity-50`) with a grey "Inactive" badge.
- Only apply `_payment_status()` logic (paid/unpaid/upcoming) to *active* streams.

This mirrors exactly how `subscriptions.html` handles inactive streams
(`opacity-50` class, no "Active" badge), so the pattern is already established
in the codebase.

## Implications

- Adding any future payment-status logic must guard on `stream['active']` before
  computing date-based status — otherwise lapsed streams re-appear as unpaid.
- The `_STATUS_ORDER` sort puts `'inactive'` last (order 3 after paid=2), so
  genuine obligations surface at the top.
- See [[003-decision-subscriptions-cadence-only-detection]] for the `active`
  flag's definition and the INACTIVE_MULTIPLIER constant.

## Related
- [[006-decision-bills-payment-status-algorithm]] — see also

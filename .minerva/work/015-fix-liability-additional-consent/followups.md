# Follow-ups: fix-liability-additional-consent

- **Surface "needs liability consent" in the UI.** Suppressing
  `ADDITIONAL_CONSENT_REQUIRED` means nothing tells the user which
  institutions still lack the `liabilities` consent — the only symptom is that
  their due-date / balance-due fields stay null. A persisted
  `needs_liability_consent` flag on `Institution`, set when
  `_refresh_liabilities` sees the code and cleared on a successful refresh,
  could drive a targeted prompt the same way `login_required` drives the
  reconnect banner. Deferred: a column + migration + context processor is
  disproportionate for a one-time, three-institution chore in a single-user
  app.

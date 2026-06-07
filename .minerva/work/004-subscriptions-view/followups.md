# Followups: subscriptions-view

## 2026-06-07

- **Name-group fuzzy merge is order-dependent and non-transitive.** In
  `app/subscriptions.py::_group_transactions`, name-only groups merge into
  the *first* canonical group whose key fuzzy-matches (first-match `break`,
  processed in alphabetical order); name groups never re-coalesce
  transitively with each other afterward. A borderline merchant can
  therefore land in a different stream depending on alphabetical ordering,
  not similarity strength. Distinct from (and sharper than) the general
  threshold-tuning Open Question. Revisit if real synced data shows
  borderline merchants landing in the wrong stream — a union-find pass over
  pairwise matches would make grouping order-independent.

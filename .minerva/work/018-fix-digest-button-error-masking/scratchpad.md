# Scratchpad — 018-fix-digest-button-error-masking

## Quick decisions 2026-08-08
- [decided] scope: single unit — one bug with three contributing defects on the same failure path, plus the test gap that let it ship
- [decided] surface the exception message to the client, not a generic string — single-user password-protected app, and naming the failure is the whole point; truncate to 300 chars, full traceback stays in the log
- [decided] redirect on `res.redirected && res.url` ending at /login, not on "not JSON" — refines 012 rather than replacing it (the Content-Type check is still needed to avoid parsing HTML, just not sufficient as an expiry signal)
- [decided] rejected returning 401 JSON from `login_required` for /api/* — cleaner signal but changes a decorator every endpoint shares; disproportionate to this bug and would need every existing fetch audited
- [decided] `app_timezone` degrades to UTC only as a last resort and logs at ERROR — 016 deliberately avoided a silent UTC fallback, so the degradation must be loud
- [decided] the 7am path's silent-failure behaviour is left alone — it is a deliberate non-fatal contract from 012/016; the button now gives an on-demand way to see the same error

## Notes
- Root cause evidence is in this session's minerva:debug report: repro showed 500 + text/html for both placeholder and well-formed AC… SIDs; traceback located the throw at `_sender_from_config`.
- Local venv lacks `twilio` (and `tzdata`) — that specific traceback is a local artifact, not prod's cause. Prod installs from requirements.txt. Prod's actual exception is still unknown; fix 1 is what will name it.

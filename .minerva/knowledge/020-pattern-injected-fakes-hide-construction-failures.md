# Injecting a fake everywhere leaves the real object's construction untested

**Date**: 2026-08-08
**Type**: pattern
**Summary**: Every notifier test injected a fake sender, so `_sender_from_config` — the line that actually threw in production — was never executed and the whole suite passed with `twilio` uninstalled; a dependency built behind a seam needs at least one test that builds the real thing.
**Context**: .minerva/work/018-fix-digest-button-error-masking

## Finding

`app/notifications.py` takes an injectable `sender`, and every test passes a
`FakeSender`. Tests that exercise the *unconfigured* path pass blank credentials,
which returns `None` before construction. The result: no test ever ran
`_sender_from_config`'s actual body — the `TwilioSender(...)` call.

The tell was that the full suite passed on a machine with **`twilio` not
installed at all**. The lazy `import twilio` inside `TwilioSender.__init__`
([[010-decision-budget-alert-notifier]]) is deliberate and correct, but it means
an absent or broken dependency is invisible until something constructs the real
object at runtime. The production failure landed on exactly that line.

The seam that makes the code testable is also the seam the tests never cross.
Injection covers *behaviour given a working dependency*; it says nothing about
whether the dependency can be built.

## The rule

When a dependency is constructed behind a factory and faked everywhere else, add
at least one test that runs the real construction path. Stub the third-party
module in `sys.modules` rather than requiring it to be installed, so the test is
hermetic and runs identically in CI and on a stale local venv:

```python
def _twilio_stub(raise_on_client=None):
    rest = types.ModuleType('twilio.rest')
    class _Client:
        def __init__(self, sid, token, http_client=None):
            if raise_on_client:
                raise raise_on_client
    rest.Client = _Client
    return {'twilio': ..., 'twilio.rest': rest, ...}

with patch.dict('sys.modules', _twilio_stub()):
    assert _sender_from_config(complete_config) is not None
```

Cover both halves: construction **succeeds** with complete config, and a
construction **failure propagates** to the caller (which is what tells you
whether the caller handles it — here, it did not).

## Related

- [[019-bug-non-json-response-conflated-with-session-expiry]] — builds on
  the production bug this gap allowed to ship.
- [[010-decision-budget-alert-notifier]] — see also
  the deliberate lazy `twilio` import that makes an absent dependency invisible until runtime.
- [[023-bug-transactions-sync-is-not-the-only-account-source]] — see also
- [[034-pattern-only-the-call-site-is-authoritative-for-runtime-behaviour]] — see also

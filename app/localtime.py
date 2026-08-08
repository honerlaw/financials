"""The app's local wall-clock timezone.

Everything scheduled or reported in "our" time resolves through here. The
container sets no ``TZ``, so bare ``date.today()`` / an untimezoned APScheduler
cron run in **UTC** — which would fire a "7am" job at 3am Eastern. Both the
scheduler and the daily digest therefore take their timezone from
``APP_TIMEZONE``.

Transaction dates, week boundaries (``app/spending.py``) and the ``created_at``
UTC timestamps are deliberately untouched by this module.
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = 'America/New_York'

log = logging.getLogger(__name__)


def app_timezone(config):
    """The configured ``ZoneInfo``, falling back to ``DEFAULT_TIMEZONE``.

    A bad ``APP_TIMEZONE`` (typo in Doppler) must not take the app down, and
    must not silently degrade to UTC either — UTC is precisely the wrong answer
    for a "send this at 7am" job. It warns and uses the default instead.
    """
    name = config.get('APP_TIMEZONE') or DEFAULT_TIMEZONE
    # Deduped so an unset (or already-default) APP_TIMEZONE isn't looked up
    # twice and then reported as "unknown 'America/New_York' — falling back to
    # America/New_York".
    for candidate in dict.fromkeys((name, DEFAULT_TIMEZONE)):
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            if candidate != DEFAULT_TIMEZONE:
                log.warning('unknown APP_TIMEZONE %r — falling back to %s',
                            candidate, DEFAULT_TIMEZONE)

    # Reaching here means no tz database is present at all. This used to raise
    # the very error it was recovering from, killing every caller including a
    # web request. UTC is the wrong *schedule* but a working *app*. Loud,
    # because the New York default exists precisely so a silent UTC fallback
    # can't happen quietly.
    log.error('no tz database available — degrading to UTC; the daily '
              'digest will fire on a UTC clock until tzdata is installed')
    return timezone.utc


def local_now(config):
    """Current time in the app's timezone."""
    return datetime.now(app_timezone(config))


def local_today(config):
    """Today's date in the app's timezone (not UTC's date)."""
    return local_now(config).date()

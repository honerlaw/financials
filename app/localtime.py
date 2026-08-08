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
from datetime import datetime
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
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning('unknown APP_TIMEZONE %r — falling back to %s',
                    name, DEFAULT_TIMEZONE)
        return ZoneInfo(DEFAULT_TIMEZONE)


def local_now(config):
    """Current time in the app's timezone."""
    return datetime.now(app_timezone(config))


def local_today(config):
    """Today's date in the app's timezone (not UTC's date)."""
    return local_now(config).date()

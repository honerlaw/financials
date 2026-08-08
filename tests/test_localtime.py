import logging
from datetime import date

from freezegun import freeze_time

from app.localtime import DEFAULT_TIMEZONE, app_timezone, local_today


def test_app_timezone_uses_config():
    assert str(app_timezone({'APP_TIMEZONE': 'Europe/London'})) == 'Europe/London'


def test_app_timezone_defaults_when_unset():
    assert str(app_timezone({})) == DEFAULT_TIMEZONE


def test_unknown_timezone_falls_back_to_default_not_utc(caplog):
    """A typo must not take the app down — nor silently degrade to UTC, which is
    exactly the wrong answer for a 'send this at 7am' job."""
    with caplog.at_level(logging.WARNING, logger='app.localtime'):
        assert str(app_timezone({'APP_TIMEZONE': 'Mars/Olympus_Mons'})) == DEFAULT_TIMEZONE
    assert 'Mars/Olympus_Mons' in caplog.text


@freeze_time('2026-08-09 03:30:00')  # 11:30pm Aug 8 in New York
def test_local_today_is_not_utc_date():
    assert local_today({'APP_TIMEZONE': 'America/New_York'}) == date(2026, 8, 8)
    assert local_today({'APP_TIMEZONE': 'UTC'}) == date(2026, 8, 9)

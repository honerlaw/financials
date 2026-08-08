from unittest.mock import patch

from app.scheduler import DAILY_JOB_HOUR, start_scheduler


def _daily_job(app):
    """Start the scheduler, hand back (scheduler, job), and never leave it running."""
    scheduler = start_scheduler(app)
    try:
        return scheduler, scheduler.get_job('daily_sync')
    finally:
        scheduler.shutdown(wait=False)


def test_daily_job_runs_at_7am_in_app_timezone(app):
    app.config['APP_TIMEZONE'] = 'America/New_York'
    scheduler, job = _daily_job(app)
    assert str(scheduler.timezone) == 'America/New_York'
    assert str(job.trigger.timezone) == 'America/New_York'
    assert f"hour='{DAILY_JOB_HOUR}'" in str(job.trigger)
    assert "minute='0'" in str(job.trigger)


def test_daily_job_dispatches_the_digest_path(app):
    """The scheduled callable must be run_daily_sync (which texts), not the bare
    sync (which must not).

    Patched before the scheduler starts: start_scheduler imports the callable
    into its closure, so a later patch would not be seen.
    """
    with patch('app.sync.run_daily_sync') as mock_run:
        _, job = _daily_job(app)
        job.func()
    assert mock_run.called

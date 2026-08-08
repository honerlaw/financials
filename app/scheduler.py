"""The app's in-process scheduler: one daily job at 7am local time.

Correct only under a single gunicorn worker (``entrypoint.sh: --workers 1``) —
with more workers every process would run its own copy of the job. The digest
notifier depends on the same invariant (see app/notifications.py).
"""
from app.localtime import app_timezone

DAILY_JOB_HOUR = 7


def start_scheduler(app):
    """Register and start the daily sync + digest job. Returns the scheduler.

    The timezone is passed as an IANA name rather than a ``tzinfo`` so the
    conversion stays APScheduler's own across versions; ``app_timezone`` has
    already validated it (and fallen back if it was junk).
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.sync import run_daily_sync

    scheduler = BackgroundScheduler(daemon=True,
                                    timezone=str(app_timezone(app.config)))

    def job():
        with app.app_context():
            run_daily_sync()

    scheduler.add_job(func=job, trigger='cron', hour=DAILY_JOB_HOUR, minute=0,
                      id='daily_sync', max_instances=1)
    scheduler.start()
    return scheduler

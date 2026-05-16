from app import create_app

app = create_app()


def _start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.sync import sync_all_institutions

    scheduler = BackgroundScheduler(daemon=True)

    def job():
        with app.app_context():
            sync_all_institutions()

    scheduler.add_job(func=job, trigger='cron', hour=7, minute=0,
                      id='daily_sync', max_instances=1)
    scheduler.start()


_start_scheduler()

if __name__ == '__main__':
    app.run()

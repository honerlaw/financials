from app import create_app
from app.scheduler import start_scheduler

app = create_app()

# Cron times are wall-clock in APP_TIMEZONE, not UTC: the container sets no TZ,
# so an untimezoned scheduler would fire the "7am" job at 3am Eastern.
start_scheduler(app)

if __name__ == '__main__':
    app.run()

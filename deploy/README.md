# Ubuntu Deployment

This project is designed to run on Ubuntu with:

- `systemd` for the FastAPI API
- `systemd` for the Streamlit dashboard
- `cron` for the scheduled scraper job

Do not use `cron` to keep `uvicorn` or Streamlit alive. `cron` is only for
the bounded collector job.

## Quick Start

From the project root on the server:

```bash
bash deploy/bootstrap_server.sh
cp .env.example .env
```

Edit `.env`, then run:

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
bash deploy/install_services.sh
bash deploy/install_cron.sh
bash deploy/check_live.sh
```

For a single authenticated X account, start with:

```dotenv
KEYWORD_CONCURRENCY=1
CRON_SCHEDULE=*/5 * * * *
MAX_TWEETS_PER_RUN=60
DISCOVERY_LIMIT_PER_KEYWORD=25
RATE_LIMIT_COOLDOWN_MIN_SECONDS=900
RATE_LIMIT_COOLDOWN_MAX_SECONDS=1800
```

For alerting, also set in `.env`:

```dotenv
ALERT_EMAIL_TO=work.mihirkate@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_gmail_address
SMTP_PASSWORD=your_gmail_app_password
MONITOR_RESTART_SERVICES=true
WATCHDOG_SCHEDULE=*/2 * * * *
HEALTH_REPORT_SCHEDULE=0 * * * *
```

The cron installer now adds:

- the scraper schedule
- the watchdog/recovery schedule
- the hourly health email schedule

## Public Access

If you are exposing the app directly by public IP:

- API: `http://SERVER_IP:8000/health`
- Dashboard: `http://SERVER_IP:8501`

The dashboard refreshes itself periodically, so a recruiter watching the page
should see newer counts after scrape runs without manually reloading the tab.

On AWS, the instance security group must allow inbound TCP:

- `8000`
- `8501`

If you later add Nginx, you can front both services with `80/443`.

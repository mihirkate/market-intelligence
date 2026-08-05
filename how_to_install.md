# How To Install And Test

This guide installs the current `market-intelligence` project on a local machine
or an Ubuntu server.

The deployment model is:

- `systemd` keeps the FastAPI API running persistently
- `systemd` keeps the Streamlit dashboard running persistently
- `cron` only triggers the short-lived scraper job

## 1. Requirements

- Ubuntu or another Linux system
- Python `3.12+`
- Network access to MongoDB Atlas
- Valid X credentials for `twscrape`

## 2. Clone Or Copy The Project

```bash
cd ~
git clone <your-repo-url> market-intelligence
cd market-intelligence
```

If the repo is already present:

```bash
cd ~/market-intelligence
```

## 3. Local Installation

Create the virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Create the runtime env file:

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

- `MONGODB_URI`
- `X_USERNAME`
- `X_AUTH_TOKEN`
- `X_CT0`

Optional but recommended:

- `MAX_TWEETS_PER_RUN=60`
- `DISCOVERY_LIMIT_PER_KEYWORD=25`
- `CRON_SCHEDULE=*/5 * * * *`
- `KEYWORD_CONCURRENCY=1`
- `ALERT_EMAIL_TO=work.mihirkate@gmail.com`
- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USERNAME=your_gmail_address`
- `SMTP_PASSWORD=your_gmail_app_password`

Bootstrap the local `twscrape` account database:

```bash
python -m app.scraper.twscrape_setup
```

## 4. Run Locally

Start the API:

```bash
source .venv/bin/activate
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

In another terminal, start the dashboard:

```bash
cd ~/market-intelligence
source .venv/bin/activate
streamlit run dashboard/main.py
```

The dashboard auto-refreshes by default every `30` seconds. Control that with:

- `DASHBOARD_AUTO_REFRESH_ENABLED=true`
- `DASHBOARD_AUTO_REFRESH_SECONDS=30`

Useful checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/stats
python -m app.scraper.account_status
python -m app.scraper.collection_status
```

## 5. Local Testing

Backend API:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/stats
curl http://127.0.0.1:8000/collection-status
curl http://127.0.0.1:8000/analysis-summary
```

Dashboard:

- open `http://127.0.0.1:8501`
- verify counters load
- wait `30` seconds and confirm the page refreshes automatically
- confirm the latest run and 24h collected metrics update after a scrape run

Scraper:

```bash
python -m app.scraper.account_status
python -m app.scraper.manager
python -m app.scraper.collection_status
cat reports/data_collection_status.json
```

Repo verification:

```bash
pytest -q
python -m compileall app tests run.py dashboard
```

## 6. Ubuntu Server Installation

The repo includes deployment scripts for Ubuntu.

Run:

```bash
cd ~/market-intelligence
bash deploy/bootstrap_server.sh
cp .env.example .env
```

Edit `.env` and verify:

- `API_HOST=0.0.0.0`
- `API_PORT=8000`
- `DASHBOARD_HOST=0.0.0.0`
- `DASHBOARD_PORT=8501`
- `DASHBOARD_AUTO_REFRESH_ENABLED=true`
- `DASHBOARD_AUTO_REFRESH_SECONDS=30`
- `MONGODB_URI=...`
- valid X auth values
- `KEYWORD_CONCURRENCY=1`
- `CRON_SCHEDULE=*/5 * * * *`
- `MAX_TWEETS_PER_RUN=60`
- `DISCOVERY_LIMIT_PER_KEYWORD=25`
- `ALERT_EMAIL_TO=work.mihirkate@gmail.com`
- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USERNAME=your_gmail_address`
- `SMTP_PASSWORD=your_gmail_app_password`
- `MONITOR_RESTART_SERVICES=true`
- `MONITOR_REBOOT_ON_CRITICAL=false`
- `WATCHDOG_SCHEDULE=*/2 * * * *`
- `HEALTH_REPORT_SCHEDULE=0 * * * *`

If you want the host to reboot itself after repeated failed recovery attempts,
set:

- `MONITOR_REBOOT_ON_CRITICAL=true`
- `MONITOR_FAILURES_BEFORE_REBOOT=3`

Bootstrap `twscrape`:

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
```

Install the API and dashboard as `systemd` services:

```bash
bash deploy/install_services.sh
```

This is the persistent process manager for:

- `uvicorn app.api.main:app --host 0.0.0.0 --port 8000`
- `streamlit run dashboard/main.py --server.address 0.0.0.0 --server.port 8501`

Do not run either of those through `cron`.

Install the scheduled scraper cron job:

```bash
bash deploy/install_cron.sh
```

Run a live check:

```bash
bash deploy/check_live.sh
```

The installed cron block now includes:

- the scraper job
- the watchdog job that checks API/dashboard health and restarts services if needed
- the hourly health email job

## 7. Service Management

Check service status:

```bash
sudo systemctl status market-intelligence-api --no-pager
sudo systemctl status market-intelligence-dashboard --no-pager
```

Restart services:

```bash
sudo systemctl restart market-intelligence-api
sudo systemctl restart market-intelligence-dashboard
```

View logs:

```bash
journalctl -u market-intelligence-api -n 100 --no-pager
journalctl -u market-intelligence-dashboard -n 100 --no-pager
tail -f logs/app.log
tail -f logs/cron.log
```

The persistent deployment model is:

- `market-intelligence-api.service` keeps the FastAPI process alive
- `market-intelligence-dashboard.service` keeps the Streamlit process alive
- `cron` starts only the short-lived collector job

If either web service exits, `systemd` restarts it automatically.

If the watchdog sees that a service restarted or became unhealthy, it sends an
email with service status and log excerpts, then attempts recovery.

## 8. Cron Verification

Check the installed cron entry:

```bash
crontab -l
python -m app.scheduler.cron status
```

The scraper runs as a short-lived job and should:

- respect cooldowns
- skip overlapping runs
- update `reports/data_collection_status.json`
- leave the API and dashboard lifecycle to `systemd`
- run the watchdog on `WATCHDOG_SCHEDULE`
- send the hourly health email on `HEALTH_REPORT_SCHEDULE`

## 9. Public Access

If you expose the app directly by server IP:

- API: `http://SERVER_IP:8000/health`
- Dashboard: `http://SERVER_IP:8501`

On AWS, allow inbound traffic for:

- `8000`
- `8501`

Useful checks from your laptop:

```bash
curl http://SERVER_PUBLIC_IP:8000/health
curl http://SERVER_PUBLIC_IP:8000/stats
curl -I http://SERVER_PUBLIC_IP:8501
```

The recruiter-facing dashboard should be:

- reachable at `http://SERVER_PUBLIC_IP:8501`
- refreshed automatically every `DASHBOARD_AUTO_REFRESH_SECONDS`
- backed by live MongoDB data updated by cron scraper runs

## 10. Server Testing

After deployment, run these on the server:

```bash
sudo systemctl status market-intelligence-api --no-pager
sudo systemctl status market-intelligence-dashboard --no-pager
crontab -l
python -m app.scraper.account_status
python -m app.scraper.collection_status
cat reports/data_collection_status.json
```

Manual smoke run for the scraper:

```bash
python -m app.scraper.manager
python -m app.scraper.collection_status
```

Manual smoke run for monitoring:

```bash
python -m app.monitoring.watchdog_job
python -m app.monitoring.hourly_report_job
```

What to verify:

- API returns HTTP `200`
- dashboard opens publicly
- dashboard auto-refreshes without manual reload
- `reports/data_collection_status.json` updates after scraper runs
- `recent_run_count` increases over time
- `total_unique_tweets_last_24_hours` moves upward
- services survive disconnects because `systemd` owns them
- the alert email arrives at `ALERT_EMAIL_TO`
- the hourly health email arrives every hour

## 11. Files To Watch

- `logs/app.log`
- `logs/cron.log`
- `reports/data_collection_status.json`
- `reports/processing_report.json`
- `reports/analysis_summary.json`
- `reports/performance_benchmark.json`

## 12. Completion Check

The data-collection requirement is complete only when:

- `reports/data_collection_status.json` shows
  `assignment_data_collection_ready: true`
- `total_unique_tweets_last_24_hours >= 2000`

## 13. Common Problems

Missing `crontab` command:

```bash
sudo apt-get update
sudo apt-get install -y cron
sudo systemctl enable --now cron
```

MongoDB connection problems:

- verify `MONGODB_URI`
- verify Atlas network allowlist
- verify the server can reach Atlas

X account rate-limited:

- check `python -m app.scraper.account_status`
- inspect `data/raw/checkpoint.json`
- inspect `data/raw/debug/`
- wait for cooldown and let cron continue

Dashboard does not refresh:

- confirm `DASHBOARD_AUTO_REFRESH_ENABLED=true`
- confirm `DASHBOARD_AUTO_REFRESH_SECONDS=30`
- restart the dashboard service
- check browser dev tools for blocked scripts/extensions

API or dashboard not persistent:

- do not run them under `cron`
- use `bash deploy/install_services.sh`
- verify `sudo systemctl status market-intelligence-api --no-pager`
- verify `sudo systemctl status market-intelligence-dashboard --no-pager`

Email alert does not arrive:

- verify `ALERT_EMAIL_TO`
- verify `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`
- if using Gmail, use an app password, not the account password
- run `python -m app.monitoring.hourly_report_job`
- inspect `logs/health-report.log` and `logs/watchdog.log`

Whole EC2 instance crash:

- the watchdog can restart services and can optionally trigger `reboot` if the host is still alive
- if the entire VM is hard-down, in-instance code cannot recover it by itself
- for full instance recovery, add AWS EC2 auto-recovery / CloudWatch outside this repo

## 14. Submission Cleanup

Before pushing the repo:

```bash
bash scripts/prepare_submission.sh
```

Then review [docs/submission_checklist.md](/home/mihir/market-intelligence/docs/submission_checklist.md).

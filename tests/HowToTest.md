# How To Test

This checklist is written for a recruiter or reviewer.

The current public demo referenced in this checklist is hosted on AWS EC2.

Use it in this order:

1. quick repository validation
2. local service validation
3. live scraper validation
4. optional monitoring validation
5. optional Ubuntu server validation

## 1. Quick Repository Validation

This path does not require live X credentials or a running MongoDB instance.

```bash
cd ~/market-intelligence
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pytest -q
python -m compileall app tests run.py dashboard
```

Expected result:

- tests pass
- compileall completes without import errors
- the reviewer can inspect the codebase without configuring external secrets first

## 2. Full Local Validation Prerequisites

To validate the live application end to end, the reviewer needs:

- MongoDB Community or MongoDB Atlas
- one valid X account/session for `twscrape`

Create the runtime env file:

```bash
cp .env.example .env
```

At minimum, configure:

```dotenv
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DATABASE=market-intelligence
X_USERNAME=your_x_handle
X_AUTH_TOKEN=your_auth_token
X_CT0=your_ct0_token
```

Alternative supported X auth paths:

- `X_USERNAME` + `X_COOKIES`
- `X_USERNAME` + `X_PASSWORD` + `X_EMAIL` + `X_EMAIL_PASSWORD`
- `X_ACCOUNTS_JSON=[...]`

## 3. Bootstrap `twscrape`

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
python -m app.scraper.account_status
```

Expected result:

- `data/twscrape/accounts.db` exists
- `account_status` prints JSON for the configured account(s)
- if a lock exists, `remaining_seconds` shows the cooldown

## 4. Validate One Collector Run

```bash
source .venv/bin/activate
python -m app.scraper.manager
python -m app.scraper.collection_status
```

Expected result:

- tweets are upserted into MongoDB database `market-intelligence`
- raw tweet archives appear under `data/raw/date=YYYY-MM-DD/`
- parquet exports appear under `data/parquet/tweets/` and `data/parquet/signals/`
- collection report is written to `reports/data_collection_status.json`
- processing and analysis reports are updated

Inspect:

```bash
cat reports/data_collection_status.json
```

Confirm:

- `total_unique_tweets_last_24_hours` is present
- `remaining_tweets_to_target` is present
- `assignment_data_collection_ready` is present

## 5. Validate API And Dashboard Locally

Terminal 1:

```bash
source .venv/bin/activate
python run.py
```

Terminal 2:

```bash
source .venv/bin/activate
streamlit run dashboard/main.py --server.address 0.0.0.0 --server.port 8501
```

Check the API:

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/stats
curl http://127.0.0.1:8000/dashboard-state
curl http://127.0.0.1:8000/collection-status
curl http://127.0.0.1:8000/analysis-summary
```

Expected result:

- `/` returns `{"status":"running"}`
- `/health` returns app and MongoDB health
- `/stats` returns dashboard overview and collection progress
- `/dashboard-state` returns a lightweight DB-backed count payload

Open the dashboard:

- `http://127.0.0.1:8501/`

Expected dashboard behavior:

- the summary counts render on initial page load
- the dashboard polls the lightweight count endpoint
- the page reloads only if the stored tweet count in MongoDB increases
- if the count does not increase, the page does not reload

## 6. Validate The Refresh Behavior

This specifically tests the dashboard reload logic.

1. Open the dashboard in the browser.
2. Note the current `Stored Tweets` count.
3. Run another bounded scrape:

```bash
source .venv/bin/activate
python -m app.scraper.manager
```

4. Wait one refresh interval, controlled by:

```dotenv
DASHBOARD_AUTO_REFRESH_SECONDS=30
```

Expected result:

- if MongoDB `total_tweets` increases, the page reloads
- the new `Stored Tweets` value appears after reload
- if no new tweets were inserted, the page remains unchanged

## 7. Validate Monitoring And Email

Optional. Requires SMTP settings in `.env`.

Example:

```dotenv
ALERT_EMAIL_TO=recipient@example.com
ALERT_EMAIL_FROM=sender@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=sender@example.com
SMTP_PASSWORD=your_gmail_app_password
SMTP_USE_TLS=true
```

Run:

```bash
source .venv/bin/activate
python -m app.monitoring.hourly_report_job
python -m app.monitoring.watchdog_job
```

Expected result:

- health email is attempted
- watchdog checks the API and dashboard
- email/log output is written under `logs/`

If using Gmail:

- use an app password, not the account password

## 8. Validate Cron Rendering

```bash
source .venv/bin/activate
python -m app.scheduler.cron render
python -m app.scheduler.cron status
```

Expected result:

- `render` prints the managed cron block
- `status` prints `installed` or `not-installed`

If you want to install the cron block on the current machine:

```bash
python -m app.scheduler.cron install
crontab -l
```

Expected jobs:

- scraper job
- watchdog job
- health-report email job

## 9. Validate Performance Report

```bash
source .venv/bin/activate
python -m app.reporting.performance
cat reports/performance_benchmark.json
```

Expected result:

- the benchmark file exists
- multiple record-count scenarios are present
- timing and memory metrics are present

## 10. Optional Ubuntu Server Validation

Use this only if the reviewer wants to validate persistent deployment on Ubuntu.

Bootstrap:

```bash
cd ~/market-intelligence
bash deploy/bootstrap_server.sh
source .venv/bin/activate
```

Configure `.env`, then:

```bash
python -m app.scraper.twscrape_setup
bash deploy/install_services.sh
bash deploy/install_cron.sh
sudo systemctl status market-intelligence-api --no-pager
sudo systemctl status market-intelligence-dashboard --no-pager
crontab -l
curl http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8501
```

If testing from another machine, ensure firewall or cloud security rules allow:

- TCP `8000`
- TCP `8501`

## 11. Common Failures

### `RuntimeError: No twscrape account is configured`

- `.env` is missing valid X auth fields
- rerun `python -m app.scraper.twscrape_setup` after fixing `.env`

### `No account available for queue "SearchTimeline"`

- the X account is currently rate-limited
- inspect:

```bash
python -m app.scraper.account_status
```

### `pymongo.errors.ServerSelectionTimeoutError`

- MongoDB is unreachable
- fix `MONGODB_URI`
- verify Atlas network access if using cloud MongoDB

### Dashboard does not open

- confirm the API is healthy:

```bash
curl http://127.0.0.1:8000/health
```

- confirm Streamlit is running on port `8501`

### SMTP authentication fails

- use a Gmail app password
- verify `SMTP_USERNAME`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`

### `address already in use`

- another process or `systemd` service is already bound to the port
- either stop the existing service or do not start a second manual process on the same port

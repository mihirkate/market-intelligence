# How To Install

This is the primary installation guide for a recruiter or reviewer running the project on their own machine.

The recommended path is:

- use a Python virtual environment
- use MongoDB locally or MongoDB Atlas
- use the same `venv`-based flow on both local machines and Ubuntu servers

The current live deployment referenced in the docs is hosted on AWS EC2.

## 1. Supported Setup

| Item | Recommended |
| --- | --- |
| OS | Ubuntu 22.04+/24.04+, macOS, or Windows with WSL2 |
| Python | 3.12 recommended |
| pip | current version inside `.venv` |
| Database | MongoDB Community or MongoDB Atlas |
| Live scraping | one valid X account/session |
| Monitoring email | optional Gmail app password |

Notes:

- The codebase has been exercised on Python `3.12` locally and on an Ubuntu server with Python `3.14`.
- The current public demo/server is hosted on AWS EC2.
- All Python package versions are pinned in [`requirements.txt`](requirements.txt).
- On a server, still use `.venv`; do not install project dependencies globally.

## 2. Clone The Repository

```bash
git clone <repo-url> market-intelligence
cd market-intelligence
```

If the repo is already present:

```bash
cd ~/market-intelligence
```

## 3. Create The Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

This is the recommended dependency isolation model for both local evaluation and Ubuntu server deployment.

## 4. Choose The Evaluation Mode

There are two practical paths for a reviewer.

### Option A: Code Validation Only

Use this if the reviewer wants to validate code quality, tests, and repository structure without configuring MongoDB or X credentials.

Run:

```bash
source .venv/bin/activate
pytest -q
python -m compileall app tests run.py dashboard
```

This is enough to verify:

- repository structure
- import correctness
- test coverage for core logic
- FastAPI/dashboard module entrypoints
- storage/reporting/monitoring logic at unit-test level

### Option B: Full Local Run

Use this if the reviewer wants the collector, API, dashboard, MongoDB storage, and reports running end to end.

This requires:

- a reachable MongoDB instance
- valid X auth for `twscrape`

## 5. Configure `.env`

Start from the checked-in template:

```bash
cp .env.example .env
```

For a local machine, the simplest setup is:

```dotenv
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DATABASE=market-intelligence
SCRAPER_ENGINE=twscrape
KEYWORD_CONCURRENCY=1
CRON_SCHEDULE=*/10 * * * *
DASHBOARD_AUTO_REFRESH_ENABLED=true
DASHBOARD_AUTO_REFRESH_SECONDS=30
```

For X authentication, fill one supported path:

### Path 1: `X_USERNAME` + `X_AUTH_TOKEN` + `X_CT0`

```dotenv
X_USERNAME=your_x_handle
X_AUTH_TOKEN=your_auth_token
X_CT0=your_ct0_token
```

### Path 2: `X_USERNAME` + `X_COOKIES`

```dotenv
X_USERNAME=your_x_handle
X_COOKIES='auth_token=...; ct0=...; ...'
```

### Path 3: Password-based login

```dotenv
X_USERNAME=your_x_handle
X_PASSWORD=your_x_password
X_EMAIL=your_email
X_EMAIL_PASSWORD=your_email_password
```

### Path 4: Multi-account setup

```dotenv
X_ACCOUNTS_JSON=[{"username":"acct_one","auth_token":"token-1","ct0":"ct0-1"},{"username":"acct_two","auth_token":"token-2","ct0":"ct0-2"}]
```

Important:

- use only one auth path unless you know exactly why you are mixing them
- `X_ACCOUNTS_JSON` is the preferred path if you want better scrape throughput
- do not commit real secrets into `.env`

## 6. MongoDB Requirement

For a full local run, the API and dashboard need MongoDB.

You can use either:

- local MongoDB Community Server on `mongodb://localhost:27017/`
- MongoDB Atlas via `MONGODB_URI=mongodb+srv://...`

The expected database name is:

```dotenv
MONGODB_DATABASE=market-intelligence
```

If MongoDB is unavailable, the API is expected to fail fast instead of starting in a partially broken state.

## 7. Bootstrap `twscrape`

Once `.env` is configured:

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
```

Expected result:

- `data/twscrape/accounts.db` is created
- the configured X account(s) are written into the local `twscrape` DB

Optional inspection:

```bash
python -m app.scraper.account_status
```

This prints account state and any current `SearchTimeline` lock/cooldown.

## 8. Run A Full Local Collection

```bash
source .venv/bin/activate
python -m app.scraper.manager
python -m app.scraper.collection_status
```

Expected outputs:

- raw fetched tweets: `data/raw/date=YYYY-MM-DD/`
- parquet tweets: `data/parquet/tweets/`
- parquet signals: `data/parquet/signals/`
- collection report: `reports/data_collection_status.json`
- processing report: `reports/processing_report.json`
- analysis report: `reports/analysis_summary.json`

The collector is designed as a bounded run, not an infinite process. Repeated runs or cron scheduling are expected.

## 9. Start The API And Dashboard

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

Verify:

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/stats
curl http://127.0.0.1:8000/dashboard-state
```

Open in the browser:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8501/`

If the current AWS-hosted public demo server is still online, the reviewer can also check:

- `http://13.60.241.241:8000/health`
- `http://13.60.241.241:8501/`

Note: this public IP is environment-specific and may change later.

Behavior note:

- the dashboard cards are rendered by Streamlit
- the page polls a lightweight DB-backed count endpoint
- the dashboard only reloads when `Stored Tweets` increases in MongoDB

## 10. Optional Monitoring Email Setup

If the reviewer wants to test watchdog and email reporting, add:

```dotenv
ALERT_EMAIL_TO=recipient@example.com
ALERT_EMAIL_FROM=sender@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=sender@example.com
SMTP_PASSWORD=your_gmail_app_password
SMTP_USE_TLS=true
WATCHDOG_SCHEDULE=*/2 * * * *
HEALTH_REPORT_SCHEDULE=0 * * * *
MONITOR_RESTART_SERVICES=true
MONITOR_REBOOT_ON_CRITICAL=false
```

Then run:

```bash
source .venv/bin/activate
python -m app.monitoring.watchdog_job
python -m app.monitoring.hourly_report_job
```

## 11. Ubuntu Server Deployment

Only use this section if the reviewer wants persistent deployment on Ubuntu.

### 11.1 Bootstrap The Host

```bash
cd ~/market-intelligence
bash deploy/bootstrap_server.sh
```

Then create or update `.env` in the project root and keep using the project `.venv`.

### 11.2 Prepare Runtime Config

At minimum, confirm:

```dotenv
API_HOST=0.0.0.0
API_PORT=8000
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8501
MONGODB_URI=...
MONGODB_DATABASE=market-intelligence
```

And configure live scrape auth as described earlier.

### 11.3 Bootstrap `twscrape`

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
```

### 11.4 Install Persistent Services

```bash
bash deploy/install_services.sh
```

This installs:

- `market-intelligence-api.service`
- `market-intelligence-dashboard.service`

### 11.5 Install Scheduled Jobs

```bash
bash deploy/install_cron.sh
```

This installs one managed cron block for:

- the short-lived scraper run
- the watchdog job
- the health-report email job

### 11.6 Open Network Ports

For a public server, allow inbound TCP:

- `8000`
- `8501`

If using AWS EC2, these must be opened in the instance security group. If `ufw` is enabled, allow the ports there too.

### 11.7 Verify The Deployed Services

```bash
sudo systemctl status market-intelligence-api --no-pager
sudo systemctl status market-intelligence-dashboard --no-pager
python -m app.scraper.collection_status
curl http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8501
crontab -l
```

If the host has a public IP:

- API: `http://<public-ip>:8000/`
- dashboard: `http://<public-ip>:8501/`

## 12. Recommended Reviewer Flow

If the reviewer has limited time, use this order:

1. `pytest -q`
2. `python -m compileall app tests run.py dashboard`
3. inspect `README.md`, `how_to_install.md`, and `tests/HowToTest.md`
4. if MongoDB and X credentials are available, run `python -m app.scraper.manager`
5. start the API and dashboard
6. inspect `reports/data_collection_status.json` and the dashboard

## 13. Common Setup Failures

### `RuntimeError: No twscrape account is configured`

- `.env` does not contain a valid X auth path
- fill one supported auth combination and rerun `python -m app.scraper.twscrape_setup`

### `No account available for queue "SearchTimeline"`

- the current X account is rate-limited
- inspect:

```bash
python -m app.scraper.account_status
```

- wait for the lock to expire or add more accounts

### `pymongo.errors.ServerSelectionTimeoutError`

- MongoDB is unreachable
- fix `MONGODB_URI`
- for Atlas, verify credentials and IP/network access

### API starts but dashboard does not

- make sure MongoDB is reachable
- verify:

```bash
curl http://127.0.0.1:8000/health
```

- then restart Streamlit

### No email is sent

- use a Gmail app password, not the normal Gmail password
- verify `SMTP_USERNAME`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`
- inspect:

```bash
tail -n 100 logs/watchdog.log
tail -n 100 logs/health-report.log
```

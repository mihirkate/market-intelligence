# How To Install

This guide installs the current `market-intelligence` project on a local machine
or an Ubuntu server.

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

- `MAX_TWEETS_PER_RUN=50`
- `DISCOVERY_LIMIT_PER_KEYWORD=20`
- `CRON_SCHEDULE=*/10 * * * *`

Bootstrap the local `twscrape` account database:

```bash
python -m app.scraper.twscrape_setup
```

## 4. Run Locally

Start the API:

```bash
source .venv/bin/activate
python run.py
```

In another terminal, start the dashboard:

```bash
cd ~/market-intelligence
source .venv/bin/activate
streamlit run dashboard/main.py
```

Useful checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/stats
python -m app.scraper.account_status
python -m app.scraper.collection_status
```

## 5. Ubuntu Server Installation

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
- `MONGODB_URI=...`
- valid X auth values

Bootstrap `twscrape`:

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
```

Install the API and dashboard as `systemd` services:

```bash
bash deploy/install_services.sh
```

Install the scheduled scraper cron job:

```bash
bash deploy/install_cron.sh
```

Run a live check:

```bash
bash deploy/check_live.sh
```

## 6. Service Management

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

## 7. Cron Verification

Check the installed cron entry:

```bash
crontab -l
python -m app.scheduler.cron status
```

The scraper runs as a short-lived job and should:

- respect cooldowns
- skip overlapping runs
- update `reports/data_collection_status.json`

## 8. Public Access

If you expose the app directly by server IP:

- API: `http://SERVER_IP:8000/health`
- Dashboard: `http://SERVER_IP:8501`

On AWS, allow inbound traffic for:

- `8000`
- `8501`

## 9. Files To Watch

- `logs/app.log`
- `logs/cron.log`
- `reports/data_collection_status.json`
- `reports/processing_report.json`
- `reports/analysis_summary.json`
- `reports/performance_benchmark.json`

## 10. Completion Check

The data-collection requirement is complete only when:

- `reports/data_collection_status.json` shows
  `assignment_data_collection_ready: true`
- `total_unique_tweets_last_24_hours >= 2000`

## 11. Common Problems

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

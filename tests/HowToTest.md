# How To Test

This repo now uses `twscrape` only. The old Playwright/browser scraping path
has been removed.

## 1. Install Dependencies

```bash
cd /home/mihir/market-intelligence
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure `.env`

Fill one supported X authentication path in `.env`:

- `X_ACCOUNTS_JSON` with one or more accounts
- `X_USERNAME` + `X_COOKIES`
- `X_USERNAME` + `X_AUTH_TOKEN` + `X_CT0`
- `X_USERNAME` + `X_PASSWORD` + `X_EMAIL` + `X_EMAIL_PASSWORD`

Recommended live-run settings:

- `LOOKBACK_HOURS=24`
- `SEARCH_FETCH_MULTIPLIER=3`
- `SEARCH_RETRY_ATTEMPTS=3`
- `SEARCH_RETRY_BASE_SECONDS=2`
- `SEARCH_RETRY_MAX_SECONDS=20`
- `TWSCRAPE_WAIT_TIMEOUT=30`
- `TWSCRAPE_WAIT_INTERVAL=1`
- `MAX_TWEETS_PER_RUN=30` to `50`
- `RUN_STARTUP_JITTER_MIN_SECONDS=0`
- `RUN_STARTUP_JITTER_MAX_SECONDS=120`
- `RATE_LIMIT_COOLDOWN_MIN_SECONDS=1800`
- `RATE_LIMIT_COOLDOWN_MAX_SECONDS=3600`
- `COLLECTION_TARGET_TWEETS_LAST_24_HOURS=2000`
- `COLLECTION_PROGRESS_RECENT_RUN_HOURS=6`
- `COLLECTION_STATUS_REPORT_PATH=reports/data_collection_status.json`
- `DEBUG_ARTIFACTS_PATH=data/raw/debug`
- `MONGODB_URI=mongodb+srv://...` for shared or deployed environments

If all account fields are blank, `python -m app.scraper.twscrape_setup` will fail.

Example multi-account value:

```dotenv
X_ACCOUNTS_JSON=[{"username":"acct_one","auth_token":"token-1","ct0":"ct0-1"},{"username":"acct_two","auth_token":"token-2","ct0":"ct0-2"}]
```

## 3. Bootstrap The Local Account DB

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
```

Expected result:

- `data/twscrape/accounts.db` is created
- the command logs that account bootstrap completed

Optional inspection:

```bash
source .venv/bin/activate
python -m app.scraper.account_status
```

Expected result:

- JSON is printed with each configured account
- `locks.SearchTimeline` shows the current X search lock, if any
- `remaining_seconds` tells you how long before that account can search again

## 4. Run The Scraper

```bash
source .venv/bin/activate
python -m app.scraper.manager
```

Expected result:

- tweets are stored in the MongoDB database `market-intelligence`
- raw fetched tweets are archived under `data/raw/date=YYYY-MM-DD/`
- new unique tweets are exported under `data/parquet/tweets/`
- keyword signals are exported under `data/parquet/signals/`
- checkpoint state is written to `data/raw/checkpoint.json`
- search failures are written to `data/raw/debug/`
- collection progress is written to `reports/data_collection_status.json`
- `logs/app.log` records the run
- rerunning the scraper does not stop just because a previous run hit its target

Recommended assignment pattern:

- run `python -m app.scraper.manager`
- let it collect a small bounded batch
- let it exit
- trigger it again with cron every 10 to 15 minutes

Example cron line:

```bash
source .venv/bin/activate
python -m app.scheduler.cron render
python -m app.scheduler.cron install
python -m app.scheduler.cron status
```

If the checkpoint contains an active `cooldown_until`, the manager should skip
the run cleanly instead of failing.

Expected result:

- `render` prints one managed cron block
- `install` adds or replaces that block in the current user's crontab
- `status` prints `installed`
- cron executes `python -m app.scheduler.job`, not `app.scraper.manager`
- overlapping cron runs are skipped because `CRON_LOCK_PATH` is lock-protected

To inspect progress manually at any time:

```bash
source .venv/bin/activate
python -m app.scraper.collection_status
```

Expected result:

- `reports/data_collection_status.json` is updated
- the report shows total unique tweets in the last 24 hours
- the report shows the gap remaining to 2,000
- the report shows whether all required keywords are being covered
- the report shows recent tweets/hour so you can judge if cron cadence is sufficient
- the report shows required tweets/hour and estimated hours to target

## 5. Run The Test Suite

```bash
source .venv/bin/activate
pytest -q
python -m compileall app tests run.py dashboard
```

## 6. Generate Analysis And Performance Reports

```bash
source .venv/bin/activate
python -m app.reporting.performance
```

Expected result:

- `reports/performance_benchmark.json` is created
- it contains multiple scenarios with increasing `record_count`
- it contains `peak_memory_mb` and `records_per_second_total`

The scraper manager should also keep these updated after successful runs:

- `reports/processing_report.json`
- `reports/analysis_summary.json`

## 7. Verify API Health

```bash
source .venv/bin/activate
python run.py
```

Then in another terminal:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/stats
curl http://127.0.0.1:8000/analysis-summary
curl http://127.0.0.1:8000/performance-benchmark
```

Expected result:

- `/health` returns `status=running` plus MongoDB connection details
- `/stats` returns dashboard overview and live collection progress
- `/analysis-summary` returns latest signals, top influencers, and hourly volume
- `/performance-benchmark` returns the saved benchmark report or `status=not-generated`
- if MongoDB is unreachable, startup should fail fast instead of serving a broken API

## 8. Common Failures

`RuntimeError: No twscrape account bootstrap data was found in .env`

- `.env` is missing account auth values or `X_ACCOUNTS_JSON` is invalid JSON
- fill one supported auth combination and rerun setup

`RuntimeError: No tweets returned for keyword: ...`

- the account was bootstrapped, but the search returned nothing for that keyword
- try a broader keyword or verify the X account can search normally

`No account available for queue SearchTimeline`

- the X account is rate-limited for search
- the manager should now store `cooldown_until` in `data/raw/checkpoint.json`
- the current run should exit cleanly with status `cooldown`
- the next cron execution should skip until the cooldown expires
- wait for the X rate limit window to reset or add more accounts
- run `python -m app.scraper.account_status` to inspect account locks
- inspect `data/raw/debug/` for the captured failure artifact
- tune `TWSCRAPE_WAIT_TIMEOUT` if you want faster failure instead of waiting

MongoDB or account DB issues

- delete `data/twscrape/accounts.db`
- rerun `python -m app.scraper.twscrape_setup`
- confirm `MONGODB_URI` points to a reachable local or cloud MongoDB instance
- for Atlas, confirm the cluster network access rules and credentials are valid
- if Atlas TLS handshakes fail in one environment, test the same URI from the deployment server directly
- if `python -m app.scheduler.cron status` says the `crontab` command is not installed, install the OS cron package on the deployment host first

Warehouse or parquet issues

- drop the `market-intelligence` database only if you want a full reset
- remove `data/parquet/tweets/` and `data/parquet/signals/` if you want to regenerate analytics exports

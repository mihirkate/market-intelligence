# Market Intelligence

Production-oriented submission for the real-time market intelligence assignment.

## Components

- FastAPI backend with health and stats endpoints
- Streamlit dashboard backed by MongoDB metrics
- Centralized configuration loaded from `.env`
- Shared file logging at `logs/app.log`
- `twscrape`-based X collector
- MongoDB operational warehouse with deduplicating upserts
- Partitioned parquet exports for tweets and keyword signals
- Unicode-safe normalization plus text-to-signal analytics
- JSON reports for collection progress, processing health, and analysis summaries
- Built-in performance benchmark for 1x to 10x style scale checks

## Run Locally

```bash
source .venv/bin/activate
python run.py
```

In another terminal:

```bash
source .venv/bin/activate
streamlit run dashboard/main.py
```

The dashboard auto-refreshes by default every `30` seconds so live collection
counts, tables, and charts update without manual browser reloads.

## Docker

```bash
docker compose up --build
```

The runtime now expects a real MongoDB deployment via `MONGODB_URI`. For
shared environments, keep secrets in `.env` locally and use [.env.example](/home/mihir/market-intelligence/.env.example)
as the checked-in template.

For Ubuntu server deployment with `systemd` and `cron`, see
[deploy/README.md](/home/mihir/market-intelligence/deploy/README.md).

The persistent deployment model is:

- `systemd` runs the FastAPI API
- `systemd` runs the Streamlit dashboard
- `cron` runs only the short-lived scraper job

That means:

- `uvicorn app.api.main:app --host 0.0.0.0 --port 8000` should be owned by `systemd`
- `streamlit run dashboard/main.py --server.address 0.0.0.0 --server.port 8501` should be owned by `systemd`
- only the collector should run from `cron`

The cron-managed background jobs now include:

- the bounded scraper run
- a watchdog that checks the API/dashboard and attempts recovery
- an hourly health email job

## Scraper Engine

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
python -m app.scraper.account_status
python -m app.scraper.collection_status
python -m app.scraper.manager
python -m app.scheduler.cron render
```

The scraper runtime is configured entirely through `.env`, including the
account DB path, keyword limits, MongoDB connection, parquet paths,
lookback window, retry behavior, cron-friendly per-run limits, cooldowns,
report output paths, and dashboard sampling limits.

## API

The backend now exposes:

- `GET /` basic status
- `GET /health` service and MongoDB health
- `GET /stats` dashboard overview plus live collection progress
- `GET /collection-status` current 24-hour collection progress snapshot
- `GET /analysis-summary` current signal, influencer, and hourly-volume snapshot
- `GET /performance-benchmark` last saved benchmark report

## Storage And Processing

Each scrape run now:

- behaves as a short-lived cron job instead of a long-running worker
- applies optional startup jitter before hitting X
- enforces a strict rolling `LOOKBACK_HOURS` window after fetch
- caps each invocation to `MAX_TWEETS_PER_RUN`
- archives raw fetched tweet records as JSONL under `data/raw/date=YYYY-MM-DD/`
- fetches all configured keywords again instead of stopping at the previous run's total
- normalizes Unicode text with Indian-language-safe cleanup
- computes compact hashed TF-IDF vectors plus custom market text features
- upserts tweets into the MongoDB database `market-intelligence`
- appends new unique tweets to `data/parquet/tweets/`
- writes aggregated keyword signals to `data/parquet/signals/`
- writes a collection progress report to `reports/data_collection_status.json`
- writes a run-level processing report to `reports/processing_report.json`
- writes an analysis summary to `reports/analysis_summary.json`

The checkpoint file at `data/raw/checkpoint.json` is now run metadata only. It
no longer prevents fresh collection on later runs. Search failures and live-run
artifacts are written to `data/raw/debug/`. When the account is rate-limited,
the manager stores `cooldown_until` in the checkpoint and exits cleanly so the
next cron run can skip or resume automatically. The collection status report
tracks current progress toward the 2,000-tweet assignment target over the last
24 hours.

## Twscrape Account Setup

Set `SCRAPER_ENGINE=twscrape` and provide either:

- `X_ACCOUNTS_JSON` with one or more accounts, or
- `X_USERNAME` plus `X_COOKIES`, or
- `X_USERNAME`, `X_AUTH_TOKEN`, and `X_CT0`, or
- `X_USERNAME`, `X_PASSWORD`, `X_EMAIL`, and `X_EMAIL_PASSWORD`

Then bootstrap the local `twscrape` account database:

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
```

By default this writes account state into `data/twscrape/accounts.db`.

Example `.env` values for a live retry:

```dotenv
SCRAPER_ENGINE=twscrape
TWSCRAPE_ACCOUNTS_DB=data/twscrape/accounts.db
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DATABASE=market-intelligence
PARQUET_TWEETS_PATH=data/parquet/tweets
PARQUET_SIGNALS_PATH=data/parquet/signals
LOOKBACK_HOURS=24
SEARCH_FETCH_MULTIPLIER=3
SEARCH_RETRY_ATTEMPTS=3
SEARCH_RETRY_BASE_SECONDS=2
SEARCH_RETRY_MAX_SECONDS=20
TWSCRAPE_WAIT_TIMEOUT=30
TWSCRAPE_WAIT_INTERVAL=1
MAX_TWEETS_PER_RUN=40
RUN_STARTUP_JITTER_MIN_SECONDS=0
RUN_STARTUP_JITTER_MAX_SECONDS=120
RATE_LIMIT_COOLDOWN_MIN_SECONDS=1800
RATE_LIMIT_COOLDOWN_MAX_SECONDS=3600
COLLECTION_TARGET_TWEETS_LAST_24_HOURS=2000
COLLECTION_PROGRESS_RECENT_RUN_HOURS=6
COLLECTION_STATUS_REPORT_PATH=reports/data_collection_status.json
DEBUG_ARTIFACTS_PATH=data/raw/debug
X_USERNAME=your_x_handle
X_AUTH_TOKEN=your_auth_token
X_CT0=your_ct0_token
```

For a single-account server deployment, start with:

```dotenv
KEYWORD_CONCURRENCY=1
CRON_SCHEDULE=*/5 * * * *
MAX_TWEETS_PER_RUN=60
DISCOVERY_LIMIT_PER_KEYWORD=25
RATE_LIMIT_COOLDOWN_MIN_SECONDS=900
RATE_LIMIT_COOLDOWN_MAX_SECONDS=1800
```

For longer runs, prefer multiple accounts so twscrape can rotate when
`SearchTimeline` locks one account. `X_ACCOUNTS_JSON` accepts a JSON array:

```dotenv
X_ACCOUNTS_JSON=[{"username":"acct_one","auth_token":"token-1","ct0":"ct0-1"},{"username":"acct_two","auth_token":"token-2","ct0":"ct0-2"}]
```

After bootstrap, inspect the pool and current queue locks:

```bash
source .venv/bin/activate
python -m app.scraper.account_status
```

For Atlas or another remote deployment, set `MONGODB_URI` to your external
connection string outside source control and keep `MONGODB_DATABASE` as
`market-intelligence`.

If MongoDB startup health fails, the API now fails fast instead of serving a
partially broken application. That is intentional for deployment.

If `python -m app.scraper.twscrape_setup` fails, the current `.env` is usually
missing all account auth fields or contains invalid `X_ACCOUNTS_JSON`. The
setup command only seeds the local `data/twscrape/accounts.db` from values
already present in `.env`.

If `python -m app.scraper.manager` fails with `No account available for queue SearchTimeline`,
the configured account is rate-limited. The run now fails fast after
`TWSCRAPE_WAIT_TIMEOUT` seconds and writes a debug artifact instead of hanging
indefinitely. Run `python -m app.scraper.account_status` to see which account
is locked and for how long.

## Reports And Benchmarks

Generate the current collection and analysis snapshots:

```bash
source .venv/bin/activate
python -m app.scraper.collection_status
```

Run the benchmark that measures processing, storage, and parquet export at
multiple batch sizes:

```bash
source .venv/bin/activate
python -m app.reporting.performance
```

Useful artifacts:

- `reports/data_collection_status.json`
- `reports/processing_report.json`
- `reports/analysis_summary.json`
- `reports/performance_benchmark.json`

Supporting notes:

- [architecture.md](/home/mihir/market-intelligence/docs/architecture.md)
- [scaling.md](/home/mihir/market-intelligence/docs/scaling.md)

## Cron Deployment

The manager is designed to run as a short-lived job. Each invocation:

- loads the checkpoint
- skips immediately if `cooldown_until` is still active
- applies a small randomized startup delay
- fetches a bounded batch up to `MAX_TWEETS_PER_RUN`
- stores raw JSONL, MongoDB rows, parquet rows, and keyword signals
- updates the checkpoint and exits

Example cron entry for a server deployment:

```bash
source .venv/bin/activate
python -m app.scheduler.cron render
```

To install the managed cron block for the current user on the deployment host:

```bash
source .venv/bin/activate
python -m app.scheduler.cron install
python -m app.scheduler.cron status
```

The installed cron entry runs `python -m app.scheduler.job`, which uses a
filesystem lock at `CRON_LOCK_PATH` so overlapping cron invocations are skipped
cleanly instead of double-scraping. That pattern is a better fit for the
assignment than trying to scrape 2,000 tweets in one process lifetime. After
each run, check
`reports/data_collection_status.json` or run `python -m app.scraper.collection_status`
to see:

- unique tweets collected in the last 24 hours
- remaining tweets to reach 2,000
- required keyword coverage
- recent tweets/hour and projected 24-hour throughput
- required tweets/hour to hit the assignment target
- estimated hours remaining at the current recent pace
- active cooldown state from the checkpoint

## Deployment Notes

- `.env` is now ignored and should not be committed with live secrets
- use [.env.example](/home/mihir/market-intelligence/.env.example) as the template for new environments
- `.dockerignore` excludes `.env`, local data, logs, and virtualenv files from the image build context
- `bash scripts/prepare_submission.sh` removes generated runtime artifacts before GitHub submission
- `docker compose up --build` now runs with restart policies and an API healthcheck
- the API and dashboard are configured for a remote MongoDB deployment rather than a local-only Mongo instance
- for MongoDB Atlas, the deployment host must be allowed in Atlas network access rules and able to complete TLS handshakes to the cluster
- if Atlas is unreachable, the API exits on startup by design so a broken deployment does not look healthy
- for cron-managed collection, the deployment host must have the `crontab` command installed; on Ubuntu that usually means installing the `cron` package

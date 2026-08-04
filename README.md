# Market Intelligence

Skeleton for the real-time market intelligence assignment.

## Components

- FastAPI backend with a health endpoint
- Streamlit dashboard backed by warehouse metrics
- Centralized configuration loaded from `.env`
- Shared file logging at `logs/app.log`
- `twscrape`-based X collector
- MongoDB operational warehouse with deduplicating upserts
- Partitioned parquet exports for tweets and keyword signals
- Unicode-safe normalization plus text-to-signal analytics

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

## Docker

```bash
docker compose up --build
```

## Scraper Engine

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
python -m app.scraper.account_status
python -m app.scraper.manager
```

The scraper runtime is configured entirely through `.env`, including the
account DB path, keyword limits, MongoDB connection, parquet paths,
lookback window, retry behavior, and dashboard sampling limits.

## Storage And Processing

Each scrape run now:

- enforces a strict rolling `LOOKBACK_HOURS` window after fetch
- archives raw fetched tweet records as JSONL under `data/raw/date=YYYY-MM-DD/`
- fetches all configured keywords again instead of stopping at the previous run's total
- normalizes Unicode text with Indian-language-safe cleanup
- computes compact hashed TF-IDF vectors plus custom market text features
- upserts tweets into the MongoDB database `market-intelligence`
- appends new unique tweets to `data/parquet/tweets/`
- writes aggregated keyword signals to `data/parquet/signals/`

The checkpoint file at `data/raw/checkpoint.json` is now run metadata only. It
no longer prevents fresh collection on later runs. Search failures and live-run
artifacts are written to `data/raw/debug/`.

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
DEBUG_ARTIFACTS_PATH=data/raw/debug
X_USERNAME=your_x_handle
X_AUTH_TOKEN=your_auth_token
X_CT0=your_ct0_token
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

If `python -m app.scraper.twscrape_setup` fails, the current `.env` is usually
missing all account auth fields or contains invalid `X_ACCOUNTS_JSON`. The
setup command only seeds the local `data/twscrape/accounts.db` from values
already present in `.env`.

If `python -m app.scraper.manager` fails with `No account available for queue SearchTimeline`,
the configured account is rate-limited. The run now fails fast after
`TWSCRAPE_WAIT_TIMEOUT` seconds and writes a debug artifact instead of hanging
indefinitely. Run `python -m app.scraper.account_status` to see which account
is locked and for how long.

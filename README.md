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
python -m app.scraper.manager
```

The scraper runtime is configured entirely through `.env`, including the
account DB path, keyword limits, MongoDB connection, parquet paths, and
dashboard sampling limits.

## Storage And Processing

Each scrape run now:

- fetches all configured keywords again instead of stopping at the previous run's total
- normalizes Unicode text with Indian-language-safe cleanup
- computes compact hashed TF-IDF vectors plus custom market text features
- upserts tweets into the MongoDB database `market-intelligence`
- appends new unique tweets to `data/parquet/tweets/`
- writes aggregated keyword signals to `data/parquet/signals/`

The checkpoint file at `data/raw/checkpoint.json` is now run metadata only. It
no longer prevents fresh collection on later runs.

## Twscrape Account Setup

Set `SCRAPER_ENGINE=twscrape` and provide either:

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
X_USERNAME=your_x_handle
X_AUTH_TOKEN=your_auth_token
X_CT0=your_ct0_token
```

For Atlas or another remote deployment, set `MONGODB_URI` to your external
connection string outside source control and keep `MONGODB_DATABASE` as
`market-intelligence`.

If `python -m app.scraper.twscrape_setup` fails, the current `.env` is usually
missing all `X_*` auth fields. The setup command only seeds the local
`data/twscrape/accounts.db` from values already present in `.env`.

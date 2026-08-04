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
- `DEBUG_ARTIFACTS_PATH=data/raw/debug`

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
- `logs/app.log` records the run
- rerunning the scraper does not stop just because a previous run hit its target

## 5. Run The Test Suite

```bash
source .venv/bin/activate
pytest -q
python -m compileall app tests run.py dashboard
```

## 6. Common Failures

`RuntimeError: No twscrape account bootstrap data was found in .env`

- `.env` is missing account auth values or `X_ACCOUNTS_JSON` is invalid JSON
- fill one supported auth combination and rerun setup

`RuntimeError: No tweets returned for keyword: ...`

- the account was bootstrapped, but the search returned nothing for that keyword
- try a broader keyword or verify the X account can search normally

`No account available for queue SearchTimeline`

- the X account is rate-limited for search
- wait for the X rate limit window to reset or add more accounts
- run `python -m app.scraper.account_status` to inspect account locks
- inspect `data/raw/debug/` for the captured failure artifact
- tune `TWSCRAPE_WAIT_TIMEOUT` if you want faster failure instead of waiting

MongoDB or account DB issues

- delete `data/twscrape/accounts.db`
- rerun `python -m app.scraper.twscrape_setup`
- confirm `MONGODB_URI` points to a reachable local or cloud MongoDB instance

Warehouse or parquet issues

- drop the `market-intelligence` database only if you want a full reset
- remove `data/parquet/tweets/` and `data/parquet/signals/` if you want to regenerate analytics exports

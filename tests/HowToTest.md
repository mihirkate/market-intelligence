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

- `X_USERNAME` + `X_COOKIES`
- `X_USERNAME` + `X_AUTH_TOKEN` + `X_CT0`
- `X_USERNAME` + `X_PASSWORD` + `X_EMAIL` + `X_EMAIL_PASSWORD`

If all `X_*` values are blank, `python -m app.scraper.twscrape_setup` will fail.

## 3. Bootstrap The Local Account DB

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
```

Expected result:

- `data/twscrape/accounts.db` is created
- the command logs that account bootstrap completed

## 4. Run The Scraper

```bash
source .venv/bin/activate
python -m app.scraper.manager
```

Expected result:

- tweets are stored in the MongoDB database `market-intelligence`
- new unique tweets are exported under `data/parquet/tweets/`
- keyword signals are exported under `data/parquet/signals/`
- checkpoint state is written to `data/raw/checkpoint.json`
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

- `.env` is missing the required `X_*` auth values
- fill one supported auth combination and rerun setup

`RuntimeError: No tweets returned for keyword: ...`

- the account was bootstrapped, but the search returned nothing for that keyword
- try a broader keyword or verify the X account can search normally

MongoDB or account DB issues

- delete `data/twscrape/accounts.db`
- rerun `python -m app.scraper.twscrape_setup`
- confirm `MONGODB_URI` points to a reachable local or cloud MongoDB instance

Warehouse or parquet issues

- drop the `market-intelligence` database only if you want a full reset
- remove `data/parquet/tweets/` and `data/parquet/signals/` if you want to regenerate analytics exports

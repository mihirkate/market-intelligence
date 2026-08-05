# Submission Checklist

Use this checklist before pushing the assignment repository.

## 1. Secrets

- Keep live credentials only in local `.env`.
- Do not commit `.env`, `.pem`, `.key`, or certificate files.
- Confirm `.env.example` contains placeholders only.
- Rotate any secret that was ever pasted into chat, logs, or screenshots.

## 2. Runtime Cleanup

Run:

```bash
bash scripts/prepare_submission.sh
```

Then verify:

- `logs/` contains no live runtime logs
- `data/raw/` contains no real tweet dumps, checkpoints, or debug artifacts
- `data/twscrape/` contains no local account database
- `reports/*.json` were removed from the working tree

## 3. Submission Artifacts

Add only sanitized examples you want reviewers to see:

- a small sample parquet export
- a small sample analysis result
- screenshots of the API/dashboard if useful

Do not include:

- live account cookies or tokens
- raw full-volume tweet archives
- anything tied to your private server state

## 4. Final Verification

Run:

```bash
source .venv/bin/activate
pytest -q
python -m compileall app tests run.py dashboard
```

Check:

- `git status`
- `README.md`
- `how_to_install.md`
- `docs/architecture.md`
- `docs/scaling.md`

## 5. Assignment Readiness

Before claiming full completion, verify:

- `reports/data_collection_status.json` reached the assignment target during live collection
- the dashboard and API are reachable on the deployment host
- the cron-managed scraper is running reliably
- the repo contains only sanitized submission artifacts

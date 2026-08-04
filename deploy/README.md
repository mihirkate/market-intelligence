# Ubuntu Deployment

This project is designed to run on Ubuntu with:

- `systemd` for the FastAPI API
- `systemd` for the Streamlit dashboard
- `cron` for the scheduled scraper job

## Quick Start

From the project root on the server:

```bash
bash deploy/bootstrap_server.sh
cp .env.example .env
```

Edit `.env`, then run:

```bash
source .venv/bin/activate
python -m app.scraper.twscrape_setup
bash deploy/install_services.sh
bash deploy/install_cron.sh
bash deploy/check_live.sh
```

## Public Access

If you are exposing the app directly by public IP:

- API: `http://SERVER_IP:8000/health`
- Dashboard: `http://SERVER_IP:8501`

On AWS, the instance security group must allow inbound TCP:

- `8000`
- `8501`

If you later add Nginx, you can front both services with `80/443`.

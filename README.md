# Infivita PharmaConnect

Distributor consignment pharma platform — GST billing, live stock, purchases, MargBooks-style ERP.

**GSTIN (demo):** `36AHEPD1696A4Z0` · Telangana state code `36`

## Quick start (local)

```powershell
cd pharma-connect
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
$env:PYTHONPATH="."
.\.venv\Scripts\flask seed          # optional: reset demo data
.\.venv\Scripts\python app.py       # http://localhost:5000
```

## Demo logins

| Username | Password | Role | Organization |
|----------|----------|------|----------------|
| `distributor` | `admin` | Distributor Admin | Infivita HQ |
| `retail_admin` | `admin` | Facility Admin | Secunderabad retail |
| `retail1` | `admin` | Cashier | Secunderabad retail |
| `hospital1` | `admin` | Facility Admin | Gachibowli hospital |

**Cashiers** can bill, manage customers, and view stock. **Admins** can manage purchases, accounting, integrations, and team users.

## Tests

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python -m pytest tests/ -q
```

**CI:** GitHub Actions runs `pytest` and `docker build` on push/PR to `main` (see `.github/workflows/ci.yml`).

### Push to GitHub (`main`)

```powershell
cd C:\Users\Akhil\Documents\GitHub\pharma-connect
git init -b main
git add .
git commit -m "Infivita PharmaConnect — v17 cashier dashboard + CI"
git remote add origin https://github.com/<your-user>/pharma-connect.git
git push -u origin main
```

Create the repo on GitHub first (empty, default branch **main**). CI runs automatically on the first push.

## Docker deploy

### SQLite (default, single-node demo)

```powershell
copy .env.example .env
# Edit PHARMACONNECT_SECRET and PHARMACONNECT_CRON_SECRET

docker compose up --build
```

### PostgreSQL (production)

```powershell
copy .env.example .env
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

Uses `postgres:16-alpine`, auto-seeds on first boot, and enables connection pooling.

- **Web:** http://localhost:5000
- **Health:** `GET /api/health`
- **Readiness:** `GET /api/ready`
- **Cron sidecar:** runs `flask run-alerts` on each hour boundary (respects `alert_schedule_hour` in Integrations)
- **Audit export:** `GET /settings/audit/export.csv` (admin login required)

### Environment variables

| Variable | Purpose |
|----------|---------|
| `PHARMACONNECT_SECRET` | Flask session secret |
| `PHARMACONNECT_DB` | SQLAlchemy URI — SQLite or `postgresql+psycopg://user:pass@host:5432/db` |
| `PHARMACONNECT_CRON_SECRET` | Secret for `POST /api/cron/alerts` |

## Backup & restore (SQLite)

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\flask backup-db
.\.venv\Scripts\flask backup-db --out D:\backups

.\.venv\Scripts\flask restore-db backups\pharmaconnect_20260611_120000.db --yes
```

Restore keeps a safety copy of the live DB (`*.pre_restore_*`) unless `--no-safety-copy` is passed.

For **PostgreSQL**, use `pg_dump` / `pg_restore` instead of `flask backup-db`.

## Scheduled SMS alerts

1. Enable SMS + **Daily scheduled SMS** in **Integrations** (set hour 0–23, server local time).
2. Run manually: `flask run-alerts` or `flask run-alerts --force`
3. Or trigger via API:

```http
POST /api/cron/alerts
X-Cron-Secret: <PHARMACONNECT_CRON_SECRET>
```

## Project layout

- `app.py` / `wsgi.py` — entrypoints
- `pharmaconnect/` — app package (routes, models, services)
- `tests/` — pytest suite (`test_v3` … `test_v15`, core, backlog)
- `scripts/run_alerts_loop.sh` — hourly cron helper for Docker
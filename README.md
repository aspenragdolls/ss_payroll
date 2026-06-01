# ss_payroll

Python payroll and accounting web app for window cleaning businesses.

## Features

- Multi-tenant accounts (each user is a separate business)
- Worker profiles with **labor** and **sales** roles (configured in profile management only)
- Mixed hourly/percentage pay with **daily hours** split across jobs
- 20% commission pool (defaults to owner when no salesman assigned)
- Apple Calendar import + OpenRouter AI job parsing (with local fallback)
- Immutable finalized payroll records with calculation snapshots

## Stack

- FastAPI + Jinja2 + HTMX
- PostgreSQL (Neon recommended)
- SQLAlchemy 2 + Alembic
- Pure Python payroll calculator (`app/domain/payroll_calculator.py`)

## Setup

### 1. Neon PostgreSQL

1. Create a project at [neon.tech](https://neon.tech)
2. Copy the connection string (include `?sslmode=require`)
3. Create `.env` from `.env.example` and set `DATABASE_URL`

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run migrations

```bash
alembic upgrade head
```

### 4. Configure OpenRouter (optional)

Set in `.env`:

```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
```

Without an API key, calendar events are parsed locally using regex fallback.

### 5. Start the server

```bash
uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000` and register your business account.

## Payroll flow

1. Manage worker profiles (`/workers`) — set labor/sales roles and pay defaults
2. Connect Apple calendar (`/settings/calendar`)
3. Begin payroll → import jobs from the selected date (or add manually) → review drafts
4. Assign laborers and salesmen per job (filtered by profile roles)
5. Enter total daily hours for hourly workers
6. Calculate → review warnings → finalize

## Testing

```bash
python -m pytest -v
```

Calculator unit tests cover all required edge cases (commission-only, mixed pay, daily hours split, rounding, etc.).

## Environment variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (Neon) |
| `SECRET_KEY` | Session signing key |
| `OPENROUTER_API_KEY` | OpenRouter API key (optional) |
| `OPENROUTER_MODEL` | Model slug for job parsing |

Never commit `.env` or API keys.

# Fuel Supply Intelligence & Resilience Platform

**BUP CSE Fest 2026 Hackathon Finals** (with Poridhi.io) — decision-support platform over the organizer-provided fuel supply simulator. Observe → Detect → Predict → Decide → Act → Monitor → Recover.

## Run it (3 commands)

```bash
cp .env.example .env
docker compose up --build
```

Then:

| Service | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| Backend API | http://localhost:8080 |
| API health | http://localhost:8080/health |
| Metrics | http://localhost:8080/metrics |
| Simulator | http://localhost:8000 (docs at `/docs`) |

`docker compose up` starts: `db` (Postgres 16), `redis`, `simulator` (organizer image), `api` (FastAPI + in-process collector), `web` (Next.js dashboard).

## Layout

```
backend/          FastAPI + collector + intelligence (forecast, optimizer)
web/              Next.js operator dashboard
mock_simulator/   Offline stub of the simulator's /v1/* for dev/tests
docs/             PRD, TRD, ERD, flows — start at DOCS/README.md
```

## Docs

Read in this order: `DOCS/README.md` → `DOCS/PRD.md` → `DOCS/TRD.md` → `DOCS/SystemArchitecture.md`.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
.venv/bin/python backend/tests/test_skeletons.py       # client/forecast/LP units
.venv/bin/python backend/tests/test_db_persistence.py  # DB + collector integration
```

Without Docker, run the mock simulator for offline dev:

```bash
.venv/bin/python -m mock_simulator.server   # /v1/* on :8000
```

Secrets stay in `.env` (never committed). All simulator integration goes through `backend/simulator_client.py` over `/v1/*` only.

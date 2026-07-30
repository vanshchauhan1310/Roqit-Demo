# Fleet Optimization Platform

A full-stack platform for fleet trip planning and optimization. Three independently deployable parts — `frontend`, `backend`, `ml` — that work together over HTTP.

- **frontend/** — React + TypeScript + Vite, TailwindCSS, React Query, React Router, Recharts, Leaflet.
- **backend/** — FastAPI + SQLAlchemy + Alembic, backed by PostgreSQL (hosted on [Supabase](https://supabase.com)).
- **ml/** — Standalone Python service (scikit-learn/XGBoost) exposing `/predict/*` endpoints, called by the backend over HTTP so it can scale/deploy separately.

The **Trip module** is the first fully-built vertical slice: trip CRUD, a trip list page, and a 5-tab trip detail page (Route Intelligence, Vehicle Intelligence, Driver Intelligence, Real-Time Operations, Reporting & KPI). Vehicles and Drivers reuse the same backend models/tables; their own dedicated frontend pages come later.

## Database

This project uses [Supabase](https://supabase.com) (hosted Postgres) instead of a local Postgres container. Create a Supabase project, grab the connection string from **Project Settings > Database > Connection string (URI)**, and put it in `backend/.env` as `DATABASE_URL` (see `backend/.env.example` for the exact format — note the `postgresql+psycopg2://` scheme and `?sslmode=require`).

## Run everything with Docker

```bash
cp backend/.env.example backend/.env   # fill in your Supabase DATABASE_URL
docker-compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (docs at /docs, health at /health)
- ML service: http://localhost:8001 (health at /health)

## Run each part locally (without Docker)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env   # fill in your Supabase DATABASE_URL
alembic upgrade head    # once migrations exist
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

### ML service

```bash
cd ml
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/train.py --model eta --input data/raw/trips.csv   # train the example ETA model
uvicorn service.ml_api:app --reload --port 8001
```

## Where to add new features

| Adding...                                   | Goes in...                                                        |
|----------------------------------------------|---------------------------------------------------------------------|
| A new API resource (CRUD)                     | `backend/app/models/`, `schemas/`, `services/`, `api/routes/`      |
| A new DB table/column                         | `backend/app/models/` + `alembic revision --autogenerate`          |
| New frontend page                             | `frontend/src/pages/` + register the route in `App.tsx`            |
| New Trip-detail tab or trip-specific widget   | `frontend/src/components/trip/`                                     |
| Reusable UI (buttons, tables, modals)         | `frontend/src/components/common/`                                   |
| New API call from the frontend                | `frontend/src/api/` + a hook in `frontend/src/hooks/`               |
| A new ML model                                | `ml/src/models/` (train/predict), wire into `ml/src/train.py`, add an endpoint in `ml/service/ml_api.py` |
| Backend calling a new ML endpoint             | `backend/app/services/ml_client.py`                                 |

## Conventions

- IDs are named consistently with the schema: `trip_id`, `driver_id`, `vehicle_id`, `route_id`, `stop_id`.
- All URLs, DB credentials, and API keys come from environment variables — see `.env.example` in `frontend/` and `backend/`. Never commit real `.env` files.
- The backend never imports ML code directly — it always calls the `ml` service over HTTP, so ML can be scaled or redeployed independently.

# Deployment And Config

## Backend Local Runtime

```bash
cd /Users/hj/Documents/paltform_data_V2/inland-shipping-platform
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
.venv/bin/python -m scripts.seed_system_init --profile production
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Frontend Local Runtime

```bash
cd /Users/hj/Documents/paltform_data_V2/frontend
npm install
cp .env.example .env.local
npm run dev
```

Default frontend dev proxy:

```text
VITE_API_BASE_URL=/api/v1
VITE_PROXY_TARGET=http://127.0.0.1:8000
```

## Required Backend Environment

Core:

- `APP_NAME`
- `APP_VERSION`
- `APP_ENV`
- `DEBUG`
- `DATABASE_URL`
- `SECRET_KEY`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `ALLOWED_ORIGINS`

Database:

- Local SQLite: `sqlite+aiosqlite:///./inland_shipping.db`
- MySQL: `mysql+asyncmy://user:password@host:3306/inland_shipping?charset=utf8mb4`

## External Integrations

Route geometry:

- `ROUTE_GEOMETRY_MODE`
- `ROUTE_GEOMETRY_TIMEOUT_SECONDS`
- `ROUTE_AMAP_WEB_API_KEY`
- `AMAP_JS_API_KEY`
- `AMAP_SECURITY_JS_CODE`

AIS and search:

- `ES_R_*` for realtime AIS
- `ES_*` for backend ES access
- `ES_HISTORY_*` for history index access

HiFleet/AMMS session:

- `HIFLEET_ENABLED`
- `HIFLEET_BASE_URL`
- `HIFLEET_LOGIN_URL`
- `HIFLEET_ROUTE_URL`
- `HIFLEET_USERNAME`
- `HIFLEET_PASSWORD`

AI:

- `AI_PROVIDER`
- `DASHSCOPE_BASE_URL`
- `DASHSCOPE_API_KEY`
- freight AI model/config keys seeded into `system_config`

Object storage:

- `COS_ENABLED`
- `COS_BUCKET_NAME`
- `COS_REGION`
- `COS_ENDPOINT`
- `COS_ACCESS_KEY`
- `COS_SECRET_KEY`

## Startup Controls

The container/start script can use:

- `WAIT_FOR_DB_ON_START`
- `RUN_MIGRATIONS_ON_START`
- `RUN_SEED_ON_START`
- `UVICORN_PORT`
- `UVICORN_LOG_LEVEL`

If `RUN_SEED_ON_START=true`, deployment must explicitly set `SEED_PROFILE=production`. Do not use `local-demo` in production.

## Security Notes

- Do not commit `.env.local`, database files, WAL files, private keys or provider credentials.
- Keep `SECRET_KEY` unique per environment.
- Keep `ALLOWED_ORIGINS` narrow in production.
- External provider configs should be tested through system config test APIs before enabling dependent workflows.

## Operational Checks

- `GET /health`
- OpenAPI available at `/docs` when enabled
- Alembic head equals `001_initial_schema`
- `GET /api/v1/freight` returns 404
- `GET /api/v1/freight/opportunities` requires authentication
- frontend menu after login matches production information architecture

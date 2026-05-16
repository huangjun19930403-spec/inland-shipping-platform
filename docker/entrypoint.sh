#!/usr/bin/env sh
set -eu

cd /app

if [ "${WAIT_FOR_DB_ON_START:-true}" = "true" ]; then
  echo "[entrypoint] waiting for database connectivity..."
  max_retries="${DB_WAIT_MAX_RETRIES:-30}"
  retry_interval="${DB_WAIT_INTERVAL_SECONDS:-2}"
  i=1
  until alembic current >/dev/null 2>&1; do
    if [ "$i" -ge "$max_retries" ]; then
      echo "[entrypoint] database is still unavailable after ${max_retries} retries"
      exit 1
    fi
    i=$((i + 1))
    sleep "$retry_interval"
  done
fi

if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then
  echo "[entrypoint] running alembic upgrade head..."
  alembic upgrade head
fi

if [ "${RUN_SEED_ON_START:-true}" = "true" ]; then
  if [ -z "${SEED_PROFILE:-}" ]; then
    echo "[entrypoint] SEED_PROFILE must be set when RUN_SEED_ON_START=true"
    exit 1
  fi
  echo "[entrypoint] running formal seed initializer..."
  PYTHONPATH=. python -m scripts.seeds.cli --profile "$SEED_PROFILE"
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn main:app --host 0.0.0.0 --port "${UVICORN_PORT:-8000}" --log-level "${UVICORN_LOG_LEVEL:-info}"

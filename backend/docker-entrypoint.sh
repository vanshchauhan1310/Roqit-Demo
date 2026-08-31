#!/bin/sh
# Backend container entrypoint: wait for dependencies, migrate, then serve.
set -e

echo "[entrypoint] waiting for database..."
python - <<'PY'
import os, sys, time
import sqlalchemy

url = os.environ.get("DATABASE_URL", "")
deadline = time.time() + 60
while True:
    try:
        engine = sqlalchemy.create_engine(url, pool_pre_ping=True)
        with engine.connect():
            print("[entrypoint] database is up")
            break
    except Exception as exc:
        if time.time() > deadline:
            print(f"[entrypoint] database not reachable in time: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
PY

echo "[entrypoint] applying database migrations..."
alembic upgrade head

if [ -n "$REDIS_URL" ]; then
  echo "[entrypoint] checking redis at $REDIS_URL ..."
  python - <<'PY'
import os, sys, time
import redis

deadline = time.time() + 30
while True:
    try:
        redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=2).ping()
        print("[entrypoint] redis is up")
        break
    except Exception as exc:
        if time.time() > deadline:
            print(f"[entrypoint] redis not reachable in time: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
PY
fi

echo "[entrypoint] starting API..."
exec "$@"
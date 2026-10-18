#!/bin/sh
set -eu

python - <<'PY'
import os
import sys
import time

url = os.environ.get("DATABASE_URL", "")
if url.startswith("postgres"):
    import psycopg

    last_error = None
    for attempt in range(30):
        try:
            with psycopg.connect(url, connect_timeout=3):
                break
        except Exception as exc:  # noqa: BLE001 - startup should report any driver error
            last_error = exc
            print(f"waiting for database ({attempt + 1}/30): {exc}", flush=True)
            time.sleep(1)
    else:
        print(f"database not available: {last_error}", file=sys.stderr)
        sys.exit(1)
PY

python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec "$@"

#!/bin/sh
# Build the GitHub Pages site: walkthrough, exported OpenAPI schema, and Redoc.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
out=${1:-$root/site}
mkdir -p "$out"

cd "$root"
export USE_SQLITE="${USE_SQLITE:-true}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-docs-build}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-false}"
export SQLITE_NAME="${SQLITE_NAME:-/tmp/ticketdesk-docs.sqlite3}"

if command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  PYTHON=python3
fi

"$PYTHON" manage.py migrate --noinput
"$PYTHON" manage.py spectacular --file "$out/openapi.yaml" --validate --fail-on-warn
cp "$root/docs/index.html" "$root/docs/redoc.html" "$out/"
"$PYTHON" - <<PY
import urllib.request
from pathlib import Path

url = "https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js"
destination = Path("$out") / "redoc.standalone.js"
with urllib.request.urlopen(url, timeout=60) as response:
    destination.write_bytes(response.read())
if destination.stat().st_size < 10000:
    raise SystemExit("redoc bundle looks truncated")
PY

test -s "$out/openapi.yaml"
test -s "$out/index.html"
test -s "$out/redoc.html"
echo "site written to $out"

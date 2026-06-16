#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
if [ ! -x ".venv/bin/python" ]; then
  echo "Python environment is not ready. Run ./setup.sh first." >&2
  exit 1
fi
".venv/bin/python" scripts/run_app.py "$@"

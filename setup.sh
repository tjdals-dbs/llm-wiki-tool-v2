#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not available. Install Python 3.11 or newer, then run ./setup.sh again." >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment in .venv..."
  python3 -m venv .venv || {
    echo "Failed to create the Python virtual environment." >&2
    exit 1
  }
fi

echo "Upgrading pip..."
".venv/bin/python" -m pip install --upgrade pip || {
  echo "Failed to upgrade pip." >&2
  exit 1
}

echo "Installing project dependencies..."
".venv/bin/python" -m pip install -r requirements.txt || {
  echo "Failed to install dependencies from requirements.txt." >&2
  exit 1
}

echo "Setup complete. Run ./run_app.sh to start the desktop app."

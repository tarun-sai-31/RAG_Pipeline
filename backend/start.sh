#!/usr/bin/env bash
# Starts the backend with the project's own Python environment (backend/.venv).
#
#   ./start.sh        development: auto-reload on code changes  (fastapi dev)
#   ./start.sh run    normal mode, no auto-reload               (fastapi run)
#
# Works from any folder and from any terminal (Anaconda "base" included).
set -euo pipefail
cd "$(dirname "$0")"

# First run on a new machine: create the environment and install the packages.
if [ ! -x .venv/bin/fastapi ]; then
  echo "Setting up backend/.venv (first run only)…"
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

source .venv/bin/activate
exec .venv/bin/fastapi "${1:-dev}"

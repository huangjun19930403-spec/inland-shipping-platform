#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

resolve_python311() {
  local candidate resolved output
  for candidate in "${PYTHON_BIN:-}" /opt/homebrew/bin/python3.11 python3.11 /usr/local/bin/python3.11; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1; then
      resolved="$(command -v "$candidate")"
    elif [ -x "$candidate" ]; then
      resolved="$candidate"
    else
      continue
    fi
    output="$("$resolved" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    if [ "$output" = "3.11" ]; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(resolve_python311 || true)"

if [ -z "$PYTHON_BIN" ]; then
  echo "[ERROR] A working Python 3.11 interpreter is required."
  exit 1
fi

if [ -d ".venv" ]; then
  VENV_VERSION="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [ "$VENV_VERSION" != "3.11" ]; then
    echo "[ERROR] Existing .venv uses Python $VENV_VERSION. Remove it and recreate with Python 3.11."
    exit 1
  fi
else
  echo "[INFO] Creating virtual environment..."
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate

echo "[INFO] Installing dependencies..."
pip install -q -r requirements.txt -r requirements-dev.txt

echo "[INFO] Starting API server on http://127.0.0.1:8000"
uvicorn main:app --reload --host 0.0.0.0 --port 8000

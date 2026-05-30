#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

find_free_port() {
  local port="$1"
  while "$PYTHON_BIN" - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("127.0.0.1", port))
finally:
    sock.close()
PY
  do
    echo "$port"
    return 0
  done

  while true; do
    port=$((port + 1))
    if "$PYTHON_BIN" - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("127.0.0.1", port))
finally:
    sock.close()
PY
    then
      echo "$port"
      return 0
    fi
  done
}

port_is_free() {
  local port="$1"
  "$PYTHON_BIN" - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("127.0.0.1", port))
finally:
    sock.close()
PY
}

cleanup() {
  echo
  echo "Stopping AgentLab..."
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" >/dev/null 2>&1 || true
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if [[ ! -f "$BACKEND_DIR/.env" ]]; then
  echo "Warning: backend/.env not found. Copy backend/.env.example if you have not configured the model yet."
fi

if ! port_is_free "$BACKEND_PORT"; then
  echo "Error: backend port $BACKEND_PORT is already in use."
  echo "Stop the existing service or run with another port, for example:"
  echo "  BACKEND_PORT=8001 ./start.sh"
  exit 1
fi

FRONTEND_PORT="$(find_free_port "$FRONTEND_PORT")"

echo "Starting backend on http://127.0.0.1:$BACKEND_PORT"
(
  cd "$BACKEND_DIR"
  "$PYTHON_BIN" -m uvicorn main:app --reload --host 127.0.0.1 --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

echo "Starting frontend on http://127.0.0.1:$FRONTEND_PORT"
(
  cd "$FRONTEND_DIR"
  "$PYTHON_BIN" -m http.server "$FRONTEND_PORT" --bind 127.0.0.1
) &
FRONTEND_PID=$!

cat <<EOF

AgentLab is running.

Frontend: http://127.0.0.1:$FRONTEND_PORT
Backend:  http://127.0.0.1:$BACKEND_PORT

Press Ctrl+C to stop both services.
EOF

wait

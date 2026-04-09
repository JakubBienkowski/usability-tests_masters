#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/logs"
EXT_DIR="$ROOT_DIR/ux-test-platform"
EXT_DIST_DIR="$EXT_DIR/dist"
DESKTOP_AGENT_PID_FILE="$RUN_DIR/desktop_agent.pid"

mkdir -p "$RUN_DIR" "$LOG_DIR"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_docker_daemon() {
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but the daemon is not running." >&2
    echo "Start Docker Desktop (or another Docker daemon) and rerun ./scripts/start_app.sh" >&2
    exit 1
  fi
}

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
    return
  fi

  echo "Docker Compose is required but was not found." >&2
  exit 1
}

wait_for_backend() {
  local attempts=30
  local url="http://localhost:8000/health"

  while [ "$attempts" -gt 0 ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 2
  done

  echo "Backend did not become healthy at $url" >&2
  exit 1
}

start_desktop_agent() {
  if [ -f "$DESKTOP_AGENT_PID_FILE" ]; then
    local old_pid
    old_pid="$(cat "$DESKTOP_AGENT_PID_FILE")"
    if kill -0 "$old_pid" >/dev/null 2>&1; then
      echo "Desktop agent already running with PID $old_pid"
      return
    fi
    rm -f "$DESKTOP_AGENT_PID_FILE"
  fi

  nohup "$VENV_DIR/bin/python" "$ROOT_DIR/desktop_agent.py" \
    >"$LOG_DIR/desktop_agent.log" 2>&1 &
  echo "$!" >"$DESKTOP_AGENT_PID_FILE"
  echo "Desktop agent started with PID $(cat "$DESKTOP_AGENT_PID_FILE")"
}

print_next_steps() {
  cat <<EOF

Startup finished.

Backend:
- API: http://localhost:8000
- RabbitMQ UI: http://localhost:15672

Artifacts:
- Extension build: $EXT_DIST_DIR
- Desktop agent log: $LOG_DIR/desktop_agent.log

Next step in browser:
1. Open Chrome or Edge.
2. Go to extensions page.
3. Enable Developer Mode.
4. Load unpacked extension from:
   $EXT_DIST_DIR
5. Open the extension popup and click Start.

Notes:
- Extension auto-runs on websites only after it is installed once.
- Browser extensions cannot be silently auto-installed by this script.
- Desktop agent is already running for outside-browser capture.
EOF
}

require_command python3
require_command npm
require_command docker
require_command curl
require_docker_daemon

COMPOSE_CMD="$(detect_compose)"

echo "Creating Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install -r "$ROOT_DIR/requirements.txt"

echo "Installing extension dependencies..."
(cd "$EXT_DIR" && npm install)

echo "Building browser extension..."
(cd "$EXT_DIR" && npm run build)

echo "Starting backend stack with Docker..."
(cd "$ROOT_DIR" && $COMPOSE_CMD up -d --build rabbitmq api worker)

echo "Waiting for backend healthcheck..."
wait_for_backend

echo "Starting desktop agent..."
start_desktop_agent

print_next_steps

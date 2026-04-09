#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
DESKTOP_AGENT_PID_FILE="$RUN_DIR/desktop_agent.pid"

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
    return
  fi

  echo ""
}

if [ -f "$DESKTOP_AGENT_PID_FILE" ]; then
  PID="$(cat "$DESKTOP_AGENT_PID_FILE")"
  if kill -0 "$PID" >/dev/null 2>&1; then
    kill "$PID"
    echo "Stopped desktop agent PID $PID"
  fi
  rm -f "$DESKTOP_AGENT_PID_FILE"
fi

COMPOSE_CMD="$(detect_compose)"
if [ -n "$COMPOSE_CMD" ]; then
  (cd "$ROOT_DIR" && $COMPOSE_CMD down)
  echo "Stopped Docker services"
fi

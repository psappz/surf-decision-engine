#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/wavewatch/app"
COMPOSE_FILE="$APP_DIR/docker-compose.prod.yml"
LOG_PREFIX="wavewatch-copernicus-cron"
LOCK_FILE="/tmp/wavewatch-copernicus-cron.lock"
ACTION="${1:-}"

log() {
  printf '{"ts":"%s","component":"%s","level":"%s","message":"%s"}\n' "$(date -u +%FT%TZ)" "$LOG_PREFIX" "$1" "$2"
}

if [[ "$ACTION" != "check" && "$ACTION" != "reconcile" ]]; then
  log error "usage: $0 check|reconcile"
  exit 64
fi

if ! command -v docker >/dev/null 2>&1; then
  log error "docker command not found"
  exit 69
fi

cd "$APP_DIR"
if [[ ! -f "$COMPOSE_FILE" ]]; then
  log error "compose file missing: $COMPOSE_FILE"
  exit 66
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log info "another cron check is already running"
  exit 0
fi

if ! docker compose -f "$COMPOSE_FILE" ps --status running app >/dev/null 2>&1; then
  log error "app service is not running"
  exit 70
fi
if ! docker compose -f "$COMPOSE_FILE" ps --status running worker >/dev/null 2>&1; then
  log error "worker service is not running"
  exit 70
fi

log info "starting $ACTION"
OUTPUT="$(docker compose -f "$COMPOSE_FILE" exec -T app python -m app.tools.copernicus "$ACTION")"
printf '%s\n' "$OUTPUT"
if printf '%s' "$OUTPUT" | grep -q '"status": "queued"'; then
  log info "queued publication detected; starting detached worker"
  docker compose -f "$COMPOSE_FILE" exec -d worker python -m app.workers.copernicus
else
  log info "no worker launch needed"
fi

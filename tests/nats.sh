#!/usr/bin/env bash
# Start a local NATS server in Docker for live testing.
# Usage:  ./tests/nats.sh [start|stop|logs|url]
set -euo pipefail

CONTAINER="eyenet-nats"
IMAGE="nats:2.10-alpine"
PORT=4222
MONITOR_PORT=8222

cmd="${1:-start}"

case "$cmd" in
  start)
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
      echo "NATS already running → nats://localhost:${PORT}"
      exit 0
    fi
    docker run -d \
      --name "$CONTAINER" \
      -p "${PORT}:4222" \
      -p "${MONITOR_PORT}:8222" \
      "$IMAGE" \
      -js \
      -m "${MONITOR_PORT}"

    # Wait up to 5s for NATS to accept connections.
    for i in $(seq 1 10); do
      if docker exec "$CONTAINER" nats-server --version &>/dev/null || \
         curl -sf "http://localhost:${MONITOR_PORT}/healthz" &>/dev/null; then
        break
      fi
      sleep 0.5
    done

    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
      echo "NATS failed to start. Logs:"
      docker logs "$CONTAINER" 2>&1 || true
      docker rm "$CONTAINER" &>/dev/null || true
      exit 1
    fi

    echo "NATS started → nats://localhost:${PORT}  (monitor http://localhost:${MONITOR_PORT})"
    ;;

  stop)
    docker stop "$CONTAINER" 2>/dev/null || true
    docker rm "$CONTAINER" 2>/dev/null && echo "NATS stopped." || echo "Not running."
    ;;

  logs)
    docker logs -f "$CONTAINER"
    ;;

  url)
    echo "nats://localhost:${PORT}"
    ;;

  *)
    echo "Usage: $0 [start|stop|logs|url]"
    exit 1
    ;;
esac

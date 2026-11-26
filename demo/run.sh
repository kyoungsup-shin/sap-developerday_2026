#!/usr/bin/env bash
# Run the local Docker demo without exposing internal Agent services.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
COMPOSE=(docker compose -f "${COMPOSE_FILE}")

require_docker() {
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running. Start Docker Desktop, then try again." >&2
    exit 1
  fi
}

run_demo() {
  require_docker
  "${COMPOSE[@]}" up -d
  "${COMPOSE[@]}" ps
  echo
  echo "Demo is available at http://localhost:5173"
}

rebuild_demo() {
  require_docker
  "${COMPOSE[@]}" build --no-cache
  "${COMPOSE[@]}" up -d --force-recreate
  "${COMPOSE[@]}" ps
  echo
  echo "Demo was rebuilt and is available at http://localhost:5173"
}

choose_and_run() {
  echo "A2A Demo Docker"
  echo
  echo "  1) Run existing images"
  echo "  2) Rebuild images and run"
  echo "  3) Stop the demo"
  echo "  4) Follow service logs"
  echo "  5) Show service status"
  echo "  0) Exit"
  echo
  read -r -p "Select a scenario [0-5]: " selection

  case "${selection}" in
    1) run_demo ;;
    2) rebuild_demo ;;
    3) require_docker; "${COMPOSE[@]}" down ;;
    4) require_docker; "${COMPOSE[@]}" logs -f ;;
    5) require_docker; "${COMPOSE[@]}" ps ;;
    0) echo "No action selected." ;;
    *) echo "Invalid selection. Run the script again and choose 0 through 5." >&2; exit 2 ;;
  esac
}

if [[ $# -gt 0 ]]; then
  echo "This script uses interactive scenario selection. Run: ./demo/run.sh" >&2
  exit 2
fi

choose_and_run

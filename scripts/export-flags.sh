#!/usr/bin/env bash
set -euo pipefail

# Export all challenge flags to flags.csv in the project root.
# Usage: ./scripts/export-flags.sh [output_path]

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$PROJECT_ROOT/flags.csv}"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.dev.yml"
TMP="/tmp/flags.csv"

docker compose -f "$COMPOSE_FILE" exec ctfd python seed.py --export-csv "$TMP"
docker compose -f "$COMPOSE_FILE" cp "ctfd:$TMP" "$OUT"

echo "Exported to $OUT"

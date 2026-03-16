#!/usr/bin/env bash
set -euo pipefail

# Export all challenge flags to flags.csv in the project root.
# Usage: ./export-flags.sh [output_path]

OUT="${1:-flags.csv}"
COMPOSE_FILE="docker-compose.dev.yml"
TMP="/tmp/flags.csv"

docker compose -f "$COMPOSE_FILE" exec ctfd python seed.py --export-csv "$TMP"
docker compose -f "$COMPOSE_FILE" cp "ctfd:$TMP" "./$OUT"

echo "Exported to $OUT"

#!/usr/bin/env bash
set -euo pipefail

# Seed challenges into the database.
# Usage: ./scripts/seed-challenges.sh

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.dev.yml"

echo "Seeding challenges..."
docker compose -f "$COMPOSE_FILE" exec ctfd python seed.py
echo "Done."

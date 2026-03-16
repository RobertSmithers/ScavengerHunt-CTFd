#!/usr/bin/env bash
set -euo pipefail

# Delete all seeded challenges, flags, and tags from the database.
# Usage: ./scripts/clean-challenges.sh

COMPOSE_FILE="docker-compose.dev.yml"

echo "Deleting all challenges, flags, and tags..."
docker compose -f "$COMPOSE_FILE" exec db \
  mariadb -u ctfd -pctfd ctfd -e \
  "DELETE FROM flags; DELETE FROM tags; DELETE FROM challenges WHERE type='standard';"

echo "Done — all seeded challenges removed."

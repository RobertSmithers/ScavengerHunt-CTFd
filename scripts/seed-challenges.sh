#!/usr/bin/env bash
set -euo pipefail

# Seed challenges into the database.
# Usage: ./scripts/seed-challenges.sh [seed.py args...]
#
# Examples:
#   ./scripts/seed-challenges.sh                              # seed all unlocked
#   ./scripts/seed-challenges.sh --all                        # seed everything
#   ./scripts/seed-challenges.sh --reseed "Murph - 0930"      # delete + reseed one event
#   ./scripts/seed-challenges.sh --list                       # show categories & locks
#   ./scripts/seed-challenges.sh --print-flags                # print all flags

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.dev.yml"

echo "Seeding challenges..."
docker compose -f "$COMPOSE_FILE" exec ctfd python seed.py "$@"
echo "Done."

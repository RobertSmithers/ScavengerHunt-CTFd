#!/usr/bin/env bash
set -euo pipefail

# Delete seeded challenges, flags, and tags from the database.
#
# Usage:
#   ./scripts/clean-challenges.sh                          # delete ALL challenges
#   ./scripts/clean-challenges.sh "Murph - 0930"           # delete only this category
#   ./scripts/clean-challenges.sh "Trivia - 0900" "Murph"  # delete multiple categories
#
# For selective re-seeding, prefer:  ./scripts/seed-challenges.sh --reseed "Category"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.dev.yml"

if [[ $# -eq 0 ]]; then
  echo "Deleting ALL challenges, flags, and tags..."
  docker compose -f "$COMPOSE_FILE" exec db \
    mariadb -u ctfd -pctfd ctfd -e \
    "DELETE FROM flags; DELETE FROM tags; DELETE FROM challenges;"
else
  for category in "$@"; do
    echo "Deleting category: $category"
    # Flags and tags cascade-delete automatically via FK constraints
    docker compose -f "$COMPOSE_FILE" exec db \
      mariadb -u ctfd -pctfd ctfd -e \
      "DELETE FROM challenges WHERE category='${category//\'/\\\'}';"
  done
fi

echo "Clearing challenge cache..."
docker compose -f "$COMPOSE_FILE" exec ctfd python -c \
  "from CTFd import create_app; app = create_app(); app.app_context().push(); from CTFd.cache import clear_challenges; clear_challenges(); print('Cache cleared.')"

echo "Done."

"""
Golden Web 2026 — Challenge Definitions

Edit the CHALLENGES list below to match your competition events.
``python seed.py`` from the project root to seed the database.
``python seed.py --print-flags`` to print all flags for event leads.

Point scales and challenge instances are intentionally declared at the top
level so they can be imported and inspected without touching the DB.

Additionally, these events are idempotent, so this script can be safely re-run.
"""

import logging

from CTFd.seeds import (
    CheckInChallenge,
    RankingChallenge,
    ScavengerHuntChallenge,
    StaticChallenge,
    TournamentChallenge,
    set_prerequisites,
)
from CTFd.models import db

log = logging.getLogger(__name__)


# ── Reusable point scales ────────────────────────────────────────────────────

def generate_podium_points(num_places, base_points=500):
	"""Generate a simple point scale for a podium of N places."""
	# 500, 400, 300, 250, 200, 175, 150, 125, 100, 75, 50, 25

	points = []
	decrement = 0
	for place in range(1, num_places + 1):
		if place <= 2:
			decrement = (place - 1) * 100
		elif place <= 5:
			decrement = (100 * 2) + (place - 3) * 50
		else:
			decrement = (100 * 2) + (50 * 3) + (place - 6) * 25
		points.append((place, max(base_points - decrement, 25)))
	return points

PODIUM_10 = generate_podium_points(10)
PODIUM_4 = generate_podium_points(4)
PODIUM_3 = generate_podium_points(3)


# ── Gate challenge (must be first) ───────────────────────────────────────────

CHECK_IN = CheckInChallenge(
    name="Competition Check-in",
    category="The Warm Up",
    description=(
        "Enter the code provided at the start of the event to unlock all "
        "competition challenges."
    ),
    tags=["warmup"],
)

# Challenges in chronological order
CHALLENGES = [
	# 0900
    CHECK_IN,


    *RankingChallenge.for_event(
        category="Trivia - 0900",
        placements=PODIUM_4,
        tags=["trivia", "ranking"],
	),

	*ScavengerHuntChallenge.hunt(
		category="Spider Egg Hunt - All Morning",
		count=80,
		value=20,
		label="Egg",
		golden_count=12,
		golden_value=50,
		golden_label="Golden Egg",
		tags=["scavenger", "hunt"],
	),

	# 0915
    *RankingChallenge.for_event(
        category="The MAV Demo - 0915",
        placements=PODIUM_10,
        tags=["fitness", "ranking"],
    ),

	*TournamentChallenge.bracket(
		category="Flag Football Tournament - 0900",
		participants=16,
		base_value=50,
		value_step=50,
		tags=["sports", "tournament"],
	),

	# 0930
    *TournamentChallenge.bracket(
        category="Pickleball Tournament - 0930",
        participants=16,
        base_value=50,
        value_step=50,
        tags=["sports", "tournament"],
    ),

	*RankingChallenge.for_event(
		category="Murph - 0930",
		placements=PODIUM_10,
		tags=["fitness", "ranking"],
	),

	# 0945

	# 1000
    *TournamentChallenge.bracket(
        category="Pickleball Tournament - 1000",
        participants=16,
        base_value=50,
        value_step=50,
        tags=["sports", "tournament"],
    ),

	# 1030
	*TournamentChallenge.bracket(
		category="Ultimate Frisbee Tournament - 1030",
		participants=16,
		base_value=50,
		value_step=50,
		tags=["sports", "tournament"],
	),

    *RankingChallenge.for_event(
        category="Trivia - 1030",
        placements=PODIUM_4,
        tags=["trivia", "ranking"],
	),

	# 1100
	*RankingChallenge.for_event(
		category="Relay Race - 1100",
		placements=PODIUM_10,
		tags=["fitness", "ranking"],
	),

	*RankingChallenge.for_event(
		category="Knockout - 1100",
		placements=PODIUM_10,
		tags=["sports", "ranking"],
	),

	*RankingChallenge.for_event(
		category="Sally Up/Down Challenges - 0945",
		placements=PODIUM_10,
		tags=["fitness", "ranking"],
	),

	# 1200
	StaticChallenge(
		name="Completion Check-in",
		category="Awards Ceremony - 1200",
		description=(
			"To receive these points, check in at the main tent and then return to your formation."
			" This challenge closes as 1200, after which point no more submissions will be accepted!"
		),
		value=100,
		tags=["check-in", "awards"],
	),
]


def seed(secret_key):
    """Seed all Golden Web 2026 challenges.  Safe to run multiple times."""
    created = 0
    skipped = 0
    for challenge_def in CHALLENGES:
        _, was_created = challenge_def.create(secret_key)
        if was_created:
            created += 1
        else:
            skipped += 1

    # Single commit for all staged challenges, flags, and tags
    db.session.commit()

    # Wire the check-in as a prerequisite for every other challenge
    dependents = [(c.name, c.category) for c in CHALLENGES if c is not CHECK_IN]
    set_prerequisites(CHECK_IN.name, dependents)

    log.info("Seeding complete: %d created, %d skipped", created, skipped)
    return created, skipped

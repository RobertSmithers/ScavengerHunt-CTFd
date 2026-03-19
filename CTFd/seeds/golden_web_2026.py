"""
Golden Web 2026 — Challenge Definitions

Edit the CHALLENGES list below to match your competition events.
``python seed.py`` from the project root to seed the database.
``python seed.py --print-flags`` to print all flags for event leads.

Point scales and challenge instances are intentionally declared at the top
level so they can be imported and inspected without touching the DB.

Additionally, these events are idempotent, so this script can be safely re-run.
"""

import json
import logging
from pathlib import Path

from collections import OrderedDict

from CTFd.seeds import (
    CheckInChallenge,
    RankingChallenge,
    ScavengerHuntChallenge,
    StaticChallenge,
    TournamentChallenge,
    delete_categories,
    set_prerequisites,
)
from CTFd.cache import clear_challenges
from CTFd.models import db

log = logging.getLogger(__name__)


# ── Reusable point scales ────────────────────────────────────────────────────

def generate_podium_points(num_places, first=500, last=25, curve=1.0):
	"""Generate a smooth point scale for a podium of N places.

	Args:
		num_places: Number of ranked positions.
		first: Points awarded to 1st place.
		last: Points awarded to last place.
		curve: Smoothing exponent.
		       1.0 = linear drop,
		       >1  = steeper drop near 1st (top-heavy),
		       <1  = gentler drop near 1st (bottom-heavy).
	"""
	if num_places == 1:
		return [(1, first)]
	points = []
	for place in range(1, num_places + 1):
		t = (place - 1) / (num_places - 1)   # 0.0 → 1st, 1.0 → last
		value = first + (last - first) * (t ** curve)
		points.append((place, 25 * round(value / 25)))
	return points

PODIUM_10 = generate_podium_points(10, first=500, last=25, curve=1.5)
KNOCKOUT_PODIUM_5 = generate_podium_points(5, first=100, last=25, curve=0.5)
PODIUM_4 = generate_podium_points(4, first=300, last=50, curve=0.5)
SALLY_PODIUM_3 = generate_podium_points(3, first=200, last=100, curve=1.0)


# ── Locked categories ────────────────────────────────────────────────────────
# Add category names here once their flags have been printed / distributed.
# Locked categories are protected from --reseed and skipped by default seeding
# unless explicitly targeted with --all.

LOCKED_CATEGORIES = set()
# LOCKED_CATEGORIES.add("Trivia - 0900")
# LOCKED_CATEGORIES.add("Spider Egg Hunt - All Morning")


# ── Golden egg answers (loaded from external secrets file) ───────────────────
_GOLDEN_EGGS_PATH = Path(__file__).parent / "golden_eggs.json"
if _GOLDEN_EGGS_PATH.exists():
    with open(_GOLDEN_EGGS_PATH) as _f:
        GOLDEN_EGGS = json.load(_f)
else:
    log.warning("golden_eggs.json not found — golden eggs will have no answers")
    GOLDEN_EGGS = []


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

	*ScavengerHuntChallenge.hunt(
		category="Spider Egg Hunt - All Morning",
		count=80,
		value=15,
		label="Egg",
		tags=["scavenger", "hunt"],
	),

	# Golden Eggs — puzzles done outside CTFd, answers loaded from golden_eggs.json
	*[
		StaticChallenge(
			name=f"Golden Egg {i}",
			category="Spider Egg Hunt - All Morning",
			description=(
				"Solve the puzzle on this Golden Egg and enter the answer to earn your points."
			),
			answer=egg["answer"],
			value=50,
			tags=["scavenger", "hunt", "golden"],
		)
		for i, egg in enumerate(GOLDEN_EGGS, start=1)
	],

    *RankingChallenge.for_event(
        category="Trivia - 0900",
        placements=generate_podium_points(4, first=300, last=50, curve=0.5),
        tags=["trivia", "ranking"],
	),
      
	*TournamentChallenge.bracket(
		category="Flag Football Tournament - 0900",
		participants=16,
		base_value=50,
		value_step=50,
		tags=["sports", "tournament"],
	),

	# 0915
    # *RankingChallenge.for_event(
    #     category="The MAV Demo - 0915",
    #     placements=generate_podium_points(10, first=200, last=25, curve=0.3),
    #     flag_count=5,
    #     tags=["fitness", "ranking"],
    # ),

	# 0930
    *TournamentChallenge.bracket(
        category="Pickleball Tournament - 0930",
        participants=8,
        base_value=50,
        value_step=50,
        tags=["sports", "tournament"],
    ),

	# 0945
    StaticChallenge(
		name="Winner",
		category="Shirt's Circuit - 0945",
		challenge_type="standard",
		description=(
			"After you win a head to head (1 team vs 1 team) matchup in this event, check in with your event lead to receive the code."
               "Note: You will only earn points for your first win/no points for reattempting unless you have not won yet"
		),
		value=100,
		flag_count=30,
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
	StaticChallenge(
		name="Winner",
		category="The MAV Demo - 1100",
		challenge_type="standard",
		description=(
			"To claim these points, you must move the MAV a certain distance using pure strength"
               "Points are awarded for first-time completion only"
		),
		value=100,
		flag_count=30,
		tags=["fitness", "solo"],
	),

	*RankingChallenge.for_event(
		category="Keyboard Warrior Relay - 1100",
		placements=PODIUM_4,
		tags=["fitness", "ranking"],
	),
     
	# 1115
	*RankingChallenge.for_event(
		category="Knockout - 1115",
		placements=KNOCKOUT_PODIUM_5,
		name_prefix="Heat 1 - ",
		tags=["sports", "ranking"],
	),

	*RankingChallenge.for_event(
		category="Knockout - 1115",
		placements=KNOCKOUT_PODIUM_5,
		name_prefix="Heat 2 - ",
		tags=["sports", "ranking"],
	),

	*RankingChallenge.for_event(
		category="Knockout - 1115",
		placements=KNOCKOUT_PODIUM_5,
		name_prefix="Heat 3 - ",
		tags=["sports", "ranking"],
	),

	*RankingChallenge.for_event(
		category="Knockout - 1115",
		placements=KNOCKOUT_PODIUM_5,
		name_prefix="Heat 4 - ",
		tags=["sports", "ranking"],
	),
     
	 # 1130
	*RankingChallenge.for_event(
		category="Keyboard Warrior Relay - 1130",
		placements=PODIUM_4,
		tags=["fitness", "ranking"],
	),

	*RankingChallenge.for_event(
		category="Sally Up/Down - 1130",
		placements=SALLY_PODIUM_3,
        name_prefix="Event 1 - ",
		tags=["fitness", "ranking"],
	),
	*RankingChallenge.for_event(
		category="Sally Up/Down - 1130",
		placements=SALLY_PODIUM_3,
        name_prefix="Event 2 - ",
		tags=["fitness", "ranking"],
	),
	*RankingChallenge.for_event(
		category="Sally Up/Down - 1130",
		placements=SALLY_PODIUM_3,
        name_prefix="Event 3 - ",
		tags=["fitness", "ranking"],
	),
	*RankingChallenge.for_event(
		category="Sally Up/Down - 1130",
		placements=SALLY_PODIUM_3,
        name_prefix="Event 4 - ",
		tags=["fitness", "ranking"],
	),

	# 1200
	StaticChallenge(
		name="Awards Ceremony Check-in",
		category="Awards Ceremony - 1200",
		challenge_type="standard",
		description=(
			"To receive these points, check in at the main tent and then return to your formation."
			" This challenge closes at 1200, after which point no more submissions will be accepted!"
		),
        answer="GW26{final_countdown}",
		value=100,
		tags=["check-in", "awards"],
	),
]


def get_categories():
    """Return an ordered dict of category → (challenge_count, is_locked)."""
    cats = OrderedDict()
    for c in CHALLENGES:
        if c.category not in cats:
            cats[c.category] = 0
        cats[c.category] += 1
    return OrderedDict(
        (cat, (count, cat in LOCKED_CATEGORIES))
        for cat, count in cats.items()
    )


def seed(secret_key, categories=None, reseed=False):
    """Seed Golden Web 2026 challenges.

    Args:
        secret_key:  HMAC key for flag generation.
        categories:  Optional list of category names to operate on.
                     ``None`` means all unlocked categories.
        reseed:      If True, delete existing challenges in the targeted
                     categories before re-creating them.
    """
    if categories is not None:
        target = set(categories)
    else:
        # Default: all categories that aren't locked
        target = {c.category for c in CHALLENGES} - LOCKED_CATEGORIES

    if reseed:
        deleted = delete_categories(list(target))
        log.info("Deleted %d challenges for reseed", deleted)

    created = 0
    skipped = 0
    for position, challenge_def in enumerate(CHALLENGES, start=1):
        if challenge_def.category not in target:
            skipped += 1
            continue
        _, was_created = challenge_def.create(secret_key, position=position)
        if was_created:
            created += 1
        else:
            skipped += 1

    # Single commit for all staged challenges, flags, and tags
    db.session.commit()

    # Wire the check-in as a prerequisite for every other challenge
    dependents = [(c.name, c.category) for c in CHALLENGES if c is not CHECK_IN]
    set_prerequisites(CHECK_IN.name, dependents)

    # Invalidate CTFd's challenge cache so the app picks up changes immediately
    clear_challenges()

    log.info("Seeding complete: %d created, %d skipped", created, skipped)
    return created, skipped

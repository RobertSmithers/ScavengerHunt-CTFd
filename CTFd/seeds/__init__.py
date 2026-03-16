"""
Seedable challenge framework for CTFd.

Provides a polymorphic class hierarchy for defining competition challenges
that can be idempotently inserted into the database:

    SeedChallenge              (base)
     ├─ RankingChallenge       (placement-based, auto-generated descriptions)
     ├─ TournamentChallenge    (bracket generator for N participants)
     ├─ StaticChallenge        (fixed description, custom answer)
     ├─ ScavengerHuntChallenge (numbered items + golden items)
     └─ CheckInChallenge       (0-point gate that unlocks other challenges)

Each instance represents a single CTFd Challenge row plus its associated
Flags, Tags, and (optionally) ChallengeFiles.
"""

import hashlib
import hmac
import logging
import math

from CTFd.models import ChallengeFiles, Challenges, Flags, Tags, db

log = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────


def ordinal(n):
    """Return the ordinal string for an integer (1st, 2nd, 3rd, …)."""
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _round_name(participants):
    """Human-friendly bracket round label."""
    names = {
        2: "Finals",
        4: "Semifinals",
        8: "Quarterfinals",
    }
    return names.get(participants, f"Round of {participants}")


# ── Base class ───────────────────────────────────────────────────────────────


class SeedChallenge:
    """Base class for defining seedable challenges.

    Subclasses can override ``build_description()`` to auto-generate
    descriptions from templates.

    Attributes:
        name:         Challenge display name (must be unique across the CTF).
        category:     Grouping category shown in the UI.
        value:        Point value awarded on solve.
        description:  HTML or plain-text challenge body.
        flag_count:   Number of unique flags to generate.
        max_attempts: Maximum submission attempts (0 = unlimited).
        tags:         List of tag strings.
        files:        List of file-location strings (already on disk / uploaded).
        state:        "visible" or "hidden".
        requirements: Dict for CTFd prerequisites, e.g. {"prerequisites": [1]}.
    """

    FLAG_PREFIX = "GW26"

    def __init__(
        self,
        name,
        category,
        value,
        description="",
        flag_count=1,
        max_attempts=0,
        tags=None,
        files=None,
        state="visible",
        requirements=None,
    ):
        self.name = name
        self.category = category
        self.value = value
        self.description = description or self.build_description()
        self.flag_count = flag_count
        self.max_attempts = max_attempts
        self.tags = tags or []
        self.files = files or []
        self.state = state
        self.requirements = requirements

    def build_description(self) -> str:
        """Override in subclasses to auto-generate a description."""
        return ""

    def generate_flag(self, index, secret_key):
        """Generate a deterministic, unique flag.

        Uses HMAC-SHA256 keyed on *secret_key* with ``category:name:index``
        as the message, producing a reproducible 12-hex-char code.  The same
        inputs will always yield the same flag, making the seed script safe
        to rerun.
        """
        msg = f"{self.category}:{self.name}:{index}"
        digest = hmac.new(
            secret_key.encode(), msg.encode(), hashlib.sha256
        ).hexdigest()[:12]
        return f"{self.FLAG_PREFIX}{{{digest}}}"

    def create(self, secret_key, position=0):
        """Stage Challenge, Flags, Tags, and Files for bulk insert.

        Idempotent — skips creation when a challenge with the same name
        already exists.  Call :func:`flush_all` after processing every
        definition to commit in a single batch.

        Returns:
            (challenge, created): The ``Challenges`` row and a boolean
            indicating whether it was newly created.
        """
        existing = Challenges.query.filter_by(
            name=self.name, category=self.category
        ).first()
        if existing:
            if existing.position != position:
                existing.position = position
                db.session.add(existing)
            log.info("SKIP   %s (already exists, id=%d)", self.name, existing.id)
            return existing, False

        challenge = Challenges(
            name=self.name,
            category=self.category,
            value=self.value,
            description=self.description,
            max_attempts=self.max_attempts,
            type="standard",
            state=self.state,
            requirements=self.requirements,
            position=position,
        )
        db.session.add(challenge)
        db.session.flush()  # populate challenge.id for FK references

        related = []
        for i in range(self.flag_count):
            related.append(
                Flags(
                    challenge_id=challenge.id,
                    type="static",
                    content=self.generate_flag(i, secret_key),
                    data="case_insensitive",
                )
            )

        for tag_value in self.tags:
            related.append(Tags(challenge_id=challenge.id, value=tag_value))

        for file_loc in self.files:
            related.append(
                ChallengeFiles(challenge_id=challenge.id, location=file_loc)
            )

        db.session.bulk_save_objects(related)
        log.info(
            "STAGE  %s (id=%d, flags=%d, tags=%d)",
            self.name,
            challenge.id,
            self.flag_count,
            len(self.tags),
        )
        return challenge, True

    def __repr__(self):
        return (
            f"<{self.__class__.__name__} "
            f"name={self.name!r} cat={self.category!r} "
            f"val={self.value} flags={self.flag_count}>"
        )


# ── Subclasses ───────────────────────────────────────────────────────────────


class RankingChallenge(SeedChallenge):
    """Challenge awarded for placing in a ranked event.

    The description is auto-generated from the placement ordinal::

        "After placing 1st in this event, your event lead will provide
         a code to you. Submit that code here to earn your points."
    """

    DESCRIPTION_TEMPLATE = (
        "After placing {ordinal} in this event, your event lead will "
        "provide a code to you. Submit that code here to earn your points."
    )

    def __init__(self, placement, **kwargs):
        self.placement = placement
        super().__init__(**kwargs)

    def build_description(self):
        return self.DESCRIPTION_TEMPLATE.format(ordinal=ordinal(self.placement))

    @classmethod
    def for_event(
        cls,
        category,
        placements,
        tags=None,
        max_attempts=0,
        flag_count=1,
    ):
        """Create one ``RankingChallenge`` per placement position.

        The challenge name is simply the ordinal placement (e.g. "1st Place").
        Use *category* to group them under the event.

        Args:
            category:     Challenge category / event name shown in the UI.
            placements:   Iterable of ``(place, value)`` tuples.
                          Example: ``[(1, 100), (2, 75), (3, 50), (4, 25)]``
            tags:         Tag strings applied to every generated challenge.
            max_attempts: Max submission attempts (0 = unlimited).
            flag_count:   Flags generated per placement challenge (default 1).

        Returns:
            List of ``RankingChallenge`` instances.
        """
        return [
            cls(
                placement=place,
                name=f"{ordinal(place)} Place",
                category=category,
                value=value,
                flag_count=flag_count,
                max_attempts=max_attempts,
                tags=tags or [],
            )
            for place, value in placements
        ]


class TournamentChallenge(SeedChallenge):
    """Generator for a full single-elimination bracket.

    Given *participants* (must be a power of 2), produces one challenge per
    round with increasing point values and the correct number of match flags.

    Example for ``participants=16, base_value=50``::

        Round of 16   → 8 flags, 50 pts
        Quarterfinals → 4 flags, 100 pts
        Semifinals    → 2 flags, 150 pts
        Finals        → 1 flag,  200 pts

    Default description per round::

        "Your event lead will provide a code to your team after each
         match in this round. Submit that code here to earn your points."
    """

    DESCRIPTION_TEMPLATE = (
        "Your event lead will provide a code to your team after each "
        "match in this round. Submit that code here to earn your points."
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def build_description(self):
        return self.DESCRIPTION_TEMPLATE

    @classmethod
    def bracket(
        cls,
        category,
        participants,
        base_value=50,
        value_step=50,
        tags=None,
        max_attempts=0,
    ):
        """Generate one challenge per round of a single-elimination bracket.

        Challenge names are the round labels themselves (e.g. "Round of 16",
        "Quarterfinals", "Finals").  Use *category* to group them under
        the event.

        Args:
            category:     Challenge category / event name shown in the UI.
            participants: Number of entrants (must be a power of 2).
            base_value:   Points awarded for the first (largest) round.
            value_step:   Point increase per subsequent round.
            tags:         Tag strings applied to every generated challenge.
            max_attempts: Max submission attempts (0 = unlimited).

        Returns:
            List of ``TournamentChallenge`` instances (one per round),
            ordered from the largest round to the finals.
        """
        if participants < 2 or (participants & (participants - 1)) != 0:
            raise ValueError(
                f"participants must be a power of 2, got {participants}"
            )

        rounds = int(math.log2(participants))
        challenges = []
        for i in range(rounds):
            remaining = participants >> i          # 16, 8, 4, 2
            matches = remaining // 2               # 8, 4, 2, 1
            value = base_value + (i * value_step)  # increasing each round
            round_label = _round_name(remaining)

            challenges.append(
                cls(
                    name=round_label,
                    category=category,
                    value=value,
                    flag_count=matches,
                    max_attempts=max_attempts,
                    tags=tags or [],
                )
            )
        return challenges


class StaticChallenge(SeedChallenge):
    """Challenge with a fixed / custom description.

    Use for trivia, scavenger hunts, participation check-ins, or anything
    that doesn't fit the ranking / tournament templates.  Pass your own
    ``description`` — no auto-generation is performed.
    """

    pass


class ScavengerHuntChallenge(SeedChallenge):
    """Generator for numbered scavenger-hunt items.

    Produces *count* individual challenges ("Egg 1", "Egg 2", …) plus
    an optional set of specially-named challenges (e.g. "Golden Egg 1").
    """

    DESCRIPTION_TEMPLATE = (
        "Find {label} and enter the code to earn your points."
    )

    def build_description(self):
        return self.DESCRIPTION_TEMPLATE.format(label=self.name)

    @classmethod
    def hunt(
        cls,
        category,
        count,
        value=10,
        label="Egg",
        golden_count=0,
        golden_value=50,
        golden_label="Golden Egg",
        tags=None,
        max_attempts=0,
    ):
        """Generate numbered hunt challenges.

        Args:
            category:      Challenge category / event name.
            count:         Number of regular items (e.g. 80).
            value:         Points per regular item.
            label:         Display label for regular items.
            golden_count:  Number of special/golden items.
            golden_value:  Points per golden item.
            golden_label:  Display label for golden items.
            tags:          Tag strings applied to every challenge.
            max_attempts:  Max submission attempts (0 = unlimited).

        Returns:
            List of ``ScavengerHuntChallenge`` instances.
        """
        challenges = []
        for i in range(1, count + 1):
            challenges.append(
                cls(
                    name=f"{label} {i}",
                    category=category,
                    value=value,
                    flag_count=1,
                    max_attempts=max_attempts,
                    tags=tags or [],
                )
            )
        for i in range(1, golden_count + 1):
            challenges.append(
                cls(
                    name=f"{golden_label} {i}",
                    category=category,
                    value=golden_value,
                    flag_count=1,
                    max_attempts=max_attempts,
                    tags=tags or [],
                )
            )
        return challenges


class CheckInChallenge(SeedChallenge):
    """Zero-point gate challenge.

    A single flag, 0 points, unlimited attempts.  Designed as a prerequisite
    that unlocks all other challenges once solved.  Uses a hardcoded flag
    rather than a generated one.
    """

    HARDCODED_FLAG = "GW26{ready_to_win}"

    def __init__(self, name, category, description, **kwargs):
        kwargs.setdefault("value", 0)
        kwargs.setdefault("flag_count", 1)
        kwargs.setdefault("max_attempts", 0)
        super().__init__(
            name=name,
            category=category,
            description=description,
            **kwargs,
        )

    def generate_flag(self, index, secret_key):
        return self.HARDCODED_FLAG


def set_prerequisites(prerequisite_name, dependents):
    """Set a prerequisite on the given challenges.

    *dependents* is a list of ``(name, category)`` tuples.  Must be called
    after all challenges have been created so that DB ids are available.
    Skips challenges that already have requirements set or don't exist.
    """
    prereq = Challenges.query.filter_by(name=prerequisite_name).first()
    if prereq is None:
        log.warning("Prerequisite %r not found — skipping", prerequisite_name)
        return

    count = 0
    for name, category in dependents:
        chal = Challenges.query.filter_by(name=name, category=category).first()
        if chal is None:
            continue
        if chal.requirements and chal.requirements.get("prerequisites"):
            continue
        chal.requirements = {"prerequisites": [prereq.id]}
        count += 1
    db.session.commit()
    log.info(
        "SET prerequisites: %s (id=%d) → %d challenges",
        prerequisite_name,
        prereq.id,
        count,
    )

#!/usr/bin/env python
"""Seed the CTFd database with Golden Web 2026 challenges.

Usage:
    python seed.py                          # seed challenges
    python seed.py --print-flags            # print all flags (no DB writes)
    python seed.py --export-csv             # write flags.csv grouped by event
    SEED_SECRET=mykey python seed.py        # use a custom HMAC key

Environment variables:
    SEED_SECRET   HMAC key used for deterministic flag generation.
                  Defaults to "golden-web-2026-default-key".
"""

import csv
import logging
import os
import sys
from collections import OrderedDict

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-5s  %(message)s",
)


def main():
    secret_key = os.environ.get("SEED_SECRET", "golden-web-2026-default-key")

    from CTFd import create_app

    app = create_app()

    with app.app_context():
        from CTFd.seeds.golden_web_2026 import CHALLENGES, seed

        if "--print-flags" in sys.argv:
            print_flags(CHALLENGES, secret_key)
            return

        if "--export-csv" in sys.argv:
            out = sys.argv[sys.argv.index("--export-csv") + 1] if len(sys.argv) > sys.argv.index("--export-csv") + 1 else "flags.csv"
            export_csv(CHALLENGES, secret_key, filename=out)
            return

        created, skipped = seed(secret_key)
        print(f"\nDone — {created} created, {skipped} skipped.")


def print_flags(challenges, secret_key):
    """Print every challenge and its flags in a hand-out-friendly format."""
    for chal in challenges:
        print(f"\n{'=' * 64}")
        print(f"  {chal.name}")
        print(f"  Category: {chal.category}  |  Value: {chal.value} pts")
        print(f"  Flags ({chal.flag_count}):")
        for i in range(chal.flag_count):
            print(f"    [{i + 1:>2}]  {chal.generate_flag(i, secret_key)}")
    print(f"\n{'=' * 64}")


def export_csv(challenges, secret_key, filename="flags.csv"):
    """Write a CSV grouped by category (event) with one row per challenge.

    Columns: Event, Challenge, Points, Flag 1, Flag 2, …, Flag N
    """
    # Find the max flag count so we can size the header
    max_flags = max(c.flag_count for c in challenges)

    # Group by category, preserving definition order
    groups = OrderedDict()
    for chal in challenges:
        groups.setdefault(chal.category, []).append(chal)

    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)

        flag_headers = [f"Flag {i + 1}" for i in range(max_flags)]
        writer.writerow(["Event", "Challenge", "Points"] + flag_headers)

        for category, chals in groups.items():
            for chal in chals:
                flags = [
                    chal.generate_flag(i, secret_key)
                    for i in range(chal.flag_count)
                ]
                # Pad with empty strings so every row has the same column count
                flags += [""] * (max_flags - len(flags))
                writer.writerow([category, chal.name, chal.value] + flags)

    print(f"Exported {sum(len(v) for v in groups.values())} challenges to {filename}")


if __name__ == "__main__":
    main()

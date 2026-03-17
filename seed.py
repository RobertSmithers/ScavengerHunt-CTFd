#!/usr/bin/env python
"""Seed the CTFd database with Golden Web 2026 challenges.

Usage:
    python seed.py                                  # seed all unlocked categories
    python seed.py --all                            # seed everything (ignore locks)
    python seed.py --only "Murph - 0930"            # seed only specific categories
    python seed.py --reseed "Murph - 0930"          # delete + reseed specific categories
    python seed.py --list                           # show all categories & lock status
    python seed.py --print-flags                    # print all flags (no DB writes)
    python seed.py --export-csv                     # write flags.csv grouped by event
    SEED_SECRET=mykey python seed.py                # use a custom HMAC key

Environment variables:
    SEED_SECRET   HMAC key used for deterministic flag generation.
                  Defaults to "golden-web-2026-default-key".
"""

import argparse
import csv
import logging
import os
from collections import OrderedDict

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-5s  %(message)s",
)


def build_parser():
    p = argparse.ArgumentParser(
        description="Seed Golden Web 2026 challenges into CTFd.",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--all", action="store_true",
        help="Seed every category, including locked ones.",
    )
    group.add_argument(
        "--only", nargs="+", metavar="CATEGORY",
        help="Seed only these categories (must already be clean).",
    )
    group.add_argument(
        "--reseed", nargs="+", metavar="CATEGORY",
        help="Delete and re-create these categories. Refuses locked categories "
             "unless --force is also passed.",
    )
    group.add_argument(
        "--list", action="store_true", dest="list_categories",
        help="List all categories with their lock status and exit.",
    )
    group.add_argument(
        "--print-flags", action="store_true",
        help="Print all flags to stdout (no DB writes).",
    )
    group.add_argument(
        "--export-csv", nargs="?", const="flags.csv", metavar="FILE",
        help="Export flags to a CSV file (default: flags.csv).",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Allow --reseed to operate on locked categories.",
    )
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    secret_key = os.environ.get("SEED_SECRET", "golden-web-2026-default-key")

    from CTFd import create_app

    app = create_app()

    with app.app_context():
        from CTFd.seeds.golden_web_2026 import (
            CHALLENGES,
            LOCKED_CATEGORIES,
            get_categories,
            seed,
        )

        # ── List categories ──────────────────────────────────────────
        if args.list_categories:
            cats = get_categories()
            print(f"\n{'Category':<45} {'Chals':>5}  Status")
            print("-" * 62)
            for cat, (count, locked) in cats.items():
                status = "LOCKED" if locked else "unlocked"
                print(f"  {cat:<43} {count:>5}  {status}")
            print()
            return

        # ── Print flags (no DB) ──────────────────────────────────────
        if args.print_flags:
            print_flags(CHALLENGES, secret_key)
            return

        # ── Export CSV (no DB) ───────────────────────────────────────
        if args.export_csv:
            export_csv(CHALLENGES, secret_key, filename=args.export_csv)
            return

        # ── Reseed specific categories ───────────────────────────────
        if args.reseed:
            blocked = set(args.reseed) & LOCKED_CATEGORIES
            if blocked and not args.force:
                print(f"ERROR: Refusing to reseed locked categories: {', '.join(sorted(blocked))}")
                print("       Use --force to override, or remove them from LOCKED_CATEGORIES.")
                raise SystemExit(1)
            created, skipped = seed(secret_key, categories=args.reseed, reseed=True)
            print(f"\nReseed done — {created} created, {skipped} skipped.")
            return

        # ── Seed only specific categories ────────────────────────────
        if args.only:
            created, skipped = seed(secret_key, categories=args.only)
            print(f"\nDone — {created} created, {skipped} skipped.")
            return

        # ── Seed all (optionally ignoring locks) ─────────────────────
        if args.all:
            categories = None  # seed() with None + we pass all cats
            all_cats = [c.category for c in CHALLENGES]
            created, skipped = seed(secret_key, categories=all_cats)
        else:
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

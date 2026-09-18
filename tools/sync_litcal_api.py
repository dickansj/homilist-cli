#!/bin/sh
''''exec "$(dirname "$0")/../env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env

"""Keep the offline fallback answerable for dates it cannot compute on its own.

liturgical.py and lectionary.py are pure and offline -- exactly why they are
tier 3 of new.py's fallback chain -- but liturgical.py says so itself: it "does
not know the whole sanctoral calendar," and returns None rather than a guess.
A homily scaffolded fully offline on one of those dates gets blank metadata.

This script runs separately from new.py, on its own schedule, while there is a
network. For every date in range where the offline calendar and lectionary
table would currently come up empty, it asks LiturgicalCalendarAPI (tier 2) for
the readings and writes what it finds to tmp/litcal_api/gap_fill.json -- a
small cache that tier 3 checks before giving up. The fix lands without editing
liturgical.py's tables by hand, and without tier 3 depending on a network at
the moment a homily is actually scaffolded.

    tools/sync_litcal_api.py             # today through ~13 months out
    tools/sync_litcal_api.py --days 30   # a narrower window
    tools/sync_litcal_api.py --refresh   # recheck dates already cached
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lectionary  # noqa: E402
import litcal_api  # noqa: E402
import liturgical  # noqa: E402


def offline_gap(target_date):
    """Whether tier 3 would currently come up empty for this date."""
    number = liturgical.lectionary_number(target_date)
    if not number:
        return True
    return not lectionary.readings_line(number, liturgical.ferial_year(target_date))


def sync(days, refresh):
    path = litcal_api.gap_fill_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    table = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}

    start = datetime.date.today()
    checked = filled = 0
    for offset in range(days):
        d = start + datetime.timedelta(days=offset)
        iso = d.isoformat()
        if iso in table and not refresh:
            continue
        if not offline_gap(d):
            continue

        checked += 1
        try:
            found = litcal_api.lookup(d)
        except litcal_api.LitCalAPIError as exc:
            print(f"  {iso}: {exc.message}")
            continue
        if found:
            table[iso] = found
            filled += 1
            print(f"  {iso}: {found['name']}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=1, sort_keys=True)
    print(f"\nwrote {path}")
    print(f"  {checked} offline gap(s) checked, {filled} filled ({len(table)} cached total)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=396,
                     help="how many days ahead to check (default: ~13 months)")
    ap.add_argument("--refresh", action="store_true",
                     help="recheck dates already in the cache")
    args = ap.parse_args()
    return sync(args.days, args.refresh)


if __name__ == "__main__":
    sys.exit(main())

#!/bin/sh
''''exec "$(dirname "$0")/../env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env

"""Keep the offline fallback answerable for dates it cannot compute on its own.

liturgical.py and lectionary.py are pure and offline -- exactly why new.py
trusts them when neither live source is around to ask -- but liturgical.py
says so itself: it "does not know the whole sanctoral calendar," and returns
None rather than a guess. A homily scaffolded fully offline on one of those
dates gets blank metadata.

This script runs separately from new.py, on its own schedule, while there is a
network. For every date in range where the offline calendar and lectionary
table would currently come up empty, it tries USCCB once -- the same one
attempt new.py makes, and about as likely to land: Shane's own words closing
the PR this project once sent him were that the bot challenge means "a script
never passes it; the occasional 200 is an edge-cache hit, not a change of
heart" -- and falls back to LiturgicalCalendarAPI when USCCB doesn't answer.
Either way, what it finds is written to tmp/litcal_api/overrides.json: a
curated cache new.py checks before asking either live source again.

The same file also holds corrections, for a date the offline table answers
*wrong* rather than not at all -- catholic-resources.org's own page gives
1 Cor 15:12-22 for lectionary 447/Year II, which is not what USCCB or the API
say. new.py saves one automatically when its conflict prompt is answered;
--patch adds one by hand, for a bad entry noticed some other way.

    tools/sync_litcal_api.py                  # today through ~13 months out
    tools/sync_litcal_api.py --days 30        # a narrower window
    tools/sync_litcal_api.py --refresh        # recheck dates already cached
    tools/sync_litcal_api.py --patch 2026-09-18 --readings \\
        "1 Cor 15:12-20; Ps 17:1bcd, 6-7, 8b+15; Luke 8:1-3"
"""

import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import homilist  # noqa: E402
import lectionary  # noqa: E402
import litcal_api  # noqa: E402
import liturgical  # noqa: E402

import requests  # noqa: E402

# Basic courtesy between USCCB attempts across a run that may try a dozen
# dates -- not a strategy for passing the challenge, which throttling does not
# affect either way (see the module docstring).
_USCCB_INTERVAL = 2.0


def offline_gap(target_date):
    """Whether the offline calendar and lectionary table would currently come
    up empty for this date."""
    number = liturgical.lectionary_number(target_date)
    if not number:
        return True
    return not lectionary.readings_line(number, liturgical.ferial_year(target_date))


def try_usccb(target_date, last=[0.0]):
    """One opportunistic attempt at USCCB for this date, or None. Same one
    attempt new.py makes at scaffolding time -- not a retry loop."""
    wait = _USCCB_INTERVAL - (time.monotonic() - last[0])
    if wait > 0:
        time.sleep(wait)
    last[0] = time.monotonic()

    url = target_date.strftime(homilist.USCCB_WEB_TEMPLATE)
    try:
        res = requests.get(url, timeout=20)
        if not res.ok:
            return None
        _, title, readings = homilist.scrape_readings(res.text)
    except (homilist.ScrapingException, requests.RequestException):
        return None
    return {"name": title, "readings": homilist.normalize_citations(readings)}


def sync(days, refresh):
    start = datetime.date.today()
    checked = filled = 0
    for offset in range(days):
        d = start + datetime.timedelta(days=offset)
        if litcal_api.override_lookup(d) and not refresh:
            continue
        if not offline_gap(d):
            continue

        checked += 1
        found = try_usccb(d)
        source = "usccb"
        if not found:
            try:
                found = litcal_api.lookup(d)
            except litcal_api.LitCalAPIError as exc:
                print(f"  {d.isoformat()}: {exc.message}")
                continue
            source = "api"

        if found:
            litcal_api.save_override(d, found, source)
            filled += 1
            print(f"  {d.isoformat()}: {found['name']} ({source})")

    print(f"\nwrote {litcal_api.override_path()}")
    print(f"  {checked} offline gap(s) checked, {filled} filled")
    return 0


def patch(iso, readings_text, name):
    d = datetime.date.fromisoformat(iso)
    entry = {"name": name or liturgical.describe(d),
             "readings": homilist.normalize_citations(readings_text)}
    litcal_api.save_override(d, entry, "manual")
    print(f"saved {iso}: {entry['name']}: {entry['readings']}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=396,
                     help="how many days ahead to check (default: ~13 months)")
    ap.add_argument("--refresh", action="store_true",
                     help="recheck dates already in the cache")
    ap.add_argument("--patch", metavar="YYYY-MM-DD",
                     help="add or correct one date's entry by hand")
    ap.add_argument("--readings", metavar="TEXT", help="the reading line for --patch")
    ap.add_argument("--name", metavar="TEXT",
                     help="the day's name for --patch (default: the offline "
                     "calendar's short form)")
    args = ap.parse_args()
    if args.patch:
        if not args.readings:
            ap.error("--patch needs --readings")
        return patch(args.patch, args.readings, args.name)
    return sync(args.days, args.refresh)


if __name__ == "__main__":
    sys.exit(main())

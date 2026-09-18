"""LiturgicalCalendarAPI: the live fallback between USCCB and the offline calendar.

USCCB is scraped one date at a time and answers unreliably (see new.py). This
project (https://github.com/Liturgical-Calendar/LiturgicalCalendarAPI) computes
the same Roman Rite calendar independently and serves it as JSON, lectionary
citations included -- so a USCCB failure does not have to fall straight to the
offline computus, which by its own admission does not know the whole sanctoral
calendar.

Neither live source is trusted blindly. When USCCB doesn't answer, new.py asks
this API and the offline calendar and lectionary table for the same date and
checks whether they agree -- see citations_agree(). When they don't (an entry
in the offline table can just be wrong -- catholic-resources.org's own page
gives 1 Cor 15:12-22 for lectionary 447/Year II, which is not what USCCB or
this API say), new.py asks rather than silently trusting one of them.

A request returns a whole liturgical year at once (Advent through the following
Christ the King), so it is cached per (host, nation, requested year) under tmp/
rather than re-fetched per date -- one request covers roughly fifty homilies. A
date in late Advent belongs to the *next* liturgical year's response, so
lookup() tries the requested civil year first and the year after it before
giving up. The host is part of the cache key, not just nation and year, so that
LITCAL_API_URL_TEMPLATE pointing the test suite at a closed port cannot be
served a stale answer left behind by a real request.

Like lectionary_string, the API's own wording for a day is never written to
that field -- it is not USCCB's wording, and the convention across this archive
is that lectionary_string is USCCB's or nothing. This module returns "name" for
display only; new.py prints it but does not store it.

overrides.json (tmp/litcal_api/overrides.json) is the curated answer for one
date, checked before either live source is asked again. Two things end up in
it: tools/sync_litcal_api.py's gap-filling, for a date the offline route can't
answer at all, and a correction -- either saved automatically when new.py's
conflict prompt is answered, or added by hand with
`tools/sync_litcal_api.py --patch`, for a date the offline route answers
*wrong*. Once a date is in there, it is settled: new.py stops re-asking.

Keyed by the full ISO date, not a liturgical label or month-day, so a movable
feast is safe: the 2026 Easter Vigil's entry lives under "2026-04-04" and is
never consulted for 2027's Vigil ("2027-03-27"). The cost is that entries
don't generalize across years -- a recurring gap like the Vigil's needs
tools/sync_litcal_api.py to refill it every year, not just once.

    lookup(date, nation="US")        -> {"name", "readings", "first",
                                          "second", "gospel"} or None
    citations_agree(a, b)            -> whether two such results, or the
                                          equivalent from lectionary.py, are
                                          the same reading
    override_lookup(date)            -> the curated entry for a date, if any,
                                          with no network call here
    save_override(date, entry, source) -> write one, merging into the file
"""

import json
import os
from urllib.parse import urlparse

import requests

import homilist

URL_TEMPLATE = os.environ.get(
    "LITCAL_API_URL_TEMPLATE",
    "https://litcal.johnromanodorazio.com/api/dev/calendar/roman/nation/{nation}/{year}?locale=en",
)

# Readings a homilist proclaims, in order. gospel_acclamation is excluded, the
# same way the USCCB scraper skips the Alleluia verse -- neither is a reading.
_READING_KEYS = ("first_reading", "responsorial_psalm", "second_reading", "gospel")


class LitCalAPIError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def fetch_year(year, nation="US"):
    """One liturgical year's events, from cache or the network."""
    url = URL_TEMPLATE.format(nation=nation, year=year)
    host = (urlparse(url).netloc or "unknown").replace(":", "_")
    path = os.path.join(homilist.tmp_dir(), "litcal_api", host, f"{nation}_{year}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))

    try:
        res = requests.get(url, timeout=20)
    except requests.RequestException as exc:
        raise LitCalAPIError(f"couldn't reach LiturgicalCalendarAPI ({exc})") from exc
    if not res.ok:
        raise LitCalAPIError(f"LiturgicalCalendarAPI returned {res.status_code} for {url}")
    try:
        data = res.json()
    except ValueError as exc:
        raise LitCalAPIError(f"LiturgicalCalendarAPI response wasn't JSON ({exc})") from exc

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def _select_primary(entries):
    """Which of the day's events actually governs the readings.

    A date can carry several: a ferial weekday plus one or more optional
    memorials, for instance. An optional memorial does not displace the day's
    own readings -- that is what makes it optional -- so it only wins here when
    it is the only thing on the date. An obligatory memorial or higher (grade 3+)
    does displace the weekday and wins outright. A vigil Mass is a distinct
    liturgy for the evening before, not the day itself, so it is set aside
    unless it is all there is -- and so is the Chrism Mass on Holy Thursday,
    which is the bishop's once-a-diocese liturgy, not the evening Mass every
    parish actually celebrates that day. Both share Holy Thursday's date and
    its grade, so without this a tie-break by grade alone could pick either.
    """
    candidates = [e for e in entries if not e.get("is_vigil_mass")
                  and "chrism" not in e.get("name", "").lower()] or entries
    obligatory = [e for e in candidates if e.get("grade", 0) >= 3]
    if obligatory:
        return max(obligatory, key=lambda e: e.get("grade", 0))
    weekday = [e for e in candidates if e.get("grade", 0) == 0]
    if weekday:
        return weekday[0]
    return candidates[0]


# The Easter Vigil numbers up to seven Old Testament readings plus an epistle,
# instead of the ordinary first/second/gospel shape -- its own Liturgy of the
# Word, not a variation on a weekday's.
_VIGIL_READING_KEYS = (
    "first_reading", "responsorial_psalm",
    "second_reading", "responsorial_psalm_2",
    "third_reading", "responsorial_psalm_3",
    "fourth_reading", "responsorial_psalm_4",
    "fifth_reading", "responsorial_psalm_5",
    "sixth_reading", "responsorial_psalm_6",
    "seventh_reading", "responsorial_psalm_7",
    "epistle", "responsorial_psalm_epistle",
    "gospel",
)


def _select_readings(readings):
    """The flat reading dict to read from, and the key order to read it in.

    Two shapes need unwrapping before the ordinary four-field order applies. A
    Mass with more than one time of day -- Christmas (night/dawn/day), Easter
    Sunday (day/evening) -- nests a complete readings dict under each instead
    of giving readings directly; "day" is preferred, matching which Mass the
    offline calendar and lectionary table default to for the same dates. And
    the Vigil's numbered shape (detected by `third_reading` or `epistle`,
    neither of which the ordinary shape has) needs the order above instead.
    """
    if readings and all(isinstance(v, dict) for v in readings.values()):
        readings = readings.get("day") or next(iter(readings.values()), {})
    if "third_reading" in readings or "epistle" in readings:
        return readings, _VIGIL_READING_KEYS
    return readings, _READING_KEYS


def _extract(readings):
    """(full reading line, comparison fields) for one entry's readings.

    An appointed reading with an alternate comes back as one field with the two
    citations joined by a bare "|" -- the API's own delimiter, not this
    project's. Splitting on it before normalizing means both book names get
    abbreviated rather than just the first, and folding the pieces back
    together with "or" matches the convention the USCCB scraper already uses
    for the same situation.

    The comparison fields are only first/second/gospel, not the full line: the
    psalm's verse-list punctuation differs by source even when the passage
    agrees ("8b+15" against "8b, 15"), which would read as a false conflict,
    and the Vigil's extra Old Testament readings only ever come from this API
    in the first place, so there is nothing on the other side to compare them
    to.
    """
    readings, keys = _select_readings(readings)
    parts, fields = [], {}
    for key in keys:
        raw = readings.get(key, "")
        if not raw:
            continue
        alternates = [homilist.normalize_citations(alt.strip())
                      for alt in raw.split("|") if alt.strip()]
        text = " or ".join(alternates)
        parts.append(text)
        fields[key] = text
    compare = {
        "first": fields.get("first_reading", ""),
        "second": fields.get("second_reading", "") or fields.get("epistle", ""),
        "gospel": fields.get("gospel", ""),
    }
    return "; ".join(parts), compare


def citations_agree(a, b):
    """Whether two {"first", "second", "gospel"} field sets are the same
    reading. Either side may come from this module or from
    lectionary.readings_for() (normalized the same way by the caller) -- the
    shape is what matters, not the source."""
    return all(a.get(k, "") == b.get(k, "") for k in ("first", "second", "gospel"))


def parse(data, target_date):
    """Pure: one year's API response -> this date's result, or None.

    Takes already-fetched JSON so it can be tested against a small fixture
    without a network, the same way homilist.scrape_readings() is tested
    against saved USCCB pages.
    """
    iso = target_date.isoformat()
    entries = [e for e in data.get("litcal", []) if e.get("date", "")[:10] == iso]
    if not entries:
        return None
    primary = _select_primary(entries)
    line, compare = _extract(primary.get("readings") or {})
    if not line:
        return None
    return {"name": primary.get("name", ""), "readings": line, **compare}


def lookup(target_date, nation="US"):
    """The live fallback: fetch, parse, or None. Raises LitCalAPIError on a
    network or response failure -- the caller decides what "no answer" means."""
    for year in (target_date.year, target_date.year + 1):
        result = parse(fetch_year(year, nation), target_date)
        if result:
            return result
    return None


def override_path():
    return os.path.join(homilist.tmp_dir(), "litcal_api", "overrides.json")


_OVERRIDES = None


def _load_overrides():
    global _OVERRIDES
    if _OVERRIDES is None:
        path = override_path()
        _OVERRIDES = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    return _OVERRIDES


def override_lookup(target_date):
    """The curated entry for a date, if any, with no network call here. new.py
    checks this before asking either live source again -- see the module
    docstring for what ends up in it and why."""
    return _load_overrides().get(target_date.isoformat())


def save_override(target_date, entry, source):
    """Write one entry, merging into the file rather than replacing it.

    `source` is a short provenance tag ("api", "api+usccb", "usccb", "manual",
    "resolved") -- not consulted by new.py, but worth keeping around for
    whoever next wonders where a date's answer came from.
    """
    global _OVERRIDES
    path = override_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    table = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    table[target_date.isoformat()] = {**entry, "source": source}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=1, sort_keys=True)
    _OVERRIDES = table

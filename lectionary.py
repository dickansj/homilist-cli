"""Readings keyed by lectionary number.

`liturgical.py` turns a date into a lectionary number. This turns that number
into the readings, from the tables Felix Just SJ publishes at
<https://catholic-resources.org/Lectionary/>, which are the only public source
found that is keyed by number rather than by date.

The table is fetched once -- seven pages, not one request per homily -- and
cached on disk, so every later lookup is local. That is the whole reason this
works where the USCCB scraper did not: the polite request count is bounded by
the number of *pages*, not by the size of the archive.

    readings_for(number, year)   -> {"first": ..., "gospel": ..., ...} or None

`year` is "I" or "II" and matters only in Ordinary Time, where one number
carries two first readings and a single Gospel.

The cache is not committed. It is someone else's compilation of the lectionary,
so it is fetched on demand rather than redistributed here.
"""

import json
import os
import re

import homilist

_TABLE = None


def cache_path():
    return os.path.join(homilist.tmp_dir(), "lectionary", "readings.json")


def _load():
    global _TABLE
    if _TABLE is None:
        path = cache_path()
        _TABLE = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    return _TABLE


def available():
    """Whether the table has been fetched. Nothing here works without it."""
    return bool(_load())


# The source's placeholders where a row does not carry its own readings: a
# cross-reference to another page, or a note that the readings are chosen from
# a range of options (All Souls, ritual Masses). Neither is a citation.
PLACEHOLDER = re.compile(r"^\s*(\(|\[|\.\s*$|see\b)", re.I)


def is_placeholder(entry):
    """A row that names no readings of its own -- or names a menu of them.
    Two alternates ("Matt 10:17-22 or Luke 1:26-38") is an appointed choice;
    All Souls lists thirteen first readings, which is a list to choose from."""
    if not entry:
        return True
    for key in ("first", "gospel"):
        text = entry.get(key, "") or ""
        if PLACEHOLDER.match(text) or text.count(" or ") >= 3:
            return True
    return False


def readings_for(number, year=None):
    """The readings for a lectionary number, or None if the table cannot say.

    Ordinary Time weekdays carry two first readings for one number, so `year`
    picks between them; everywhere else it is ignored. Asking for an OT number
    without a year is ambiguous rather than wrong, so it returns None instead of
    silently choosing one. So does a number whose readings are chosen from
    options: the choice is the preacher's.
    """
    if number is None:
        return None
    entry = _load().get(str(number))
    if not entry:
        return None
    if isinstance(entry, dict) and {"I", "II"} & set(entry):
        entry = entry.get(year) if year in ("I", "II") else None
    return None if is_placeholder(entry) else entry


def readings_line(number, year=None):
    """The whole liturgy of the word, in the order it is proclaimed.

    This is what the `readings` field holds -- psalm included, unlike
    `preached_line`, which is the pruned form you actually preach on.
    """
    entry = readings_for(number, year)
    if not entry:
        return ""
    parts = [entry.get("first", ""), entry.get("psalm", ""),
             entry.get("second", ""), entry.get("gospel", "")]
    return "; ".join(homilist.normalize_citations(p) for p in parts if p)


def preached_line(number, year=None):
    """First reading and Gospel, in the pruned form the `preached` field wants.

    The psalm and the verse before the Gospel are dropped: `preached` is what
    was preached on, not the whole liturgy of the word.
    """
    entry = readings_for(number, year)
    if not entry:
        return ""
    parts = [entry.get("first", ""), entry.get("second", ""), entry.get("gospel", "")]
    return "; ".join(homilist.normalize_citations(p) for p in parts if p)

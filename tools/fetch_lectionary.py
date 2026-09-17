#!/bin/sh
''''exec "$(dirname "$0")/../env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env

"""Build the lectionary-number -> readings table, once.

    tools/fetch_lectionary.py            # fetch what is missing, then build
    tools/fetch_lectionary.py --refresh  # re-fetch every page
    tools/fetch_lectionary.py --show 372 # what the table says for a number

Source: the tables Felix Just SJ publishes at catholic-resources.org, which are
keyed by lectionary number. Fourteen pages cover the whole cycle, so the request
count is bounded by the source's size rather than the archive's -- which is the
difference between this and the per-date USCCB lookup that a script cannot make.

Pages are cached as HTML and the parsed table as JSON, both under tmp/ and
neither committed: this is someone else's compilation, fetched on demand rather
than redistributed.
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import homilist  # noqa: E402
import lectionary  # noqa: E402

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

BASE = "https://catholic-resources.org/Lectionary/"
USER_AGENT = ("homilist-cli/1.0 (personal homily archive; "
              "https://github.com/dickansj)")
INTERVAL = 1.5

# (filename, year cycle for Ordinary Time weekdays). None where the number is
# unambiguous on its own.
PAGES = [
    ("2002USL-Weekdays-OT-I.htm", "I"),
    ("2002USL-Weekdays-OT-II.htm", "II"),
    ("2002USL-Weekdays-Lent.htm", None),
    ("2002USL-Weekdays-AdventChristmas.htm", None),
    ("2002USL-Weekdays-Easter.htm", None),
    ("2002USL-Sanctoral.htm", None),
    ("1998USL-Solemnities.htm", None),
    # Sundays and solemnities. Their numbers are already cycle-specific -- 22 is
    # the first Sunday of Lent in Year A and nothing else -- so no year split.
    ("1998USL-Advent.htm", None),
    ("1998USL-Christmas.htm", None),
    ("1998USL-Lent.htm", None),
    ("1998USL-Easter.htm", None),
    ("1998USL-OrdinaryA.htm", None),
    ("1998USL-OrdinaryB.htm", None),
    ("1998USL-OrdinaryC.htm", None),
]

LECT_NUMBER = re.compile(r"^(\d{1,3})")


class FetchError(RuntimeError):
    pass


def cache_dir():
    return os.path.join(homilist.tmp_dir(), "lectionary")


def fetch(filename, refresh=False, last=[0.0]):
    path = os.path.join(cache_dir(), filename)
    if os.path.exists(path) and not refresh:
        return open(path, encoding="utf-8", errors="replace").read()
    os.makedirs(cache_dir(), exist_ok=True)
    wait = INTERVAL - (time.monotonic() - last[0])
    if wait > 0:
        time.sleep(wait)
    last[0] = time.monotonic()
    res = requests.get(BASE + filename, timeout=30,
                       headers={"User-Agent": USER_AGENT})
    if not res.ok:
        raise FetchError(f"{res.status_code} fetching {filename}")
    with open(path, "wb") as f:
        f.write(res.content)
    print(f"  fetched {filename} ({len(res.content):,} bytes)")
    return res.content.decode("utf-8", errors="replace")


def header_map(cells):
    """Column name -> index, for the fields worth keeping."""
    wanted = {
        "first": ("first reading",),
        "second": ("second reading",),
        "psalm": ("responsorial psalm", "psalm"),
        "gospel": ("gospel",),
        # NOT "date": the first column is the calendar date, and matching it
        # here meant the cycle letter was looked for in "12/29/24".
        "day": ("sunday or feast", "sunday", "feast", "day", "celebration"),
    }
    out = {}
    for i, cell in enumerate(cells):
        low = cell.lower().strip()
        for key, names in wanted.items():
            if key not in out and any(low.startswith(n) for n in names):
                # "Verse before the Gospel" must not be taken as the Gospel.
                if key == "gospel" and "verse" in low:
                    continue
                out[key] = i
    return out


# The tables annotate their cells for readers: a title after an en dash, an
# editorial "( new )" or "( diff )", an "opt:" prefix on optional forms. All of
# it is useful on the page and none of it belongs in a citation field.
OPTIONAL = re.compile(r"^\s*opt\.?:", re.I)
ANNOTATION = re.compile(r"\s*\(\s*(?:new|diff|abbrev|opt|longer|shorter)[^)]*\)", re.I)
TITLE_TAIL = re.compile(r"\s+[–—]\s+.*$")


def clean(text):
    text = ANNOTATION.sub("", text or "")
    text = re.sub(r"^\s*opt\.?:\s*", "", text, flags=re.I)
    text = TITLE_TAIL.sub("", text)
    return " ".join(text.split()).strip(" ;,")


def parse(html):
    """[(lectionary number, entry)] from one page -- every row, in order.

    Rows are not collapsed here. One number can head several: Pentecost and the
    Holy Family each have one row per Sunday cycle, and the Holy Family's
    readings differ completely between them. Collapsing early lost that.
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for table in soup.find_all("table"):
        columns, lect_col = None, None
        for row in table.find_all("tr"):
            cells = [" ".join(c.get_text(" ", strip=True).split())
                     for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            # The weekday tables head this column "Lect. #"; the Sunday
            # tables head it just "#". Matching only the first quietly parsed
            # every Sunday page to nothing.
            def is_number_column(cell):
                low = cell.lower().strip()
                return low.startswith("lect") or low in ("#", "no.", "number")

            if any(is_number_column(c) for c in cells):
                columns = header_map(cells)
                lect_col = next(i for i, c in enumerate(cells) if is_number_column(c))
                continue
            if columns is None or lect_col is None or lect_col >= len(cells):
                continue
            m = LECT_NUMBER.match(cells[lect_col])
            if not m:
                continue
            entry, optional = {}, False
            for key, index in columns.items():
                if index < len(cells) and cells[index] not in ("", "x", "—", "-"):
                    raw = cells[index]
                    if key in ("first", "gospel") and OPTIONAL.match(raw):
                        optional = True
                    entry[key] = raw if key == "day" else clean(raw)
            # Pentecost and the like list alternative forms as separate rows.
            # Stripping "opt:" and taking whichever came first let an optional
            # Gospel stand in for the one actually appointed.
            entry["optional"] = optional
            if entry.get("gospel") or entry.get("first"):
                found.append((m.group(1), entry))
    return found


def best(entries):
    """The appointed form, with any optional alternates recorded beside it.

    Several numbers head more than one row: the Holy Family is appointed Sir 3
    and Matt 2 in every cycle, with optional alternates for B and C. Choosing
    between them is the preacher's call, so the table gives the appointed form
    and says that others exist rather than picking silently.
    """
    appointed = next((e for e in entries if not e.get("optional")), entries[0])
    alternates = [e for e in entries if e is not appointed]
    if alternates:
        appointed = dict(appointed)
        appointed["alternates"] = [
            "; ".join(x for x in (e.get("first",""), e.get("gospel","")) if x)
            for e in alternates]
    return appointed


def build(refresh=False):
    table = {}
    for filename, year in PAGES:
        try:
            html = fetch(filename, refresh)
        except (FetchError, requests.RequestException) as exc:
            print(f"  ⚠️  {filename}: {exc}")
            continue
        page = parse(html)
        print(f"  {filename}: {len(page)} rows")
        rows = {}
        for number, entry in page:
            rows.setdefault(number, []).append(entry)
        for number, entries in rows.items():
            if year:
                # Ordinary Time weekdays: one number, two first readings.
                slot = table.get(number)
                if not isinstance(slot, dict) or not {"I", "II"} & set(slot):
                    slot = {}
                slot[year] = best(entries)
                table[number] = slot
            else:
                # A number can appear on two pages, one of them a placeholder
                # pointing at the other -- "( see the Sunday Lectionary )". The
                # real entry wins whichever page came first.
                chosen = best(entries)
                if number not in table or (lectionary.is_placeholder(table[number])
                                           and not lectionary.is_placeholder(chosen)):
                    table[number] = chosen

    path = lectionary.cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=1, sort_keys=True)
    both = sum(1 for v in table.values() if isinstance(v, dict) and "I" in v)
    print(f"\nwrote {path}")
    print(f"  {len(table)} lectionary numbers ({both} with a Year I/II split)")
    return 0


def show(number):
    lectionary._TABLE = None
    for year in (None, "I", "II"):
        entry = lectionary.readings_for(number, year)
        if entry:
            label = f" (Year {year})" if year else ""
            print(f"  {number}{label}: {entry}")
    line_i = lectionary.preached_line(number, "I")
    line_ii = lectionary.preached_line(number, "II")
    if line_i or line_ii:
        print(f"\n  preached line — Year I:  {line_i or '(none)'}")
        print(f"                  Year II: {line_ii or '(none)'}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-fetch every page")
    ap.add_argument("--show", metavar="N", help="print one number and stop")
    args = ap.parse_args()
    if args.show:
        return show(args.show)
    return build(args.refresh)


if __name__ == "__main__":
    sys.exit(main())

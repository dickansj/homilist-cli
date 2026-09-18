#!/usr/bin/env python3
"""Tests for the parts of homilist-cli that can fail quietly.

    ./tests/units.py          (or: env/bin/python tests/units.py)

Priorities, in order:

  1. The USCCB scraper. Seven CSS selectors into someone else's website, and its
     failure mode is a homily file with blank metadata -- noticed at the wrong
     moment. Tested against saved fixtures so it needs no network and so the
     fixture doubles as a record of what the page looked like when it worked.
  2. Frontmatter round-tripping. pandoc reads the same block as real YAML, so
     anything we write that pandoc rejects makes check.py a tool that lies. This
     bug class has already appeared twice.
  3. Directory resolution. Getting the precedence backwards writes homilies to
     the wrong place.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import homilist  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")

failures = []
checked = 0


def check(name, got, want):
    global checked
    checked += 1
    if got != want:
        failures.append(f"  {name}\n      got  {got!r}\n      want {want!r}")


def raises(name, fn, message_contains=""):
    global checked
    checked += 1
    try:
        fn()
    except homilist.ScrapingException as exc:
        if message_contains and message_contains not in str(exc):
            failures.append(f"  {name}: wrong message {str(exc)!r}")
        return
    except Exception as exc:  # noqa: BLE001
        failures.append(f"  {name}: raised {type(exc).__name__}, want ScrapingException")
        return
    failures.append(f"  {name}: did not raise")


# ---------------------------------------------------------------- scraper

def test_scraper():
    html = open(os.path.join(FIXTURES, "usccb-sunday.html"), encoding="utf-8").read()
    number, title, readings = homilist.scrape_readings(html)

    check("lectionary number is an int", number, 112)
    check("day title", title, "Eighteenth Sunday In Ordinary Time")
    # The Alleluia is skipped: it is not preached on.
    check("readings, Alleluia skipped", readings,
          "Isaiah 55:1-3; Psalm 145:8-9, 15-16, 17-18; "
          "Romans 8:35, 37-39; Matthew 14:13-21")
    check("Alleluia really absent", "Matthew 4:4b" in readings, False)


def test_scraper_alternate():
    """An `Or` block folds into the preceding reading rather than listing alone."""
    html = open(os.path.join(FIXTURES, "usccb-alternate.html"), encoding="utf-8").read()
    _, _, readings = homilist.scrape_readings(html)
    check("alternate folded with 'or'",
          readings.endswith("Matthew 14:13-21 or Matthew 14:22-33"), True)
    check("alternate is not its own entry", readings.count(";"), 3)


def test_scraper_nbsp():
    """USCCB puts non-breaking spaces inside citations; they must be normalized."""
    html = open(os.path.join(FIXTURES, "usccb-sunday.html"), encoding="utf-8").read()
    html = html.replace("Isaiah 55:1-3", "Isaiah 55:1-3")
    _, _, readings = homilist.scrape_readings(html)
    check("nbsp normalized to a space", " " in readings, False)
    check("citation still intact", readings.startswith("Isaiah 55:1-3"), True)


def test_scraper_compound_title():
    """A compound title puts its parenthetical on its own line in the source
    HTML -- "The Commemoration of All the Faithful Departed\\n   (All Souls)"
    -- and `.text` alone carries that newline and indentation into the title.
    Found live: a title scraped this way for real came back with the
    parenthetical on a line of its own, in tmp/litcal_api/overrides.json."""
    html = open(os.path.join(FIXTURES, "usccb-sunday.html"), encoding="utf-8").read()
    html = html.replace(
        "<h2>Eighteenth Sunday In Ordinary Time</h2>",
        "<h2>Eighteenth Sunday In Ordinary Time\n"
        "                    (Some Feast)\n                </h2>")
    _, title, _ = homilist.scrape_readings(html)
    check("embedded newline and indentation collapse to one space", title,
          "Eighteenth Sunday In Ordinary Time (Some Feast)")


def test_scraper_failures():
    """A redesign must raise, not return blank metadata."""
    good = open(os.path.join(FIXTURES, "usccb-sunday.html"), encoding="utf-8").read()

    raises("missing title block raises",
           lambda: homilist.scrape_readings("<html><body></body></html>"),
           "no title block")

    raises("missing h2 raises",
           lambda: homilist.scrape_readings(
               '<div class="b-lectionary"><div class="innerblock">'
               "<p>Lectionary: 112</p></div></div>"),
           "no header")

    raises("missing address raises",
           lambda: homilist.scrape_readings(
               good.replace('<div class="address"><a href="#">Isaiah 55:1-3</a></div>', "")),
           "no address")

    # A renamed wrapper class is the exact shape a USCCB redesign takes. Writing
    # this test is what revealed the scraper returned "" silently instead of
    # raising -- a homily file with blank readings and no complaint.
    renamed = good.replace('class="wr-block b-verse"', 'class="wr-block b-scripture"')
    raises("renamed verse class raises rather than returning nothing",
           lambda: homilist.scrape_readings(renamed),
           "no readings found")


# ---------------------------------------------------------------- frontmatter

ROUND_TRIP = [
    {"date": "2026-08-02", "lectionary_number": 112,
     "lectionary_string": "Eighteenth Sunday in Ordinary Time",
     "title": "", "occasion": "", "location": "St. Anne",
     "readings": "Isa 55:1-3; Ps 145:8-9", "preached": "", "variant": ""},
    # The values that broke a hand-rolled writer: a colon, an apostrophe, a
    # leading bracket, and something that looks like a number.
    {"date": "2026-08-02", "rite": "Maronite", "lectionary_number": "",
     "lectionary_string": "Feast of X: Second Form",
     "title": "Martha: A Study in Grief", "occasion": "Healing Mass",
     "location": "St. Joe's", "readings": "Eccl 1:2, 2:21-23",
     "preached": "[not yet]", "variant": "Preaching Text"},
]


def test_frontmatter_round_trip():
    global checked
    for i, original in enumerate(ROUND_TRIP):
        text = homilist.format_frontmatter(original)
        try:
            parsed, body = homilist.split_frontmatter(text)
        except homilist.FrontmatterError as exc:
            # A writer that emits YAML its own reader rejects is the bug this
            # pair of functions exists to prevent. Report it rather than
            # crashing the run with a traceback.
            checked += 1
            failures.append(
                f"  round-trip [{i}]: format_frontmatter wrote invalid YAML\n"
                f"      {exc}"
            )
            continue
        for key, value in original.items():
            check(f"round-trip [{i}] {key}", parsed.get(key), value)
        check(f"round-trip [{i}] body is empty", body.strip(), "")


def test_frontmatter_rejects_bad_yaml():
    global checked
    checked += 1
    bad = "---\ntitle: Martha: A Study in Grief\ndate: 2026-08-02\n---\n\nbody\n"
    try:
        homilist.split_frontmatter(bad)
    except homilist.FrontmatterError:
        pass
    else:
        failures.append("  invalid YAML accepted -- pandoc would reject the same file")


def test_frontmatter_normalizes():
    # An unquoted date parses as datetime.date; downstream wants a string.
    parsed, _ = homilist.split_frontmatter("---\ndate: 2026-08-02\n---\n\nx\n")
    check("bare date normalized to string", parsed["date"], "2026-08-02")
    # An empty value parses as None; downstream wants "".
    parsed, _ = homilist.split_frontmatter("---\noccasion:\n---\n\nx\n")
    check("empty value normalized to ''", parsed["occasion"], "")
    # No frontmatter at all is not an error.
    parsed, body = homilist.split_frontmatter("just a body\n")
    check("no frontmatter yields empty dict", parsed, {})
    check("no frontmatter keeps the body", body.strip(), "just a body")


# ---------------------------------------------------------------- directory

def test_pdf_naming():
    """The printed filename depends on the rite; drafts stay YYYY-MM-DD.md."""
    # render.py used to run its whole body on import, so this had to slice the
    # function out of the source. It is in a guarded main() now, so import it.
    import render
    pdf_name = render.pdf_name

    # A venue typed into the variant as well used to print twice in the name.
    check("a venue already in the name is not added again",
          pdf_name({"date": "2026-09-16", "lectionary_number": 445,
                    "variant": "Maple Court", "location": "Maple Court"}, "x", [{}]),
          "2026-09-16 Homily 445 Maple Court.pdf")
    # ...but only the descriptive parts are compared: Homily 22 on the 22nd
    # keeps its number.
    check("a lectionary number matching the date is kept",
          pdf_name({"date": "2026-02-22", "lectionary_number": 22}, "x"),
          "2026-02-22 Homily 22.pdf")
    check("a venue is found word by word, not inside a longer word",
          render.distinct(["End of School St Anne", "St. Anne", "Ann"]),
          "End of School St Anne Ann")

    cases = [
        ({"date": "2026-04-28", "lectionary_number": 280},
         "2026-04-28 Homily 280.pdf"),
        ({"date": "2026-02-06", "lectionary_number": 327, "occasion": "Healing Mass"},
         "2026-02-06 Homily 327 Healing Mass.pdf"),
        # Non-Roman: rite first, no lectionary number, date only when known.
        ({"rite": "Maronite", "title": "12th Sunday of Pentecost"},
         "Maronite 12th Sunday of Pentecost.pdf"),   # no date: nothing to place
        # rite, then date, then day -- so each rite sorts chronologically
        ({"date": "2024-08-11", "rite": "Chaldean", "title": "Palm Sunday"},
         "Chaldean 2024-08-11 Palm Sunday.pdf"),
        # An explicit title beats the scraped day.
        ({"date": "2026-01-01", "rite": "Maronite", "title": "Mother of God",
          "lectionary_string": "ignored"},
         "Maronite 2026-01-01 Mother of God.pdf"),
        # The day is a fallback. A lectionary number already encodes it, so
        # "Homily 239 Wed 3rd of Lent" said the same thing twice; and an
        # occasion identifies a homily better than the day it fell on.
        ({"date": "2026-03-11", "lectionary_number": "239",
          "title": "Wed 3rd of Lent", "occasion": "Novena of Grace Day 7",
          "variant": "Manuscript"},
         "2026-03-11 Homily 239 Novena of Grace Day 7 Manuscript.pdf"),
        ({"date": "2026-05-13", "lectionary_number": "293",
          "title": "Wed 6th of Easter"},
         "2026-05-13 Homily 293.pdf"),
        # No number, but an occasion: the occasion wins.
        ({"date": "2026-03-27", "title": "Fri 5th of Lent",
          "occasion": "Lazarus Miracles All Around Us House Prayer Service"},
         "2026-03-27 Lazarus Miracles All Around Us House Prayer Service.pdf"),
        # Neither: the day is all there is.
        ({"date": "2024-01-20", "title": "Sat 2nd of OT"},
         "2024-01-20 Sat 2nd of OT.pdf"),
        # A slash would break the path.
        ({"date": "2026-01-01", "lectionary_number": 1, "occasion": "A/B"},
         "2026-01-01 Homily 1 A-B.pdf"),
        # No lectionary number: "Homily" in front of an occasion is just noise.
        ({"date": "2026-03-27", "occasion": "House Prayer Service"},
         "2026-03-27 House Prayer Service.pdf"),
    ]
    for meta, want in cases:
        check(f"pdf name {want}", pdf_name(meta, "fallback"), want)

    # Two homilies can share a date and a lectionary number -- the same day
    # preached twice in different places. Without the venue they collide and one
    # silently overwrites the other.
    a = {"date": "2026-05-20", "lectionary_number": 299, "location": "Maple Court"}
    b = {"date": "2026-05-20", "lectionary_number": 299, "location": "St. Anne"}
    check("colliding siblings get the venue",
          pdf_name(a, "x", [b]), "2026-05-20 Homily 299 Maple Court.pdf")
    check("the other sibling too",
          pdf_name(b, "x", [a]), "2026-05-20 Homily 299 St. Anne.pdf")
    # Every homily on a shared date names its venue, even when the siblings
    # already differ -- naming some but not others reads as an oversight.
    c = {"date": "2026-04-12", "lectionary_number": 43, "variant": "With Baptisms",
         "location": "St. Clare"}
    d = {"date": "2026-04-12", "lectionary_number": 43, "variant": "Without Baptisms",
         "location": "St. Clare"}
    check("siblings all name their venue",
          pdf_name(c, "x", [d]),
          "2026-04-12 Homily 43 With Baptisms St. Clare.pdf")
    # A homily with no sibling stays unadorned.
    check("a lone homily stays plain",
          pdf_name(c, "x", []), "2026-04-12 Homily 43 With Baptisms.pdf")


def test_homilies_dir_precedence():
    """$HOMILIES_DIR beats config.toml beats the parent directory."""
    saved_env = os.environ.get("HOMILIES_DIR")
    config = os.path.join(homilist.SCRIPT_DIR, "config.toml")
    saved_config = open(config, encoding="utf-8").read() if os.path.exists(config) else None

    try:
        with tempfile.TemporaryDirectory() as from_env, \
             tempfile.TemporaryDirectory() as from_config:
            with open(config, "w", encoding="utf-8") as f:
                f.write(f'homilies_dir = "{from_config}"\n')

            # Resolve both sides: on macOS /var is a symlink to /private/var, so
            # comparing an abspath against a realpath fails for the wrong reason.
            def resolved():
                return os.path.realpath(homilist.homilies_dir())

            os.environ["HOMILIES_DIR"] = from_env
            check("env var wins", resolved(), os.path.realpath(from_env))

            del os.environ["HOMILIES_DIR"]
            check("config.toml is next", resolved(), os.path.realpath(from_config))

            os.remove(config)
            check("falls back to the parent directory", resolved(),
                  os.path.realpath(os.path.join(homilist.SCRIPT_DIR, "..")))
    finally:
        if saved_config is not None:
            with open(config, "w", encoding="utf-8") as f:
                f.write(saved_config)
        elif os.path.exists(config):
            os.remove(config)
        if saved_env is None:
            os.environ.pop("HOMILIES_DIR", None)
        else:
            os.environ["HOMILIES_DIR"] = saved_env


# ---------------------------------------------------------------- day names

def test_standardize_day():
    """The two day shapes.

    The Eastern seasons are opt-in because several of those words name a *feast*
    in Roman day titles; a Roman day must survive the wider vocabulary untouched.
    """
    for text, rite, want in [
        ("Wednesday of 8th OT", None, "Wed 8th of OT"),
        ("Wed 12th of OT/St. Anselm", None, "Wed 12th of OT — St. Anselm"),
        ("Wed 12th of OT — St. Anselm", None, "Wed 12th of OT — St. Anselm"),
        ("Moses 2nd Sunday", "Chaldean", "Sun 2nd of Moses"),
        ("Church 4th Sunday", "Chaldean", "Sun 4th of Church"),
        ("2nd Sunday of the Church", "Chaldean", "Sun 2nd of Church"),
        ("11th Sun Pentecost", "Maronite", "Sun 11th of Pentecost"),
        ("11th Friday of Pentecost", "Maronite", "Fri 11th of Pentecost"),
        ("5th Sunday of Resurrection", "Maronite", "Sun 5th of Resurrection"),
        ("Lent 1st Sunday/ Faithful Departed", "Chaldean",
         "Sun 1st of Lent — Faithful Departed"),
        ("Peter and Paul / 4th Sunday of Pentecost", "Maronite",
         "Sun 4th of Pentecost — Peter and Paul"),
        # counted *from* a feast, not within a season -- "after" is the whole signal
        ("1st Sun after Epiphany", "Maronite", "1st Sun after Epiphany"),
        ("3rd Sunday After Epiphany", "Maronite", "3rd Sun after Epiphany"),
        ("3rd Sunday after Holy Cross", "Maronite", "3rd Sun after Holy Cross"),
        ("3rd Sun after Holy Cross", "Maronite", "3rd Sun after Holy Cross"),
        # not numbered days in a season: leave them alone
        # named for what it commemorates rather than counted; anchored at the
        # start so "5th Sunday of Lent" never reaches that rule
        ("Sunday of the Faithful Departed", "Maronite", "Sun of Faithful Departed"),
        ("Sunday of the Righteous and Just", "Maronite",
         "Sun of Righteous and Just"),
        ("Sun of Faithful Departed", "Chaldean", "Sun of Faithful Departed"),
        ("5th Sunday of Lent", "Maronite", "Sun 5th of Lent"),
        ("Sun 1st of Lent — Faithful Departed", "Chaldean",
         "Sun 1st of Lent — Faithful Departed"),
        # a day named for what it observes -- tried only after the numbered
        # rule declines, or it swallows "Wednesday of 8th OT"
        ("Tuesday of Easter Octave", None, "Tue of Easter Octave"),
        ("Tue of Easter Octave", None, "Tue of Easter Octave"),
        ("Wednesday of 8th OT", None, "Wed 8th of OT"),
        # the Sunday cycle belongs to the year, not the day
        ("Sun 13th of OT Year A", None, "Sun 13th of OT"),
        ("Sun 13th of OT - C", None, "Sun 13th of OT"),
        ("Sun 13th of OT", None, "Sun 13th of OT"),
        ("Palm Sunday", "Chaldean", "Palm Sunday"),
        # `rite: Roman` is written two ways and neither is Eastern, so the wider
        # season vocabulary must stay off for both
        ("Epiphany of the Lord", "Roman", "Epiphany of the Lord"),
        ("2nd Sunday of the Church", "Roman", "2nd Sunday of the Church"),
        ("2nd Sunday of the Church", "", "2nd Sunday of the Church"),
        ("Ascension", "Chaldean", "Ascension"),
        # Roman days whose names contain an Eastern season word
        ("Epiphany of the Lord", None, "Epiphany of the Lord"),
        ("The Resurrection of the Lord", None, "The Resurrection of the Lord"),
    ]:
        check(f"standardize_day {text!r} ({rite or 'Roman'})",
              homilist.standardize_day(text, rite), want)

    # Every canonical form in the README, run through again: the output must be
    # a fixed point, or a re-import walks the archive away from the documented
    # shape one run at a time. One README example was an input, not an output.
    for text, rite in [("Wed 12th of OT", None), ("Sun 5th of Easter", None),
                       ("Sun 4th of Church", "Chaldean"),
                       ("3rd Sun after Holy Cross", "Maronite"),
                       ("1st Sun after Epiphany", "Maronite"),
                       ("Sun of Faithful Departed", "Maronite"),
                       ("Sun of Righteous and Just", "Maronite"),
                       ("Ascension", "Chaldean"), ("Pentecost", "Chaldean"),
                       ("Ash Wednesday", None), ("Assumption", "Maronite")]:
        check(f"idempotent {text!r}", homilist.standardize_day(text, rite), text)

    # An override is a correction, not an exemption: whatever is typed into
    # _metadata-overrides.txt still goes through the conventions.
    check("override day is normalized",
          homilist.standardize_day("Sun 4th of Advent/Announcement to Joseph",
                                   "Chaldean"),
          "Sun 4th of Advent — Announcement to Joseph")

    for rite, want in [(None, False), ("", False), ("Roman", False),
                       ("roman", False), (" Roman ", False),
                       ("Maronite", True), ("Chaldean", True)]:
        check(f"is_eastern {rite!r}", homilist.is_eastern(rite), want)


# ---------------------------------------------------------------- calendar

def test_liturgical_calendar():
    """The local calendar that replaced the USCCB lookup.

    A scraper could not be tested; this can. Every number below is checked
    against a homily in the archive whose date is independently known, so a
    change in the arithmetic fails here rather than silently misdating an
    import.
    """
    import datetime
    import liturgical

    for year, want in [(2011, "2011-04-24"), (2023, "2023-04-09"),
                       (2024, "2024-03-31"), (2025, "2025-04-20"),
                       (2026, "2026-04-05"), (2027, "2027-03-28")]:
        check(f"Easter {year}", liturgical.easter(year).isoformat(), want)

    # Each of these is a real homily whose date came from its own document.
    for date, want, why in [
        ("2026-02-18", 219, "Ash Wednesday"),
        ("2026-02-25", 226, "Wed 1st of Lent"),
        ("2026-03-04", 232, "Wed 2nd of Lent"),
        ("2026-03-09", 237, "Mon 3rd of Lent — Lent steps by 7 after week 2"),
        ("2026-03-27", 255, "Fri 5th of Lent"),
        ("2026-04-02", 39, "Holy Thursday, not the ferial number"),
        ("2026-04-07", 262, "Tuesday in the octave of Easter"),
        ("2026-04-14", 268, "Tue 2nd of Easter"),
        ("2026-05-20", 299, "Wed 7th of Easter"),
        ("2026-06-09", 360, "Tue 10th of OT"),
        ("2026-06-30", 378, "Tue 13th of OT"),
        ("2026-02-22", 22, "Sun 1st of Lent, Year A"),
        ("2026-04-12", 43, "Sun 2nd of Easter, Year A"),
        ("2026-05-24", 63, "Pentecost"),
        ("2026-06-07", 167, "Corpus Christi, Year A"),
        # Fixed feasts that displace the day -- including an OT Sunday.
        ("2026-12-26", 696, "St Stephen, not a string from describe()"),
        ("2026-11-01", 667, "All Saints on a Sunday beats the OT Sunday"),
        ("2026-11-02", 668, "All Souls"),
        ("2026-08-15", 622, "Assumption"),
        ("2027-01-03", 20, "Epiphany Sunday"),
        ("2027-01-10", 21, "Baptism of the Lord"),
        ("2026-03-29", 37, "Palm Sunday A: a season Sunday is not displaced"),
        ("2026-03-25", 545, "the Annunciation, a fixed date"),
        ("2024-10-28", 666, "Simon and Jude, a fixed date"),
        # 25 December must not report as the fourth week of Advent: Advent
        # begins in November, so an untested ordering swallowed Christmas.
        ("2025-12-25", 16, "Christmas Day"),
        ("2025-12-29", 202, "a weekday of the Christmas octave"),
    ]:
        got = liturgical.lectionary_number(datetime.date.fromisoformat(date))
        check(f"lectionary {date} ({why})", got, want)

    # The inverse, which is what dating an import actually uses.
    got = liturgical.dates_for_lectionary(378, datetime.date(2026, 7, 3))
    check("lect 378 near 2026-07-03", got[0].isoformat() if got else None,
          "2026-06-30")
    # describe() and standardize_day must write the same weekday.
    check("describe agrees with standardize_day",
          liturgical.describe(datetime.date(2026, 6, 9)), "Tue 10th of OT")

    check("an unknown number finds nothing",
          liturgical.dates_for_lectionary(9999, datetime.date(2026, 7, 3)), [])


# ---------------------------------------------------------------- lectionary

# ---------------------------------------------------------------- LiturgicalCalendarAPI

def test_litcal_api():
    """parse() against a small fixture -- no network, same idea as the USCCB
    scraper tests: the fetch and the parse are separate, so the parse is the
    part worth testing on its own."""
    import datetime
    import litcal_api

    fixture = {"litcal": [
        # A plain ferial weekday.
        {"date": "2025-12-01T00:00:00+00:00", "name": "Monday of the 1st Week of Advent",
         "grade": 0,
         "readings": {"first_reading": "Isaiah 4:2-6",
                      "responsorial_psalm": "Psalm 122:1-2, 3-4b, 4cd-5, 6-7, 8-9",
                      "gospel_acclamation": "Psalm 80:4",
                      "gospel": "Matthew 8:5-11"}},
        # A weekday sharing its date with an optional memorial: the optional
        # memorial does not displace the ferial readings.
        {"date": "2025-12-04T00:00:00+00:00", "name": "Thursday of the 1st Week of Advent",
         "grade": 0,
         "readings": {"first_reading": "Isaiah 26:1-6",
                      "responsorial_psalm": "Psalm 118:1, 8-9, 19-21, 25-27a",
                      "gospel": "Matthew 7:21, 24-27"}},
        {"date": "2025-12-04T00:00:00+00:00", "name": "Saint John Damascene, Priest and Doctor",
         "grade": 2,
         "readings": {"first_reading": "1 John 4:4-9", "gospel": "Matthew 5:13-16"}},
        # An obligatory memorial with no competing weekday entry: it wins.
        {"date": "2025-12-03T00:00:00+00:00", "name": "Saint Francis Xavier, Priest",
         "grade": 3,
         "readings": {"first_reading": "1 Corinthians 9:16-19, 22-23",
                      "responsorial_psalm": "Psalm 117:1bc, 2",
                      "gospel": "Mark 16:15-20"}},
        # A vigil Mass beside the Sunday it anticipates: the vigil is set aside
        # in favor of the day itself.
        {"date": "2025-11-30T00:00:00+00:00", "name": "First Sunday of Advent Vigil Mass",
         "grade": 7, "is_vigil_mass": True,
         "readings": {"first_reading": "Isaiah 2:1-5", "responsorial_psalm": "Psalm 122",
                      "second_reading": "Romans 13:11-14", "gospel": "Matthew 24:37-44"}},
        {"date": "2025-11-30T00:00:00+00:00", "name": "First Sunday of Advent",
         "grade": 7,
         "readings": {"first_reading": "Isaiah 2:1-5", "responsorial_psalm": "Psalm 122",
                      "second_reading": "Romans 13:11-14", "gospel": "Matthew 24:37-44"}},
        # A date with an event but nothing to proclaim.
        {"date": "2025-12-10T00:00:00+00:00", "name": "Nothing to preach on", "grade": 0,
         "readings": {}},
        # The API's own delimiter for an alternate reading is a bare "|" inside
        # one field, not the "; " this project uses between readings.
        {"date": "2025-12-21T00:00:00+00:00", "name": "Monday of the 4th Week of Advent",
         "grade": 0,
         "readings": {"first_reading": "Song of Songs 2:8-14|Zephaniah 3:14-18a",
                      "responsorial_psalm": "Psalm 33:2-3, 11-12, 20-21",
                      "gospel": "Luke 1:39-45"}},
        # A Mass with more than one time of day nests a complete readings dict
        # under each instead of giving readings directly.
        {"date": "2025-12-25T00:00:00+00:00", "name": "Christmas", "grade": 7,
         "readings": {
             "night": {"first_reading": "Isaiah 9:1-6", "gospel": "Luke 2:1-14"},
             "dawn": {"first_reading": "Isaiah 62:11-12", "gospel": "Luke 2:15-20"},
             "day": {"first_reading": "Isaiah 52:7-10", "responsorial_psalm": "Psalm 98:1-6",
                     "second_reading": "Hebrews 1:1-6", "gospel": "John 1:1-18"}}},
        # The Easter Vigil numbers up to seven Old Testament readings plus an
        # epistle, not the ordinary first/second/gospel shape.
        {"date": "2025-04-19T00:00:00+00:00", "name": "Easter Vigil", "grade": 7,
         "readings": {"first_reading": "Genesis 1:1-2:2", "responsorial_psalm": "Psalm 104",
                      "third_reading": "Exodus 14:15-15:1", "responsorial_psalm_3": "Exodus 15",
                      "epistle": "Romans 6:3-11", "responsorial_psalm_epistle": "Psalm 118",
                      "gospel_acclamation": "", "gospel": "Matthew 28:1-10"}},
        # The Chrism Mass shares Holy Thursday's date and its grade 7 with the
        # Evening Mass of the Lord's Supper -- the parish's actual liturgy that
        # day -- so a plain tie-break by grade could pick either.
        {"date": "2025-04-17T00:00:00+00:00", "name": "Chrism Mass", "grade": 7,
         "readings": {"first_reading": "Isaiah 61:1-3a, 6a, 8b-9", "gospel": "Luke 4:16-21"}},
        {"date": "2025-04-17T00:00:00+00:00", "name": "Holy Thursday", "grade": 7,
         "readings": {"first_reading": "Exodus 12:1-8, 11-14",
                      "second_reading": "1 Corinthians 11:23-26", "gospel": "John 13:1-15"}},
    ]}

    def parsed(iso):
        return litcal_api.parse(fixture, datetime.date.fromisoformat(iso))

    got = parsed("2025-12-01")
    check("weekday name", got["name"], "Monday of the 1st Week of Advent")
    check("weekday readings, acclamation skipped", got["readings"],
          "Isa 4:2–6; Ps 122:1–2, 3–4b, 4cd-5, 6–7, 8–9; Matt 8:5–11")

    got = parsed("2025-12-04")
    check("optional memorial does not displace the weekday", got["name"],
          "Thursday of the 1st Week of Advent")
    check("weekday readings win", got["readings"],
          "Isa 26:1–6; Ps 118:1, 8–9, 19–21, 25–27a; Matt 7:21, 24–27")

    got = parsed("2025-12-03")
    check("obligatory memorial with no weekday competitor", got["name"],
          "Saint Francis Xavier, Priest")
    check("memorial readings", got["readings"],
          "1 Cor 9:16–19, 22–23; Ps 117:1bc, 2; Mark 16:15–20")

    got = parsed("2025-11-30")
    check("the day wins over its own vigil", got["name"], "First Sunday of Advent")
    check("Sunday readings", got["readings"],
          "Isa 2:1–5; Ps 122; Rom 13:11–14; Matt 24:37–44")

    check("a date with nothing to proclaim parses to None",
          parsed("2025-12-10"), None)
    check("a date with no entry at all parses to None",
          parsed("2025-12-26"), None)

    got = parsed("2025-12-21")
    check("the API's '|' alternate becomes 'or', both books abbreviated",
          got["readings"],
          "Song 2:8–14 or Zeph 3:14–18a; "
          "Ps 33:2–3, 11–12, 20–21; Luke 1:39–45")

    got = parsed("2025-12-25")
    check("a multi-Mass day defaults to the day Mass", got["readings"],
          "Isa 52:7–10; Ps 98:1–6; Heb 1:1–6; John 1:1–18")

    got = parsed("2025-04-19")
    check("the Vigil's numbered readings all come through, in order",
          got["readings"],
          "Gen 1:1–2:2; Ps 104; Exod 14:15–15:1; Exod 15; "
          "Rom 6:3–11; Ps 118; Matt 28:1–10")

    got = parsed("2025-04-17")
    check("the parish's Evening Mass wins over the diocese's Chrism Mass",
          got["name"], "Holy Thursday")
    check("Holy Thursday's own readings, not the Chrism Mass's",
          got["readings"],
          "Exod 12:1–8, 11–14; 1 Cor 11:23–26; John 13:1–15")
    check("comparison fields split out too", got["second"], "1 Cor 11:23–26")

    got = parsed("2025-04-19")
    check("the Vigil's epistle stands in for 'second' in the comparison fields",
          got["second"], "Rom 6:3–11")


def test_citations_agree():
    """citations_agree() compares first/second/gospel only -- not the psalm,
    whose punctuation differs by source even when the passage agrees."""
    import litcal_api

    a = {"first": "1 Cor 15:12–20", "second": "", "gospel": "Luke 8:1–3"}
    b_same = {"first": "1 Cor 15:12–20", "second": "", "gospel": "Luke 8:1–3"}
    b_diff = {"first": "1 Cor 15:12–22", "second": "", "gospel": "Luke 8:1–3"}

    check("identical fields agree", litcal_api.citations_agree(a, b_same), True)
    check("today's actual bug: a differing verse range does not agree",
          litcal_api.citations_agree(a, b_diff), False)
    check("a missing 'psalm' key in the comparison dict is a non-issue",
          litcal_api.citations_agree({"first": "Luke 1:1", "gospel": "Luke 1:1"},
                                     {"first": "Luke 1:1", "gospel": "Luke 1:1"}),
          True)


def test_lectionary_table():
    """The readings table, where it has been fetched.

    Skipped rather than failed when the table is absent: it is someone else's
    compilation, cached under tmp/ and not committed, so a fresh clone has no
    copy until tools/fetch_lectionary.py runs.
    """
    import lectionary
    if not lectionary.available():
        print("  (lectionary table not fetched; skipping)")
        return

    # Every one of these was read off the source by hand before the parser
    # existed, so they check the parser rather than restate it.
    for number, year, gospel in [
        ("372", "II", "Matt 7:6, 12-14"),
        ("433", "II", "Luke 4:38-44"),
        ("457", "I", "Luke 9:57-62"),
        ("491", "I", "Luke 17:1-6"),
        ("491", "II", "Luke 17:1-6"),
        ("226", None, "Luke 11:29-32"),
        ("259", None, "Matt 26:14-25"),
        ("28", None, "John 4:5-42"),
        ("543", None, "Matt 1:16, 18-21, 24a or Luke 2:41-51a"),
        ("666", None, "Luke 6:12-19"),
        # Pentecost heads three rows, the later two marked "opt:". Taking
        # whichever came last put an optional Gospel in place of the appointed.
        ("63", None, "John 20:19-23"),
    ]:
        entry = lectionary.readings_for(number, year) or {}
        check(f"lectionary table {number} {year or ''}", entry.get("gospel"), gospel)
    # All Souls lists every option from the Masses for the Dead. That is a menu,
    # not the day's readings, and the preacher chooses.
    check("a menu of options is not a set of readings",
          lectionary.readings_for(668), None)
    check("but its cross-referenced neighbours resolve",
          bool(lectionary.readings_for(20)), True)

    # Year I and Year II differ in the first reading and agree on the Gospel.
    first_i = (lectionary.readings_for("491", "I") or {}).get("first")
    first_ii = (lectionary.readings_for("491", "II") or {}).get("first")
    check("491 Year I first reading", first_i, "Wis 1:1-7")
    check("491 Year II first reading", first_ii, "Titus 1:1-9")
    # An Ordinary Time number without a year is ambiguous, not answerable.
    check("OT number needs a year", lectionary.readings_for("491"), None)


# ---------------------------------------------------------------- header split

def test_header_line():
    """Which opening lines are header and which are the homily.

    Length was the old test and it was wrong in both directions: "All the feasts
    of Lent link together to form" is 44 characters and is a homily's first
    line, while "St. Rafqa Maronite Church (Riverton, MA)" is longer and is a
    venue. Every string below is real text from the archive.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
    import import_docx as imp

    for text, want in [
        # labels
        ("St. Rafqa Maronite Church (Riverton, MA)", True),
        ("Sunday of the Righteous and Just", True),
        ("Birth of John the Baptist (and Immaculate Conception)", True),
        ("Memorial of St. Ephrem", True),
        ("Mark 10:46-52", True),
        ("February 18, 2026", True),
        # an ordinal must not drag a day name below the threshold: "2nd"
        # contributes a phantom lowercase "nd" without a word boundary
        ("Thurs 2nd of Lent", True),
        ("Wed 3rd of Lent", True),
        # the homily itself
        ("All the feasts of Lent link together to form", False),
        ("There is a hunger underneath our hunger.", False),
        ("Every one of us has walked out of a room mid-sentence,", False),
        ("Friends, merry Christmas to all of you!", False),
        ("Nicodemus comes to Jesus at night.", False),
    ]:
        check(f"header_line {text[:44]!r}", imp.header_line(text), want)


# ---------------------------------------------------------------- sidecars

def test_sidecar_files():
    """Application and filesystem artifacts must never reach document handling.

    Word's owner files are the awkward case: the "~$" prefix REPLACES the first
    two characters rather than being prepended, so the name keeps its length and
    still reads like a title. Both fixtures below are real names that appeared
    in this archive and sat in the unresolved report permanently -- an owner
    file has no date to resolve, so nothing ever cleared them.
    """
    for name, want in [
        # Word owner files, as they actually appeared
        ("~$mily Healing of the Blind Man.docx", True),
        ("~$rth of John the Baptist.docx", True),
        # AppleDouble resource forks -- a cloud-synced archive collects them
        ("._Homily 280.docx", True),
        ("._2026-08-02.md", True),
        # dotfiles
        (".DS_Store", True),
        (".gitignore", True),
        # the controls: real documents, which must still be picked up
        ("Homily Healing of the Blind Man.docx", False),
        ("Birth of John the Baptist.docx", False),
        ("2026-08-02.md", False),
    ]:
        check(f"is_sidecar {name!r}", homilist.is_sidecar(name), want)

    # A path, not just a bare name: the glob hands over "Word/~$foo.docx".
    check("is_sidecar on a path",
          homilist.is_sidecar("/Users/x/Homilies/Word/~$rth of John the Baptist.docx"),
          True)
    check("is_sidecar on a directory that starts with a dot",
          homilist.is_sidecar("/Users/x/.hidden/Homily 280.docx"), False)

    # documents() is what argv goes through, and is the reason --report stopped
    # listing owner files.
    given = ["Word/Homily 280.docx", "Word/~$mily Healing of the Blind Man.docx",
             "Word/._Homily 280.docx", "Word/Birth of John the Baptist.docx"]
    check("documents() filters the glob", homilist.documents(given),
          ["Word/Homily 280.docx", "Word/Birth of John the Baptist.docx"])


# ---------------------------------------------------------------- docx runs

def test_run_merging():
    """Adjacent runs sharing formatting are merged before markers go on.

    Word splits a run wherever it likes -- a spell-check boundary, a language
    attribute, a tracked revision -- so one italic phrase often arrives as
    several runs. Marking each separately produced "*t**he souls of the just*",
    which markdown does not read as emphasis at all: pandoc printed the
    asterisks. Both fixtures are real text from the archive.
    """
    import zipfile
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
    import import_docx as imp

    def docx_with(runs):
        """A one-paragraph .docx whose runs are (bold, italic, text)."""
        W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        body = ""
        for bold, ital, text in runs:
            props = ("<w:rPr>" + ("<w:b/>" if bold else "")
                     + ("<w:i/>" if ital else "") + "</w:rPr>") if (bold or ital) else ""
            body += f"<w:r>{props}<w:t xml:space='preserve'>{text}</w:t></w:r>"
        xml = (f"<w:document xmlns:w='{W}'><w:body><w:p>{body}</w:p></w:body></w:document>")
        path = os.path.join(tempfile.mkdtemp(), "t.docx")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", xml)
        return path

    # one italic phrase, split by Word into two runs
    path = docx_with([(False, False, "As Peter said, "),
                      (False, True, "t"),
                      (False, True, "he souls of the just"),
                      (False, False, " are in God's hand.")])
    check("split italic run merges",
          imp.paragraphs(path)[0][1],
          "As Peter said, *the souls of the just* are in God's hand.")

    # formatting really does change: the markers must stay separate
    path = docx_with([(False, True, "italic"), (False, False, " then "),
                      (True, False, "bold")])
    check("different formatting stays separate",
          imp.paragraphs(path)[0][1], "*italic* then **bold**")

    # plain text is untouched
    path = docx_with([(False, False, "a"), (False, False, "b")])
    check("plain runs merge without markers", imp.paragraphs(path)[0][1], "ab")


# ---------------------------------------------------------------- sibling names

def test_sibling_naming():
    """Two homilies on one date: the suffix has to say which is which, and the
    best answer is not always available."""
    novena = {"occasion": "Novena of Grace Day 7", "variant": "Manuscript",
              "location": "Loyola University", "title": "Wed 3rd of Lent"}
    check("occasion and variant name it first",
          homilist.distinguishers(novena)[0], "novena-of-grace-day-7-manuscript")
    check("the venue and the day stand behind it",
          homilist.distinguishers(novena)[1:],
          ["loyola-university", "wed-3rd-of-lent"])
    check("a draft with nothing to say has no suffix",
          homilist.distinguishers({"occasion": "", "variant": "",
                                   "location": "", "title": ""}), [])

    # Same venue, same date, no occasion and no variant: the venue distinguishes
    # nothing, so the day has to.
    feast = {"occasion": "", "variant": "", "location": "St. Anthony",
             "title": "Assumption"}
    check("a suffix that is already taken falls through to the day",
          homilist.sibling_name("2025-08-17", feast,
                                taken={"2025-08-17_st-anthony.md"}),
          "2025-08-17_assumption.md")
    check("an unclaimed venue is enough",
          homilist.sibling_name("2025-08-17", feast), "2025-08-17_st-anthony.md")
    # What counts is the field the other drafts that day lack, not the best
    # field in the abstract: two Masses at one church share the venue.
    check("a shared venue is skipped for the day's own name",
          homilist.distinguishing_slug(
              {"location": "St. Anne", "variant": "With Baptisms"},
              [{"location": "St. Anne", "variant": "Without Baptisms"}]),
          "with-baptisms")
    check("different venues are enough on their own",
          homilist.distinguishing_slug(
              {"location": "Maple Court", "title": "Wed 24th of OT"},
              [{"location": "Arrupe House", "title": "Wed 24th of OT"}]),
          "maple-court")
    check("nothing of its own is None, not a guess",
          homilist.distinguishing_slug(
              {"location": "St. Anne"}, [{"location": "St. Anne"}]),
          None)

    check("the plain date is never offered as a sibling",
          homilist.sibling_name("2025-08-17", feast,
                                taken={"2025-08-17_st-anthony.md",
                                       "2025-08-17_assumption.md"}),
          "2025-08-17_b.md")


# ---------------------------------------------------------------- summary follows draft

def test_rename_summary():
    """A renamed draft takes its summary along, or the summaries task writes a
    second one and orphans the first."""
    with tempfile.TemporaryDirectory() as root:
        drafts = os.path.join(root, "Drafts")
        summaries = os.path.join(root, "Homily Summaries")
        os.makedirs(drafts)
        os.makedirs(summaries)
        saved = os.environ.get("HOMILIES_DIR")
        os.environ["HOMILIES_DIR"] = drafts
        try:
            text = "# 2026-09-16 Summary\n\n<!-- summary-format: 2 -->\n\n## Core Themes\n"
            with open(os.path.join(summaries, "2026-09-16 Summary.md"), "w", encoding="utf-8") as f:
                f.write(text)

            check("a summary moves with its draft",
                  homilist.rename_summary("2026-09-16.md", "2026-09-16_maple-court.md"),
                  "renamed")
            moved = os.path.join(summaries, "2026-09-16_maple-court Summary.md")
            check("the old name is gone",
                  os.path.exists(os.path.join(summaries, "2026-09-16 Summary.md")), False)
            # Heading rewritten, and nothing else -- not the blank line after it.
            check("only the heading changes", open(moved, encoding="utf-8").read(),
                  text.replace("# 2026-09-16 Summary", "# 2026-09-16_maple-court Summary"))

            check("no summary yet is not an error",
                  homilist.rename_summary("2026-09-17.md", "2026-09-17_a.md"), "missing")

            # Two summaries claiming one name: neither is touched.
            with open(os.path.join(summaries, "2026-09-18 Summary.md"), "w", encoding="utf-8") as f:
                f.write("# 2026-09-18 Summary\n")
            with open(os.path.join(summaries, "2026-09-18_b Summary.md"), "w", encoding="utf-8") as f:
                f.write("# 2026-09-18_b Summary\n")
            check("an occupied name is a conflict",
                  homilist.rename_summary("2026-09-18.md", "2026-09-18_b.md"), "conflict")
            check("and the original stays put",
                  os.path.exists(os.path.join(summaries, "2026-09-18 Summary.md")), True)
        finally:
            if saved is None:
                os.environ.pop("HOMILIES_DIR", None)
            else:
                os.environ["HOMILIES_DIR"] = saved


# ---------------------------------------------------------------- editor

def test_editor_command():
    """The editor is looked for before it is called: the old code ran `code` on
    faith and crashed after the draft was already written."""
    sys.path.insert(0, os.path.dirname(HERE))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "new_editor", os.path.join(os.path.dirname(HERE), "new.py"))
    # new.py runs a picker on import, so only the function's source is loaded.
    source = open(os.path.join(os.path.dirname(HERE), "new.py"), encoding="utf-8").read()
    start = source.index("def editor_command(")
    end = source.index("def open_in_editor(")
    namespace = {}
    exec("import shlex, shutil\n" + source[start:end], namespace)
    editor_command = namespace["editor_command"]

    check("config.toml names the editor first",
          editor_command({"editor": "cat"}, {"EDITOR": "ls"})[0].endswith("/cat"), True)
    check("an editor not on the PATH is skipped, not run",
          editor_command({"editor": "no-such-editor-xyz"}, {"EDITOR": "cat"})[0].endswith("/cat"),
          True)
    check("flags in the setting survive",
          editor_command({"editor": "cat -n"}, {})[1:], ["-n"])
    check("$VISUAL beats $EDITOR", editor_command({}, {"VISUAL": "cat", "EDITOR": "ls"})[0].endswith("/cat"), True)
    check("nothing configured is None, not a crash",
          editor_command({}, {"EDITOR": "no-such-editor-xyz"}), None)


# ---------------------------------------------------------------- themes index

def test_themes():
    """The themes index copies rather than interprets, so what it copies has to
    survive the trip: a wrapped bullet is one theme, and an image that appears
    twice in one summary is one image."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
    import themes  # noqa: PLC0415

    summary = (
        "# A Summary\n\n"
        "## Core Themes\n"
        "- Waiting without knowing how long\n"
        "- A theme that wraps\n  onto a second line\n\n"
        "## Summary\nProse that is not a theme.\n\n"
        "## Preaching Notes\n"
        '- Quotes St. Ignatius, "Go, set the world on fire."\n'
        "- Retells an episode from *Confessions*; God is mentioned throughout.\n"
    )

    check("themes section stops at the next heading",
          themes.bullets(themes.section(summary, "Core Themes")),
          ["Waiting without knowing how long", "A theme that wraps onto a second line"])
    check("a section that is absent is empty",
          themes.section(summary, "Preaching Nothing"), "")

    got = themes.images(themes.section(summary, "Preaching Notes"))
    check("quoted matter is kept", "Go, set the world on fire" in got, True)
    check("the narration verb is dropped, the saint kept",
          "St. Ignatius" in got, True)
    check("no bare narration verb survives", "Quotes" in got, False)
    check("italics are kept", "Confessions" in got, True)
    check("what every homily says is not an image", "God" in got, False)

    # The same name in two forms is one image, not two.
    twice = themes.images('- Names "Our Lady of the Rosary"; Our Lady of the '
                          "Rosary again.\n")
    check("the longer form of a repeated image wins", twice,
          ["Our Lady of the Rosary"])

    # A summary is named for its draft whatever the homily was imported from --
    # the archive used to name imported ones after the .docx, and the two
    # conventions cost more than they explained.
    check("a summary is named for its draft",
          homilist.summary_name("2026-08-27.md"), "2026-08-27 Summary.md")
    check("a variant's summary keeps the suffix",
          homilist.summary_name("2026-08-23_with-baptisms.md"),
          "2026-08-23_with-baptisms Summary.md")

    check("a pipe in a field cannot break the row",
          themes.cell("Luke 1:1 | Matt 2:2"), "Luke 1:1 \\| Matt 2:2")
    check("an empty field is marked, not blank", themes.cell(""), themes.BLANK)


def main():
    test_scraper()
    test_scraper_alternate()
    test_scraper_nbsp()
    test_scraper_compound_title()
    test_scraper_failures()
    test_frontmatter_round_trip()
    test_frontmatter_rejects_bad_yaml()
    test_frontmatter_normalizes()
    test_pdf_naming()
    test_homilies_dir_precedence()
    test_standardize_day()
    test_liturgical_calendar()
    test_lectionary_table()
    test_litcal_api()
    test_citations_agree()
    test_header_line()
    test_sidecar_files()
    test_run_merging()
    test_sibling_naming()
    test_editor_command()
    test_rename_summary()
    test_themes()

    if failures:
        print(f"{len(failures)} of {checked} checks FAILED:")
        print("\n".join(failures))
        return 1
    print(f"{checked} checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

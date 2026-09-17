#!/bin/sh
''''exec "$(dirname "$0")/../env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env

"""Reverse-generate a markdown draft from an existing .docx homily.

    tools/import_docx.py --dry-run "Word/<file>.docx"   # show what it would write
    tools/import_docx.py Word/*.docx                   # write the drafts

**Non-destructive.** The .docx is opened read-only and never written to. Drafts
land in the configured homilies directory as `YYYY-MM-DD.md`, and an existing
draft is never overwritten without --force.

Dating is the hard part: the file's own timestamps are not the day it was preached.
Measured against the 66 homilies whose text carries an explicit date, `modified` is
exact 74% of the time, within 3 days 95%, and within 30 days 100%. So it is useless
as an answer and excellent as a *window* -- which makes the lectionary number in the
filename resolvable: `liturgical.py` computes the number for each candidate date in
that window and the matching one is the answer. No network is involved.

Sources are tried in descending order of trust, and the one used is recorded in the
draft so a guess is never mistaken for a fact.
"""

import argparse
import datetime
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import homilist  # noqa: E402
import liturgical  # noqa: E402
import lectionary  # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
MONTHS = {m[:3].lower(): i for i, m in enumerate(MONTH_NAMES, 1)}
MONTH_RE = (r"(?:January|February|March|April|May|June|July|August|September|"
            r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|"
            r"Oct|Nov|Dec)\.?")

LONG_DATE = re.compile(rf"\b({MONTH_RE})\s+(\d{{1,2}}),?\s+(20\d\d)\b")
ISO_DATE = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")
# "26-03-25" in a filename is yy-mm-dd, the convention in this corpus.
SHORT_DATE = re.compile(r"\b(\d{2})-(\d{2})-(\d{2})\b")

# A scripture citation: book, then chapter, optionally chapter:verse. The book
# name is checked against the real list, because the shape alone is not enough --
# "St. Anne 7:00 pm" is a venue and a Mass time, and matching it as a citation
# put a whole header line into the readings field and displaced everything else.
CITATION_SHAPE = re.compile(
    r"\b((?:[123]\s+)?[A-Z][A-Za-z]{1,11})\.?\s+(\d{1,3})(?:\s*[:.]\s?\d)?")


class _CitationFinder:
    """Drop-in for the old compiled pattern: .search() with a book-name check."""

    def search(self, text):
        if not text:
            return None
        for match in CITATION_SHAPE.finditer(text):
            book = match.group(1).lower().rstrip(". ")
            if book in homilist._BOOKS:
                return match
        return None

    def finditer(self, text):
        for match in CITATION_SHAPE.finditer(text or ""):
            if match.group(1).lower().rstrip(". ") in homilist._BOOKS:
                yield match


CITATION = _CitationFinder()

# Parenthesised or trailing location, e.g. "Tuesday 4th of Easter (St. Anne)".
PAREN_LOCATION = re.compile(r"\(([^)]{2,40})\)\s*$")

# A header line is short. Body prose in this corpus runs long.
HEADER_LINE_MAX = 130


# ---------------------------------------------------------------- docx reading

def paragraphs(path):
    """(text, markdown_text) per non-empty paragraph, read-only."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))

    out = []
    for p in root.iter(W + "p"):
        # Collect runs first, then merge the adjacent ones that share formatting.
        # Word splits a run wherever it likes -- a spell-check boundary, a
        # language attribute, a tracked revision -- so one italic phrase often
        # arrives as several runs. Marking each separately produced "*t**he
        # souls of the just*", which markdown does not read as emphasis at all
        # and pandoc prints with the asterisks showing.
        runs = []
        for r in p.iter(W + "r"):
            if r.find(W + "br") is not None and runs:
                runs.append((None, None, "\n"))
            text = "".join(t.text or "" for t in r.iter(W + "t"))
            if not text:
                continue
            rpr = r.find(W + "rPr")
            bold = rpr is not None and rpr.find(W + "b") is not None
            ital = rpr is not None and rpr.find(W + "i") is not None
            if runs and runs[-1][0] == bold and runs[-1][1] == ital:
                runs[-1] = (bold, ital, runs[-1][2] + text)
            else:
                runs.append((bold, ital, text))

        plain, md = [], []
        for bold, ital, text in runs:
            if text == "\n" and bold is None:
                # A <w:br/> is a line break *inside* a paragraph -- Word's way of
                # setting quoted scripture in sense lines. Dropping it ran the
                # surrounding words together ("the LORD of hostswill provide"),
                # so it becomes a real break. Two trailing spaces is markdown's.
                plain.append("\n")
                md.append("  \n")
                continue
            plain.append(text)
            # Emphasis markers must hug the words, or markdown ignores them.
            lead = len(text) - len(text.lstrip())
            trail = len(text) - len(text.rstrip())
            core = text.strip()
            if core and (bold or ital):
                mark = "**" if bold else "*"
                core = f"{mark}{core}{mark}"
            md.append(" " * lead + core + " " * trail)
        joined = "".join(plain).replace("\n", " ").strip()
        if joined:
            out.append((joined, "".join(md).strip()))
    return out


def docx_modified(path):
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("docProps/core.xml"))
    except (KeyError, zipfile.BadZipFile, ET.ParseError):
        return None
    for tag in ("modified", "created"):
        for el in root.iter():
            if el.tag.endswith(tag) and el.text:
                try:
                    return datetime.date.fromisoformat(el.text[:10])
                except ValueError:
                    continue
    return None


# ---------------------------------------------------------------- parsing

def parse_date(text):
    m = LONG_DATE.search(text)
    if m:
        month = MONTHS.get(m.group(1)[:3].lower())
        if month:
            try:
                return datetime.date(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                pass
    m = ISO_DATE.search(text)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = SHORT_DATE.search(text)
    if m:
        try:
            return datetime.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def ambiguous_short_date(text):
    """True when a `dd-dd-dd` filename date could be read two ways.

    The convention in this corpus is yy-mm-dd, and "24-01-20" can only be that.
    But "11-11-19" is a valid date read either way, and reading it as yy-mm-dd
    put a 2019 homily in 2011 -- eight years off, and invisible, because the
    result was still a plausible date on a plausible weekday. Where both
    readings work, the filename is not evidence and something else must decide.
    """
    m = SHORT_DATE.search(text or "")
    if not m:
        return False
    a, b, c = (int(x) for x in m.groups())
    def valid(year, month, day):
        try:
            datetime.date(2000 + year, month, day)
            return True
        except ValueError:
            return False
    return valid(a, b, c) and valid(c, a, b)


# Words that carry no capitalization signal either way.
_SMALL_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "is",
    "are", "was", "were", "of", "on", "or", "our", "the", "their", "to", "with",
    "who", "that", "it", "its", "his", "her", "us", "me", "my", "your", "not",
}


def title_case_ish(text, threshold=0.7):
    """Whether a line reads as a label rather than a sentence.

    Length is the wrong test -- "All the feasts of Lent link together to form" is
    44 characters and is a homily's first line, while "St. Rafqa Maronite
    Church (Riverton, MA)" is longer and is a venue. Capitalization separates
    them: a label capitalizes nearly everything that carries meaning, prose
    capitalizes the first word and the proper nouns.
    """
    # \b matters: without it "2nd" contributes a phantom lowercase "nd" and
    # drags an ordinal-bearing day name below the threshold.
    words = re.findall(r"\b[A-Za-z][A-Za-z'’]*\b", text)
    significant = [w for w in words if w.lower() not in _SMALL_WORDS]
    if not significant:
        return True          # numerals and punctuation only: a citation or date
    caps = sum(1 for w in significant if w[0].isupper())
    return caps / len(significant) >= threshold


def header_line(text):
    """Whether a line after the first is part of the header rather than the body.

    A header line is a *label*: a date, a citation, a venue, or a short name for
    the day. A sentence is not, however short -- "All the feasts of Lent link
    together to form" is 44 characters and is the homily's first line.
    """
    if parse_date(text) or CITATION.search(text) or names_a_venue(text):
        return True
    return title_case_ish(text)


def split_header(paras):
    """(header_lines, body_paragraphs).

    A header is a short run of lines at the top carrying a date and/or a line of
    citations. Homily 177 opens with four lines of quoted Isaiah and has no header
    at all -- so unless a date or citation line actually appears in the opening
    lines, everything is body. Guessing here would silently eat the first sentence
    of a homily.
    """
    window = paras[:5]
    anchored = any(
        parse_date(text) or (CITATION.search(text) and len(text) <= HEADER_LINE_MAX)
        for text, _ in window
    )
    if not anchored:
        return [], paras

    header = []
    for index, (text, _) in enumerate(paras):
        if len(text) > HEADER_LINE_MAX:
            break
        # A stage direction opens the body. "[Opening]" is not a header line,
        # and everything after it certainly is not.
        if text.startswith(("[", "(")):
            break
        # The first line is always the header's own; later ones have to earn it.
        # Without this a short *body* line was taken as a title -- the trailing
        # trim only dropped long ones, so a homily set in sense lines lost its
        # opening sentence, and the audit could not see it because the audit
        # split the header the same way.
        if index and not header_line(text):
            break
        header.append(text)
        if len(header) >= 5:
            break

    return header, paras[len(header):]


def interpret_header(header, ignore_names=(), venues=()):
    """Pull date, readings, location and title out of the header lines."""
    found = {"date": None, "readings": "", "location": "", "title": "", "rite": ""}
    leftovers = []

    for line in header:
        date = parse_date(line)
        if date and not found["date"]:
            found["date"] = date
            # A line that is *only* a date contributes nothing else.
            if len(LONG_DATE.sub("", line).strip(" ,.-–—")) < 3:
                continue
        citation = CITATION.search(line)
        if citation and not found["readings"]:
            # Only split when the line is genuinely carrying several fields at
            # once, which a date on the same line signals. Splitting on the
            # citation's position instead cut "Song of Songs 3:1-4b" down to
            # "Songs 3:1-4b", because the pattern only recognises a one-word book.
            if not parse_date(line):
                found["readings"] = line.strip()
                continue
            # Otherwise the line carries a citation *and* other things --
            # "Feb. 6, 2026 Healing Mass/Paul Miki (St. Joe's) -- Mark 6:14-29".
            # Keep the citation, hand the rest back to the other rules.
            found["readings"] = line[citation.start():].strip()
            line = line[: citation.start()].strip(" ,.-–—")
            if not line:
                continue
        leftovers.append(line)

    for line in leftovers:
        m = PAREN_LOCATION.search(line)
        if m:
            inner = m.group(1).strip()
            # A trailing parenthetical is often the location -- "(St. Anne)" --
            # but not always. Taking it blindly filed a reading citation, a rite,
            # and a Gospel theme as locations. Only claim it when it is none of
            # those; anything else is left in the title, where it is visible.
            if CITATION.search(inner):
                if not found["readings"]:
                    found["readings"] = inner
                line = PAREN_LOCATION.sub("", line).strip()
            elif inner.lower() in ("maronite", "chaldean", "roman"):
                found["rite"] = inner.title()
                line = PAREN_LOCATION.sub("", line).strip()
            elif not found["location"] and is_location(inner):
                outside = PAREN_LOCATION.sub("", line).strip(" ,.-–—")
                if outside and names_a_venue(outside):
                    # The line itself names the venue; the bracket qualifies it.
                    found["location"] = line.strip(" ,.-–—")
                    line = ""
                else:
                    found["location"] = inner
                    line = PAREN_LOCATION.sub("", line).strip()  # keeps the event
        if line and line.strip(" ,.-–—").lower() in ignore_names:
            continue  # the preacher's own name, not the liturgical day
        stripped_line = line.strip(" ,.-–—")
        if stripped_line and any(stripped_line.lower() == v.lower() for v in venues):
            if not found["location"]:
                found["location"] = stripped_line
            continue  # a venue line, so the day is still to come
        if line and not found["title"]:
            found["title"] = line.strip(" ,.-–—")
        elif line and not found["location"] and looks_like_place(line):
            # A later header line naming a church or school is the venue. Lines
            # without a place word are left alone -- they are usually more
            # liturgical detail, and guessing would fill the field with a feast.
            found["location"] = line.strip(" ,.-–—")

    return found


# Rite detection.
#
# Roman is the default and stays empty. The Eastern-rite homilies in this archive
# are identifiable from their filenames: 18 say "Chaldean" outright, and the
# Maronite ones name seasons the Roman calendar does not have -- Pentecost counted
# in numbered weeks, Sundays "after Epiphany" or "after Holy Cross", the Season of
# Announcements, and the Sundays of the Faithful Departed and of the Righteous and
# Just. Patterns are deliberately narrow: a Roman homily preached on Pentecost
# Sunday must not be swept up, so "of Pentecost" only counts with an ordinal in
# front of it.
MARONITE_MARKERS = [
    re.compile(r"\bmaronite\b", re.I),
    re.compile(r"\b\d+(?:st|nd|rd|th)\s+\w+\s+of\s+Pentecost\b", re.I),
    re.compile(r"\bafter\s+Epiphany\b", re.I),
    re.compile(r"\bafter\s+Holy\s+Cross\b", re.I),
    re.compile(r"\bof\s+Resurrection\b", re.I),
    re.compile(r"\bAnnouncement\s+to\b", re.I),
    re.compile(r"\bFaithful\s+Departed\b", re.I),
    re.compile(r"\bRighteous\s+and\s+Just\b", re.I),
]


RITE_WORD = re.compile(r"\b(Maronite|Chaldean)\b", re.I)

# Words that mark a header line as a place rather than more liturgical detail.
# Deliberately narrow: an ambiguous line is left for the locations worksheet
# rather than guessed at, because a wrong location is worse than a missing one.
PLACE_WORDS = re.compile(
    r"\b(church|chapel|parish|cathedral|basilica|hall|school|academy|"
    r"university|college|mission|hospital|center|centre|abbey|priory|"
    r"seminary|retreat)\b", re.I)

# ...but a liturgical day can contain a place word too. "2nd Sunday of the Church"
# is a Chaldean season, not a venue, and it was filed as one until this guard.
DAY_WORDS = re.compile(
    r"\b(sun|sunday|mon|monday|tue|tues|tuesday|wed|wednesday|thu|thurs|"
    r"thursday|fri|friday|sat|saturday|"
    r"advent|lent|easter|epiphany|pentecost|ordinary|triduum|"
    r"feast|solemnity|memorial|vigil|holy\s+cross|resurrection|"
    r"\d+(?:st|nd|rd|th)\s+(?:sun|week)|ot)\b", re.I)


# A parenthetical after a liturgical day is usually the venue -- "(St. Anne)" --
# but across this archive it is just as often the Gospel theme: "(Healing of
# Paralytic)", "(Prodigal Son)", "(Beatitudes)". Frequency alone does not separate
# them, so the test is structural: a place is named like one.
PLACE_PREFIX = re.compile(
    r"^(?:St\.|Ste\.|Ss\.|Saints?\b|Our\s+Lady\b|OLO?\b|Holy\s+Name\b)", re.I)
CITY_STATE = re.compile(r",\s*[A-Z]{2}\b")


def looks_like_place(line):
    return bool(PLACE_WORDS.search(line)) and not DAY_WORDS.search(line)


VENUE_NOUN = re.compile(
    r"\b(church|chapel|parish|cathedral|basilica|hall|school|academy|"
    r"university|college|mission|hospital|center|centre|abbey|priory|"
    r"seminary)\s*$", re.I)


def names_a_venue(text):
    """Whether this text is a venue *name*, not an event that mentions a place.

    "Campion Chapel" and "St. Anne School" name venues; "End of School Year
    Mass" and "Parish Family Lenten Reconciliation" do not, though both contain a
    place word. The difference is what the phrase ends in.
    """
    text = text.strip(" ,.-–—")
    if not text:
        return False
    if VENUE_NOUN.search(text):
        return True
    # "St. Anne" is a place; "Saints Martha, Mary, and Lazarus" and "St. Leo the
    # Great/Mon. 32nd OT" are feasts. A saint's name is a venue only when it is
    # short and carries no day vocabulary.
    return bool(PLACE_PREFIX.match(text)
                and len(text.split()) <= 3
                and not DAY_WORDS.search(text))


def known_locations():
    """Venues confirmed by hand, from config.toml -- names stay out of the repo."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config.toml")
    if not os.path.exists(path):
        return []
    import tomllib
    with open(path, "rb") as f:
        return [str(v).strip() for v in tomllib.load(f).get("known_locations", [])]


def is_location(text):
    """Whether a parenthetical names a venue rather than a theme or a feast."""
    text = text.strip()
    if not text or DAY_WORDS.search(text):
        return False  # "Feast of St. Joseph" is a day, not a place
    if any(text.lower() == k.lower() for k in known_locations()):
        return True
    return bool(PLACE_PREFIX.match(text)
                or PLACE_WORDS.search(text)
                or CITY_STATE.search(text))


def location_aliases(drafts_dir):
    """Spelling variants of one venue, from _location-aliases.txt beside the drafts.

    "CHS" and "Campion Chapel (CHS)" are the same place written two ways. Kept
    with the drafts rather than in the repo, because venue names are parish data.

    Format:  <as written> = <canonical>
    """
    path = os.path.join(drafts_dir, "_location-aliases.txt")
    out = {}
    if not os.path.exists(path):
        return out
    for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            sys.exit(f"{path}:{lineno}: expected '<as written> = <canonical>'")
        written, canonical = line.split("=", 1)
        out[written.strip().lower()] = canonical.strip()
    return out


# A dash inside a header title often separates the liturgical day from something
# else: "11th Sun Pentecost—St. Anthony of the Desert" is day + venue, and
# "Chaldean Mission – 4th Sun. of Advent" is the same two things the other way
# round. "Tues 15th OT—July 14, 2025" is day + date. Whichever side carries the
# day words is the day; the other side is a venue unless it parses as a date.
DASH_SPLIT = re.compile(r"\s*[—–]\s*|\s+-\s+")


def split_day_and_place(title):
    """(day, place) -- place is '' when the title is only a day."""
    parts = [p.strip(" ,.-–—") for p in DASH_SPLIT.split(title) if p.strip(" ,.-–—")]
    if len(parts) != 2:
        return title, ""

    # A part that is a date is never the day-name, whatever else it looks like.
    dated = [bool(parse_date(p)) for p in parts]
    if dated[0] != dated[1]:
        return (parts[1] if dated[0] else parts[0]), ""

    dayish = [bool(DAY_WORDS.search(p)) for p in parts]
    if dayish[0] == dayish[1]:
        return title, ""  # both or neither look like a day; leave it alone

    day = parts[0] if dayish[0] else parts[1]
    return day, parts[1] if dayish[0] else parts[0]


def presider_names():
    """Names to ignore when they appear as a header line, from config.toml.

    Some documents open with the preacher's own name, which was being read as the
    liturgical day. Configured rather than hardcoded, so no real name lives in
    this repository.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config.toml")
    if not os.path.exists(path):
        return []
    import tomllib
    with open(path, "rb") as f:
        value = tomllib.load(f).get("presider_names", [])
    return [str(v).strip().lower() for v in value if str(v).strip()]


def rite_from_name(name):
    """'', 'Maronite' or 'Chaldean'. Empty means Roman, which is the common case.

    A guess, and reported as one -- the importer prints every non-Roman
    classification so it can be checked rather than trusted.
    """
    if re.search(r"\bchaldean\b", name, re.I):
        return "Chaldean"
    if any(p.search(name) for p in MARONITE_MARKERS):
        return "Maronite"
    return ""


# Values that belong in `variant`, not in the occasion or the day.
VARIANT_WORDS = re.compile(
    r"\b(manuscript|preaching\s+text|with(?:out)?\s+baptisms)\b", re.I)

# Things that are not points in the liturgical calendar. A day field should hold
# only what a calendar would name; a Novena, a baptism or an end-of-school Mass is
# the occasion of the celebration, not the day itself.
OCCASION_WORDS = re.compile(
    r"\b(novena(?:\s+of\s+grace)?(?:\s+day\s+\d+)?|"
    r"end\s+of\s+school(?:\s+year)?(?:\s+mass)?|"
    r"house\s+prayer\s+service|prayer\s+service|reconciliation\s+service|"
    r"parish\s+family\s+lenten\s+reconciliation|"
    r"may\s+crowning(?:\s+of\s+mary)?|graduation|orientation|"
    r"young\s+priests\s+gathering|retreat|"
    r"funeral|wedding|baptisms?|healing\s+mass|healing)\b", re.I)

# "Gospel Reflection" and "Reflection" describe the kind of document, not the
# occasion of a celebration, so they are dropped rather than recorded.
NOT_AN_OCCASION = re.compile(r"^(?:gospel\s+)?reflection$", re.I)

# Two or three capitalised words and nothing else: a person, not an occasion.
PERSON_NAME = re.compile(r"^(?:[A-Z][\w’']+\s+){1,2}[A-Z][\w’']+$")


def tidy(text):
    """Collapse the punctuation left behind when a phrase is lifted out."""
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\(\s*\)", "", text)
    # Lifting a venue out of "(SU Novena…)" takes the opening bracket with it and
    # strands the closing one. Drop whichever bracket has no partner.
    if text.count("(") != text.count(")"):
        while text.count(")") > text.count("("):
            text = text.replace(")", "", 1)
        while text.count("(") > text.count(")"):
            text = "".join(text.rsplit("(", 1))
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s*[—–/,]\s*$", "", text)
    text = re.sub(r"^\s*[—–/,]\s*", "", text)
    return text.strip(" ,.-–—/")


def lift(pattern, source, skip_brackets=False):
    """(remainder, lifted) -- pull every match of `pattern` out of `source`.

    With skip_brackets, text inside parentheses is left alone: it is usually a
    Gospel theme, and lifting a word out of "(Healing of Paralytic)" leaves the
    mangled "( of Paralytic)".
    """
    if skip_brackets:
        segments = re.split(r"(\([^)]*\))", source)
        out, found = [], []
        for segment in segments:
            if segment.startswith("("):
                out.append(segment)
                continue
            found += [m.group(0).strip() for m in pattern.finditer(segment)]
            out.append(pattern.sub("", segment))
        if not found:
            return source, ""
        return tidy("".join(out)), " ".join(dict.fromkeys(found))

    found = [m.group(0).strip() for m in pattern.finditer(source)]
    if not found:
        return source, ""
    return tidy(pattern.sub("", source)), " ".join(dict.fromkeys(found))


FEAST_WORDS = re.compile(
    r"\b(feast|solemnity|memorial|octave|annunciation|assumption|ascension|"
    r"conception|nativity|epiphany|magnificat|transfiguration|corpus\s+christi|"
    r"all\s+saints|all\s+souls|christ\s+the\s+king)\b", re.I)


def looks_liturgical(text):
    """Whether this names a point in a liturgical calendar."""
    text = tidy(text)
    if not text:
        return False
    # "Sunday, December 7, 2025" is a date wearing a weekday, not a liturgical
    # day. Strip the date and see whether anything of substance is left.
    without_date = tidy(LONG_DATE.sub("", text))
    if parse_date(text) and len(re.sub(r"\W+", "", without_date)) <= 9:
        return False
    return bool(DAY_WORDS.search(text) or FEAST_WORDS.search(text)
                or PLACE_PREFIX.match(text))


def overlaps(candidate, existing):
    """Whether `existing` already says what `candidate` says.

    The occasion often comes from the filename and the day from the header, and
    they describe the same thing in different words -- "End of School St Clare"
    and "End of School Year Mass". Appending both reads as a stutter.
    """
    if not existing:
        return False
    a = set(re.findall(r"\w+", candidate.lower()))
    b = set(re.findall(r"\w+", existing.lower()))
    return bool(a) and len(a & b) / len(a) >= 0.5


def lift_bracketed_occasion(day):
    """(day, occasion) -- lift a parenthetical that is wholly an occasion.

    "(Novena of Grace Day 7)" is an occasion and belongs in its own field.
    "(Healing of Paralytic)" is a Gospel theme that happens to contain an
    occasion word, and lifting from it leaves "( of Paralytic)". The test is
    whether anything of substance survives removing the occasion vocabulary.
    """
    for match in list(re.finditer(r"\(([^)]*)\)", day)):
        inner = match.group(1).strip()
        if not inner or not OCCASION_WORDS.search(inner):
            continue
        remainder = re.sub(r"\W+", "", OCCASION_WORDS.sub("", inner))
        if len(remainder) <= 2:
            return tidy(day.replace(match.group(0), "")), inner
    return day, ""


def presider_words():
    """Individual name tokens to strip from a filename-derived occasion.

    Filenames carry the preacher's surname -- "Novena of Grace Day 5 Smith" --
    which is not part of the occasion.
    """
    tokens = set()
    for full in presider_names():
        words = [w for w in re.findall(r"[A-Za-z]{3,}", full)
                 if w.lower() not in ("the", "rev", "father")]
        if words:
            tokens.add(words[-1].lower())  # surname only
    return tokens


def tidy_readings(text):
    """Strip what is not part of a citation from the readings line."""
    if not text:
        return text
    # A citation inside brackets with prose outside: "Announcement to Joseph
    # (Matt 1:18-25)". The brackets hold the reference.
    brackets = re.findall(r"\(([^)]*)\)", text)
    outside = tidy(re.sub(r"\([^)]*\)", "", text))
    for inner in brackets:
        if CITATION.search(inner) and not CITATION.search(outside):
            return tidy(inner)
    # Bracketed notes are left alone: "(Beatitudes)" and "(Magnificat)" name the
    # Gospel, and only a reader can tell those from an attribution like
    # "(Barron)". That distinction goes in _metadata-overrides.txt.
    return tidy(text)


def normalize_fields(meta, aliases, locations):
    """Move values into the field they belong to, after extraction.

    Extraction reads whatever the document's header happens to put on a line, and
    a line often carries two things at once: a day and a venue, an occasion and a
    variant. Sorting them out once here is simpler than teaching every extraction
    path the same rules.
    """
    day = str(meta.get("title", ""))
    occasion = str(meta.get("occasion", ""))
    location = str(meta.get("location", ""))
    variant = str(meta.get("variant", ""))

    # A known venue can appear in any of them, and is removed from all of them --
    # otherwise "Durocher House Prayer Service" loses "House" to the occasion
    # vocabulary and leaves "Durocher" behind as a liturgical day.
    for known in sorted(locations, key=len, reverse=True):
        pattern = re.compile(rf"\(?\b{re.escape(known)}\b\)?", re.I)
        if pattern.search(day):
            location = location or known
            day = tidy(pattern.sub("", day))
        if pattern.search(occasion):
            location = location or known
            occasion = tidy(pattern.sub("", occasion))

    # Manuscript / Preaching Text / with baptisms belong in `variant`. Strip them
    # from BOTH fields even once one has supplied the value, or the leftover
    # "With Baptisms" in the day gets lifted again as an occasion.
    occasion, from_occasion = lift(VARIANT_WORDS, occasion)
    day, from_day = lift(VARIANT_WORDS, day)
    if not variant:
        variant = (from_occasion or from_day).title()

    # A parenthetical that is wholly an occasion moves out of the day.
    day, bracketed = lift_bracketed_occasion(day)
    if bracketed and not overlaps(bracketed, occasion):
        occasion = f"{occasion} {bracketed}".strip() if occasion else bracketed

    # A day field holds calendar days. Anything else is the occasion.
    day, lifted = lift(OCCASION_WORDS, day, skip_brackets=True)
    if lifted and not overlaps(lifted, occasion):
        occasion = f"{occasion} {lifted}".strip() if occasion else lifted

    rite_word = re.compile(r"\b(Maronite|Chaldean|Roman)\b", re.I)
    day = tidy(rite_word.sub("", day))
    occasion = tidy(rite_word.sub("", occasion))

    # A liturgical day belongs in the day field wherever it was found. The
    # occasion comes from the filename and the day from the header, so the same
    # feast often arrives twice -- or only in whichever one existed.
    # A date is not a liturgical day, however it is written.
    if day and not looks_liturgical(day) and parse_date(day):
        day = ""

    if occasion and looks_liturgical(occasion) and not day:
        day, occasion = occasion, ""
    elif occasion and day and overlaps(occasion, day):
        occasion = ""

    # An occasion that merely repeats the venue is not an occasion.
    if occasion and location and occasion.lower() in location.lower():
        occasion = ""

    # A Mass time is not part of the day's name.
    day = tidy(re.sub(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", "", day, flags=re.I))

    day = tidy(day)
    if day and not looks_liturgical(day):
        # A funeral names the deceased and a baptism the child; neither is a
        # point in a calendar. Keep it as the occasion if nothing else is there.
        if not occasion:
            occasion = day
        day = ""

    # A Gospel theme often appears in both the filename and the readings line --
    # "Parish Family Lenten Reconciliation Prodigal Son" and "(Prodigal Son)".
    readings = str(meta.get("preached", ""))
    bracketed = re.findall(r"\(([^)]*)\)", readings)
    for theme in bracketed:
        theme = theme.strip()
        if theme and len(theme.split()) >= 2 and theme.lower() in occasion.lower():
            occasion = tidy(re.sub(re.escape(theme), "", occasion, flags=re.I))

    # The preacher's surname rides along in filenames; it is not an occasion.
    if occasion:
        kept = [w for w in occasion.split()
                if re.sub(r"\W", "", w).lower() not in presider_words()]
        occasion = tidy(" ".join(kept))

    # "Funeral Smith" -- the rite is the occasion, the name is not.
    occasion = tidy(re.sub(r"\b(funeral|baptism)\b\s+\S+.*$", r"\1",
                           occasion, flags=re.I))

    # A bare personal name is not an occasion either. What kind of celebration it
    # was comes from the filename, which says "Funeral" or "Baptism" outright.
    if occasion and PERSON_NAME.match(occasion) and not OCCASION_WORDS.search(occasion):
        from_source = OCCASION_WORDS.search(str(meta.get("source", "")))
        occasion = from_source.group(0).title() if from_source else ""

    if NOT_AN_OCCASION.match(occasion.strip()):
        occasion = ""

    day = re.sub(r"\bSs\.\s*", "Saints ", day)

    meta["title"] = day
    meta["occasion"] = tidy(occasion)
    meta["preached"] = homilist.normalize_citations(
        tidy_readings(str(meta.get("preached", ""))))
    # The Eastern days used to be left alone here, which is why they were the
    # only ones still written six ways. `rite` widens the season vocabulary
    # rather than switching the rule off.
    meta["title"] = homilist.standardize_day(
        meta["title"], rite=meta.get("rite"))
    meta["variant"] = tidy(variant)
    meta["location"] = aliases_apply(tidy(location), aliases)
    return meta


def aliases_apply(location, aliases):
    """Canonical spelling. An exact rule wins; otherwise the longest prefix rule."""
    if not location:
        return location
    exact = aliases.get(location.strip().lower())
    if exact is not None:
        return exact
    best = None
    for written, canonical in aliases.items():
        if written.endswith("*") and location.lower().startswith(written[:-1]):
            if best is None or len(written) > len(best[0]):
                best = (written, canonical)
    return best[1] if best else location


def lectionary_from_name(name):
    # Not followed by another -NN: "Baptism Homily 24-01-20" is a date, and was
    # being read as lectionary 24.
    m = re.search(r"\bHomily\s+(\d{1,3})(?!\s*-\s*\d)\b", name)
    return int(m.group(1)) if m else None


def suffix_from_name(name):
    """Whatever distinguishes this homily beyond `Homily NNN` -- 'Maple Court',
    'with baptisms', 'Preaching Text'. Kept for the rendered filename."""
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"\bHomily\s+\d{1,3}(?!\s*-\s*\d)\b", "", stem)
    stem = re.sub(r"\b20\d\d-\d{2}-\d{2}\b", "", stem)  # a whole yyyy-mm-dd
    stem = re.sub(r"\b\d{2}-\d{2}-\d{2}\b", "", stem)   # a whole yy-mm-dd
    stem = re.sub(r"\b20\d\d\b", "", stem)
    stem = re.sub(r"\bHomily\b", "", stem)
    return re.sub(r"\s+", " ", stem).strip(" -–—")


# ---------------------------------------------------------------- summaries

def metadata_overrides(drafts_dir):
    """Per-source field corrections, from _metadata-overrides.txt.

    A few documents cram everything onto one line, or name a memorial in a form
    no rule can recognise as one. Rather than bending the extraction around a
    single file, the answer is recorded beside the drafts and re-applied on every
    import -- the same arrangement as the date corrections.

    Format:  <source .docx> | <field> = <value>
    """
    path = os.path.join(drafts_dir, "_metadata-overrides.txt")
    out = {}
    if not os.path.exists(path):
        return out
    for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "|" not in line or "=" not in line:
            sys.exit(f"{path}:{lineno}: expected '<file.docx> | <field> = <value>'")
        source, rest = line.split("|", 1)
        field, value = rest.split("=", 1)
        out.setdefault(source.strip(), {})[field.strip()] = value.strip()
    return out


def date_overrides(drafts_dir):
    """Corrections keyed by source filename, from _date-overrides.txt.

    Some documents disagree with themselves: "Friday 12th OT" printed with a
    Thursday date. The .docx is never edited -- it is the archive -- so the
    correction lives beside the drafts and is re-applied on every import.
    Without this, a re-import silently restores the wrong date.

    Format:  <source .docx filename> = YYYY-MM-DD   # optional reason
    """
    path = os.path.join(drafts_dir, "_date-overrides.txt")
    out = {}
    if not os.path.exists(path):
        return out
    for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            sys.exit(f"{path}:{lineno}: expected '<file.docx> = YYYY-MM-DD'")
        name, value = line.split("=", 1)
        try:
            out[name.strip()] = datetime.date.fromisoformat(value.strip())
        except ValueError:
            sys.exit(f"{path}:{lineno}: {value.strip()!r} is not a YYYY-MM-DD date")
    return out


def summary_for(docx_path):
    """The matching file in Homily Summaries/, if there is one."""
    # The summaries sit at the archive root, not beside the .docx files -- which
    # stopped being the same directory when the documents moved into Word/.
    folder = os.path.join(homilist.archive_dir(), "Homily Summaries")
    stem = os.path.splitext(os.path.basename(docx_path))[0]
    candidate = os.path.join(folder, f"{stem} Summary.md")
    if os.path.exists(candidate):
        return open(candidate, encoding="utf-8").read()
    return None


def date_from_summary(text):
    if not text:
        return None
    m = re.search(r"\*\*Date:\*\*\s*(.+)", text)
    if not m:
        return None
    return parse_date(m.group(1))


# ---------------------------------------------------------------- USCCB lookup

class Blocked(Exception):
    """USCCB refused the request. Stop asking rather than hammering."""


# One request per second, with a User-Agent that says who is calling. A bulk
# sweep of this site earned a 403 during development -- which then looked
# exactly like "no match for that date", so a block must be distinguishable
# from an answer.
_LAST_REQUEST = [0.0]
REQUEST_INTERVAL = 1.0
USER_AGENT = "homilist-cli/1.0 (personal homily archive tool; low volume)"


def usccb_lectionary(date, cache_dir):
    """The lectionary number USCCB lists for a date, or None if the page has none.

    Raises Blocked if the server refuses. Cached on disk, so a re-run costs
    nothing and an interrupted sweep resumes where it stopped.
    """
    import time

    import requests

    os.makedirs(cache_dir, exist_ok=True)
    stamp = date.strftime("%m%d%y")
    path = os.path.join(cache_dir, f"{stamp}.html")

    if not os.path.exists(path):
        wait = REQUEST_INTERVAL - (time.monotonic() - _LAST_REQUEST[0])
        if wait > 0:
            time.sleep(wait)
        url = f"https://bible.usccb.org/bible/readings/{stamp}.cfm"
        try:
            res = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        except Exception as exc:  # noqa: BLE001
            raise Blocked(f"network error fetching {url}: {exc}") from exc
        finally:
            _LAST_REQUEST[0] = time.monotonic()
        if res.status_code in (403, 429, 503):
            raise Blocked(
                f"USCCB returned {res.status_code} -- rate limited or blocked. "
                "Wait before resuming; cached dates are kept."
            )
        if not res.ok:
            return None  # a genuinely missing page, not a refusal
        with open(path, "wb") as f:
            f.write(res.content)

    number, _ = _scrape_cached(path)
    return number


def _scrape_cached(path):
    """(lectionary number, canonical day) from a saved USCCB page."""
    try:
        number, day_string, _ = homilist.scrape_readings(open(path, encoding="utf-8").read())
    except (homilist.ScrapingException, OSError):
        return None, ""
    return (number if isinstance(number, int) else None), day_string or ""


def cached_day_string(date, cache_dir):
    """USCCB's own name for a date -- from the cache only, never the network.

    lectionary_string belongs to USCCB, so it is filled from USCCB or left empty;
    guessing it from the document would put a hand shorthand in a field that is
    supposed to be canonical. Reading only the cache keeps this free, keeps it
    working offline, and lets the remaining pages fill in whenever the sweep
    finishes.
    """
    if not date:
        return ""
    path = os.path.join(cache_dir, f"{date.strftime('%m%d%y')}.html")
    if not os.path.exists(path):
        return ""
    return _scrape_cached(path)[1]


def date_from_lectionary(number, around, cache_dir, radius=32, log=None,
                        allow_network=True):
    """The date near `around` whose lectionary number is `number`.

    The local calendar answers first: it needs no network, cannot be refused,
    and is checked against every homily whose date is already known. USCCB is
    kept only as a fallback for numbers the calendar does not carry -- most of
    the sanctoral cycle -- and is skipped entirely when it is unreachable.
    """
    local = liturgical.dates_for_lectionary(number, around, radius)
    if local:
        best = local[0]
        if log is not None:
            delta = (best - around).days
            log.append(f"lectionary {number} is {liturgical.describe(best)}, "
                       f"which falls on {best} ({delta:+d} days from the file "
                       f"timestamp) — computed locally")
        return best
    if not allow_network:
        return None
    return _date_from_lectionary_usccb(number, around, cache_dir, radius, log)


def _date_from_lectionary_usccb(number, around, cache_dir, radius=32, log=None):
    """Find the date near `around` whose lectionary number is `number`.

    The window comes from the file's modified date, which lands within 30 days of
    the real date in every measured case. Candidates are tried nearest-first, so
    the usual answer costs a handful of requests rather than a sweep.
    """
    if number is None or around is None:
        return None
    for offset in range(0, radius + 1):
        for delta in ((0,) if offset == 0 else (offset, -offset)):
            candidate = around + datetime.timedelta(days=delta)
            got = usccb_lectionary(candidate, cache_dir)  # may raise Blocked
            if got == number:
                if log is not None:
                    log.append(f"matched lectionary {number} at {candidate} "
                               f"({delta:+d} days from the file timestamp)")
                return candidate
    return None


# ---------------------------------------------------------------- assembly

def build_draft(docx_path, cache_dir, allow_network=True, overrides=None,
                aliases=None, field_overrides=None):
    name = os.path.basename(docx_path)
    paras = paragraphs(docx_path)
    if not paras:
        raise ValueError("no text found in the document")

    header_lines, body = split_header(paras)
    header = interpret_header(header_lines, ignore_names=presider_names(),
                              venues=known_locations())

    # The rite can be named in the header text itself -- "Maronite 5th Sunday of
    # Lent" -- not only in a trailing parenthetical or the filename.
    rite = rite_from_name(name) or header.get("rite", "")
    if not rite:
        found = RITE_WORD.search(header["title"])
        if found:
            rite = found.group(1).title()
    # A non-Roman homily has no Roman lectionary number, so neither the number nor
    # the USCCB lookup that depends on it applies.
    lect = None if rite else lectionary_from_name(name)
    summary = summary_for(docx_path)
    notes = []
    aliases = aliases or {}
    override = (overrides or {}).get(name)
    if override:
        date, source = override, "_date-overrides.txt"
    else:
        date, source = header["date"], "text header"
    if not date and ambiguous_short_date(name):
        # Both readings of the filename are real dates, so it decides nothing.
        # The summary states its date in words and is not ambiguous.
        from_summary = date_from_summary(summary)
        if from_summary:
            date, source = from_summary, "summary (filename date is ambiguous)"
        else:
            notes.append(f"filename date {name} is ambiguous (yy-mm-dd or "
                         f"mm-dd-yy) and no summary resolves it")
    if not date:
        date, source = parse_date(name), "filename"
    if not date:
        date, source = date_from_summary(summary), "summary"
    if not date:
        modified = docx_modified(docx_path)
        date = date_from_lectionary(lect, modified, cache_dir, log=notes,
                                    allow_network=allow_network)
        source = "lectionary number + file timestamp window"
    if not date:
        source = "UNRESOLVED"

    # A non-Roman homily is identified by its liturgical day; with no header to
    # read one from, the filename is the best available title.
    day, dashed_place = split_day_and_place(header["title"])
    if dashed_place:
        bracket = PAREN_LOCATION.search(dashed_place)
        if bracket and is_location(bracket.group(1)):
            # "Lord's Supper (St. Anne)" -- the bracket is the venue, the rest
            # is the theme and belongs with the day.
            outside = PAREN_LOCATION.sub("", dashed_place).strip(" ,.-–—")
            if outside:
                day = f"{day} — {outside}" if day else outside
            dashed_place = bracket.group(1).strip()
        elif not is_location(dashed_place):
            # Not a venue at all: keep it with the day rather than inventing one.
            day = f"{day} — {dashed_place}" if day else dashed_place
            dashed_place = ""

        if dashed_place:
            if not header["location"]:
                header["location"] = dashed_place
            elif dashed_place not in header["location"]:
                # The dash gave the venue, the parenthetical gave its city.
                header["location"] = f"{dashed_place} ({header['location']})"
    if rite and not day:
        day = suffix_from_name(name)

    metadata = {
        "date": date.isoformat() if date else "",
        "rite": rite,
        "lectionary_number": lect or "",
        # The day read out of the document is *this* homily's short display
        # form, not the calendar's canonical name for the date. USCCB owns
        # lectionary_string; a hand shorthand written there would be silently
        # replaced the first time a lookup ran.
        "lectionary_string": cached_day_string(date, cache_dir) if not rite else "",
        "title": day,
        "occasion": suffix_from_name(name),
        "location": header["location"],
        "readings": "",
        "preached": header["readings"],
        "variant": "",
        "source": name,
    }

    # A document that never printed its citation line can still be answered:
    # the lectionary number and the date give the readings outright. Only ever
    # fills a blank -- what the document said always wins.
    if date and lect and not rite and not metadata["preached"]:
        liturgical_year = date.year + (1 if date >= liturgical.advent_start(date.year) else 0)
        line = lectionary.preached_line(lect, "I" if liturgical_year % 2 else "II")
        if line:
            metadata["preached"] = line
            notes.append(f"readings from the lectionary table for {lect}")

    metadata = normalize_fields(metadata, aliases, known_locations())
    for field, value in (field_overrides or {}).get(name, {}).items():
        # An override is a correction, not an exemption from the conventions.
        # Applied raw, a day typed with a slash kept its slash while every
        # extracted day around it was rewritten -- the overrides file quietly
        # became the one place the rules did not reach.
        if field == "title":
            value = homilist.standardize_day(value, rite=metadata.get("rite"))
        elif field == "location":
            value = aliases_apply(value, aliases)
        elif field in ("preached", "readings"):
            value = homilist.normalize_citations(value)
        metadata[field] = value

    return {
        "metadata": metadata,
        "body": "\n\n".join(md for _, md in body),
        "date": date,
        "date_source": source,
        "notes": notes,
        "header_lines": header_lines,
        "source_name": name,
    }


def stale_drafts(drafts_dir, source, keep):
    """Other drafts claiming `source` -- leftovers from an earlier filename."""
    if not source:
        return []
    out = []
    for _, path in homilist.homily_files(drafts_dir):
        if os.path.abspath(path) == os.path.abspath(keep):
            continue
        try:
            meta, _ = homilist.split_frontmatter(open(path, encoding="utf-8").read())
        except homilist.FrontmatterError:
            continue
        if str(meta.get("source", "")).strip() == source:
            out.append(path)
    return out


def write_report(paths, out_path, overrides=None):
    """A worksheet for the homilies whose date could not be established.

    Everything known about each one, gathered in one place so a human can date it
    by recognition -- which is faster than any lookup for a homily you preached.
    Fill in the date column, then re-run the importer.
    """
    overrides = overrides or {}
    # A homily whose header carries no date is not unresolved if the lectionary
    # number already placed it. Before the local calendar almost nothing did,
    # so the report counted them all and now overstates the work left.
    imported = set()
    for _, path in homilist.homily_files(homilist.homilies_dir()):
        try:
            meta, _body = homilist.split_frontmatter(open(path, encoding="utf-8").read())
        except homilist.FrontmatterError:
            continue
        source = str(meta.get("source", "")).strip()
        if source:
            imported.add(source)
    rows = []
    for path in paths:
        name = os.path.basename(path)
        try:
            paras = paragraphs(path)
        except Exception:  # noqa: BLE001
            paras = []
        header_lines, body = split_header(paras)
        header = interpret_header(header_lines, ignore_names=presider_names(),
                              venues=known_locations())
        if header["date"] or parse_date(name) or name in overrides:
            continue  # already datable, or dated by hand; not our problem
        if name in imported:
            continue  # the calendar resolved it from its lectionary number

        summary = summary_for(path)
        summary_date = None
        if summary:
            m = re.search(r"\*\*Date:\*\*\s*(.+)", summary)
            summary_date = m.group(1).strip()[:90] if m else None

        rows.append({
            "name": name,
            "rite": rite_from_name(name) or "Roman",
            "lect": lectionary_from_name(name) if not rite_from_name(name) else None,
            "modified": docx_modified(path),
            "opening": (body[0][0] if body else "")[:110],
            "readings": header["readings"],
            "summary_date": summary_date,
        })

    rows.sort(key=lambda r: (r["rite"] != "Roman", r["modified"] or datetime.date.min))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Unresolved homily dates\n\n")
        f.write(f"{len(rows)} homilies whose date could not be established from the "
                "document, the filename, or a summary.\n\n")
        f.write("The **window** is the file's own `modified` timestamp. Measured "
                "against the homilies that do carry a date, it is exact 74% of the "
                "time and within 30 days in every case — so the real date is "
                "almost certainly within a month of it.\n\n")
        f.write("Fill in a date, rename the file, or just tell the importer — then "
                "re-run it.\n\n")
        for rite in ("Roman", "Maronite", "Chaldean"):
            group = [r for r in rows if r["rite"] == rite]
            if not group:
                continue
            f.write(f"\n## {rite} ({len(group)})\n\n")
            if rite != "Roman":
                f.write("_No Roman lectionary number; USCCB cannot help with "
                        "these._\n\n")
            for r in group:
                f.write(f"### {r['name']}\n\n")
                f.write(f"- **window** {r['modified'] or 'unknown'}\n")
                if r["lect"]:
                    f.write(f"- **lectionary** {r['lect']}\n")
                if r["readings"]:
                    f.write(f"- **readings** {r['readings']}\n")
                if r["summary_date"]:
                    f.write(f"- **summary says** {r['summary_date']}\n")
                if r["opening"]:
                    f.write(f"- **opens** “{r['opening']}…”\n")
                f.write("- **date:** \n\n")
    print(f"wrote {out_path} ({len(rows)} unresolved)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", nargs="+")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be written, touch nothing")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing draft")
    ap.add_argument("--no-network", action="store_true",
                    help="skip the USCCB lookup for undated homilies")
    ap.add_argument("--report", metavar="FILE",
                    help="write a dating worksheet for everything unresolved, "
                         "instead of importing")
    args = ap.parse_args()

    # Filter here, before any branch reads the list. Doing it further down meant
    # --report ran on the unfiltered one, and two Word owner files sat in the
    # unresolved report permanently -- there is no date to give them.
    args.docx = homilist.documents(args.docx)

    # homilies_dir() already points at the drafts folder (config.toml), which is
    # where every other command in this repo reads and writes.
    drafts = homilist.homilies_dir()
    if args.report:
        return write_report(args.docx, args.report, date_overrides(drafts))

    cache = os.path.join(homilist.tmp_dir(), "usccb")
    overrides = date_overrides(drafts)
    aliases = location_aliases(drafts)
    field_overrides = metadata_overrides(drafts)
    unresolved = []

    for path in args.docx:
        try:
            draft = build_draft(path, cache, allow_network=not args.no_network,
                                overrides=overrides, aliases=aliases,
                                field_overrides=field_overrides)
        except Blocked as exc:
            print(f"\n⛔ {exc}")
            print("   Stopping. Re-run later; already-fetched dates are cached.")
            print("   Use --no-network to import everything datable without lookups.")
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {os.path.basename(path)}: {exc}")
            unresolved.append(path)
            continue

        meta, date = draft["metadata"], draft["date"]
        print(f"\n=== {draft['source_name']} ===")
        print(f"  date        {meta['date'] or '(unresolved)'}   [{draft['date_source']}]")
        for note in draft["notes"]:
            print(f"              {note}")
        print(f"  rite        {meta['rite'] or 'Roman (default)'}")
        print(f"  lectionary  {meta['lectionary_number'] or '-'}")
        print(f"  day         {meta['title'] or '-'}")
        print(f"  location    {meta['location'] or '-'}")
        print(f"  preached    {meta['preached'] or '-'}")
        print(f"  occasion    {meta['occasion'] or '-'}")
        print(f"  header read {draft['header_lines'] or '(none — all body)'}")
        words = len(draft["body"].split())
        print(f"  body        {words:,} words, {draft['body'].count(chr(10) * 2) + 1} paragraphs")

        if not date:
            unresolved.append(path)
            print("  → not written: date unresolved")
            continue

        # Two homilies can share a date -- "with baptisms" and "without", a
        # Manuscript and its Preaching Text, two school Masses. check.py already
        # understands YYYY-MM-DD_suffix.md, so use it rather than dropping one.
        #
        # A draft already imported from THIS document is not a collision; without
        # that check a second run duplicates every draft under a new suffix.
        def imported_from_here(path):
            if not os.path.exists(path):
                return False
            try:
                existing, _ = homilist.split_frontmatter(open(path, encoding="utf-8").read())
            except homilist.FrontmatterError:
                return False
            return str(existing.get("source", "")) == meta["source"]

        target = os.path.join(drafts, f"{date.isoformat()}.md")
        if os.path.exists(target) and not imported_from_here(target):
            # Name a sibling by whatever actually distinguishes it: its occasion
            # and variant, failing those its venue, failing that the liturgical
            # day. An anonymous "_b" says nothing about which homily it is.
            # Tried in order, because the best answer can distinguish nothing --
            # a venue that hosted both Masses names neither of them.
            candidates = [os.path.join(drafts, f"{date.isoformat()}_{slug}.md")
                          for slug in homilist.distinguishers(meta)]
            candidates += [os.path.join(drafts, f"{date.isoformat()}_{c}.md")
                           for c in "bcdefgh"]
            for candidate in candidates:
                if not os.path.exists(candidate) or imported_from_here(candidate):
                    target = candidate
                    break

        if os.path.exists(target) and not imported_from_here(target) and not args.force:
            print(f"  → not written: {os.path.basename(target)} exists (--force to replace)")
            continue

        if args.dry_run:
            print(f"  → would write {target}")
            continue

        os.makedirs(drafts, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(homilist.format_frontmatter(meta))
            f.write(draft["body"].rstrip() + "\n")
        print(f"  → wrote {target}")

        # The sibling suffix is built from the occasion, variant, or venue, so
        # correcting any of those changes the filename -- and the old draft would
        # be left behind, a second copy of the same homily claiming the same
        # source. Provenance is what makes re-importing safe, so it has to be
        # checked across the directory rather than at one computed path.
        for stale in stale_drafts(drafts, meta["source"], keep=target):
            os.remove(stale)
            print(f"  → removed {os.path.basename(stale)} (renamed, same source)")

    if unresolved:
        print(f"\n{len(unresolved)} unresolved:")
        for path in unresolved:
            print(f"  {os.path.basename(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

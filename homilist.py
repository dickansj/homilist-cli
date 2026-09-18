"""Shared helpers: where the homilies live, and how their frontmatter is shaped.

Kept deliberately small so each script stays a standalone executable.
"""

import datetime
import os
import sys
import tomllib

import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Overridable so the test suite (and tools/sync_litcal_api.py's opportunistic
# check) can force USCCB closed deterministically; it answers intermittently,
# so a test that depends on it failing would be as flaky as one that depends
# on it working. Shared by new.py and tools/sync_litcal_api.py, the only two
# places that fetch a USCCB page.
USCCB_WEB_TEMPLATE = os.environ.get(
    "USCCB_URL_TEMPLATE", "https://bible.usccb.org/bible/readings/%m%d%y.cfm")

# Frontmatter field order, as written into new files.
#
# `rite` is empty for the Roman rite, which is the common case. Maronite and
# Chaldean homilies have no Roman lectionary number and are named differently when
# rendered -- see pdf_name() in render.py.
#
# Scraped from USCCB by new.py -- canonical, complete, left alone:
#   date, lectionary_number, lectionary_string, readings
# Filled in by hand -- what actually prints on the page:
#   title, occasion, location, preached, variant
#
# `source` records the .docx a draft was imported from, and is empty for anything
# written by new.py. It is provenance, and it is what makes re-importing safe: the
# importer recognises its own output instead of writing a duplicate.
FIELDS = [
    "date",
    "rite",
    "lectionary_number",
    "lectionary_string",
    "title",
    "occasion",
    "location",
    "readings",
    "preached",
    "variant",
    "source",
]


def config():
    """config.toml as a dict, or an empty one when there is none.

    Read every time rather than cached: it is a few lines, and the tests
    rewrite it between checks.
    """
    path = os.path.join(SCRIPT_DIR, "config.toml")
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def homilies_dir():
    """Resolve the homily directory.

    $HOMILIES_DIR wins, then homilies_dir in config.toml, then the parent
    directory (which is how @sjml's original layout worked).
    """
    raw = os.environ.get("HOMILIES_DIR")
    source = "$HOMILIES_DIR"

    if not raw:
        raw = config().get("homilies_dir")
        source = os.path.join(SCRIPT_DIR, "config.toml")

    if not raw:
        raw = os.path.join(SCRIPT_DIR, "..")
        source = "default (parent directory)"

    path = os.path.abspath(os.path.expanduser(raw))
    if not os.path.isdir(path):
        sys.stderr.write(
            f"Homily directory does not exist: {path}\n  (from {source})\n"
        )
        sys.exit(1)
    return path


def tmp_dir():
    """Scratch space, kept in the repo rather than in the homily directory,
    so it never lands in the parish archive or gets indexed with it."""
    path = os.path.join(SCRIPT_DIR, "tmp")
    os.makedirs(path, exist_ok=True)
    return path


def archive_dir():
    """The folder the drafts directory sits in -- the archive root."""
    return os.path.dirname(homilies_dir().rstrip("/")) or "."


def word_dir():
    """Where the .docx originals live.

    They used to sit beside the Drafts folder and now live in Word/ under it.
    Resolved rather than assumed, so both layouts work and a move does not
    silently break every `source` in the archive.
    """
    candidate = os.path.join(archive_dir(), "Word")
    return candidate if os.path.isdir(candidate) else archive_dir()


def summaries_dir():
    """Where the per-homily summaries live, beside Word/ under the archive root.

    The summaries are written by a scheduled task rather than by anything here,
    so this is a read-only address: tools that want to know what a homily was
    about look here, and find nothing rather than failing when a homily has not
    been summarised yet.
    """
    return os.path.join(archive_dir(), "Homily Summaries")


def summary_name(draft_name):
    """The summary filename belonging to a draft: its own name, plus Summary.

    Imported homilies were once summarised under the name of the .docx they came
    from, so the archive held two conventions at once and every tool had to know
    both. The summaries were renamed to this one. analyze.py in the archive root
    maps drafts the same way -- the two have to agree, or a summary that exists
    reads as missing and gets rewritten.
    """
    return f"{os.path.splitext(draft_name)[0]} Summary.md"


def rename_summary(old_draft, new_draft):
    """Move a draft's summary when the draft is renamed. Returns what happened.

    The summaries task only ever writes: rename a draft and it writes a fresh
    summary under the new name, leaving the old one behind for good. So whatever
    renames a draft renames the summary in the same step, heading included --
    line 1 names the file, and a heading that disagrees with its filename gets
    trusted once and is wrong.

    "renamed", "missing" when there was no summary to move, or "conflict" when
    one already exists under the new name, in which case neither is touched:
    choosing between two summaries is not something to do silently.
    """
    directory = summaries_dir()
    old_name, new_name = summary_name(old_draft), summary_name(new_draft)
    old, new = os.path.join(directory, old_name), os.path.join(directory, new_name)
    if not os.path.isfile(old):
        return "missing"
    if os.path.exists(new):
        return "conflict"
    os.rename(old, new)

    # Only an exact first line is rewritten. A pattern here once matched the
    # blank line after the heading too, and removed it from every summary.
    with open(new, encoding="utf-8") as f:
        lines = f.read().split("\n")
    if lines and lines[0] == f"# {os.path.splitext(old_name)[0]}":
        lines[0] = f"# {os.path.splitext(new_name)[0]}"
        with open(new, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    return "renamed"


def copy_roots():
    """Folders that may hold a per-occasion copy of a rendered homily.

    A funeral, a wedding, a school Mass keeps its own folder with the script,
    the reading sheet and the intercessions in it. The homily belongs there too,
    and `render.py --to` finds the folder by a fragment of its name so the whole
    path never has to be typed. Configured, because the folder names are the
    parish's, not this repo's.
    """
    raw = config().get("copy_roots", [])
    # A relative entry is resolved against the archive root and then against its
    # parent, because these folders are usually the archive's *siblings*:
    # Funerals/ sits beside Homilies/, not inside it.
    bases = [archive_dir(), os.path.dirname(archive_dir().rstrip("/"))]
    out = []
    for entry in raw:
        expanded = os.path.expanduser(str(entry))
        if os.path.isabs(expanded):
            if os.path.isdir(expanded):
                out.append(expanded)
            continue
        for base in bases:
            candidate = os.path.join(base, expanded)
            if os.path.isdir(candidate):
                out.append(candidate)
                break
    return out


def pdf_dir():
    """Where rendered PDFs go. The Drafts folder is for markdown."""
    return archive_dir()


# Prefixes that mean "the filesystem or an application put this here", not
# "someone wrote this".
#
#   ~$   Word, Excel and PowerPoint owner files, written beside any open
#        document to hold the name of whoever has it locked. The naming is
#        unusual: the prefix REPLACES the first two characters rather than
#        being added, so the length is unchanged and the result still reads
#        like a title -- "~$mily Healing of the Blind Man.docx". They carry a
#        .docx extension and match any glob, but they are not documents and
#        not even valid ZIP containers.
#   ._   AppleDouble resource forks, written when a Mac copies a file onto a
#        volume that cannot hold its metadata. A cloud-synced archive
#        collects them.
#   .    Dotfiles generally, .DS_Store included.
_SIDECAR_PREFIXES = ("~$", "._", ".")


def is_sidecar(path):
    """Whether a filename is an application or filesystem artifact.

    Takes a path or a bare name. Nothing that enumerates documents should ever
    hand one of these downstream: an owner file has no date, no title and no
    readable text, so it cannot be imported and cannot be *resolved* either --
    it just accumulates in the unresolved report forever.
    """
    return os.path.basename(str(path)).startswith(_SIDECAR_PREFIXES)


def documents(paths):
    """Real documents from a list of paths -- a shell glob's output, usually.

    `Word/*.docx` is expanded by the shell, so this is where that enumeration
    arrives and where it has to be filtered.
    """
    return [p for p in paths if not is_sidecar(p)]


def homily_files(directory):
    """The .md files we consider ours, sorted. Skips sidecars, underscore
    worksheets, and anything that isn't a plain file."""
    out = []
    for name in sorted(os.listdir(directory)):
        if is_sidecar(name) or name.startswith("_"):
            continue
        if not name.endswith(".md"):
            continue
        full = os.path.join(directory, name)
        if os.path.isfile(full):
            out.append((name, full))
    return out


def find_draft(argument):
    """A draft from whatever the user typed, or None.

    Rendering and counting happen from the drafts folder, so a bare name should
    be enough: the full path, a name relative to where you are, or just the
    draft's name with or without its extension.
    """
    candidates = [
        argument,
        os.path.join(homilies_dir(), argument),
        os.path.join(homilies_dir(), argument + ".md"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


class FrontmatterError(Exception):
    """The frontmatter isn't valid YAML. Worth its own type because pandoc
    will reject the same file, and we want to say so before it does."""


def split_frontmatter(contents):
    """(metadata dict, body).

    Parsed as real YAML, deliberately: pandoc reads this same block as YAML
    to fill the template, so anything we accept that pandoc rejects is a
    lint tool that lies. Raises FrontmatterError on invalid YAML.
    """
    metadata = {}
    body = contents

    if contents.startswith("---\n"):
        end = contents.find("\n---", 3)
        if end != -1:
            raw = contents[4:end]
            body = contents[end + 4 :].lstrip("\n")
            try:
                loaded = yaml.safe_load(raw)
            except yaml.YAMLError as exc:
                raise FrontmatterError(str(exc)) from exc
            if loaded is None:
                loaded = {}
            if not isinstance(loaded, dict):
                raise FrontmatterError("frontmatter is not a set of key/value pairs")
            # Normalize: YAML turns a bare date into datetime.date and an empty
            # value into None. Downstream code wants strings and ints only.
            for key, value in loaded.items():
                if value is None:
                    value = ""
                elif isinstance(value, (datetime.date, datetime.datetime)):
                    value = value.strftime("%Y-%m-%d")
                elif not isinstance(value, (str, int)):
                    value = str(value)
                metadata[str(key)] = value

    return metadata, body


def format_frontmatter(metadata):
    """Serialize via PyYAML so values needing quotes get them, in FIELDS order."""
    ordered = {key: metadata.get(key, "") for key in FIELDS}
    dumped = yaml.safe_dump(
        ordered,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10000,
    )
    return f"---\n{dumped}---\n\n"

# ---------------------------------------------------------------- USCCB scraping

# Readings we don't preach on and don't want in the citation line.
SKIP_READINGS = {"alleluia", "verse before the gospel"}


class ScrapingException(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def scrape_readings(html):
    """Pull lectionary number, day title and reading citations out of a USCCB page.

    Separated from new.py so it can be tested against a saved fixture without a
    network call. This is the most fragile code here -- seven CSS selectors into
    someone else's site -- and its failure mode is a homily file with blank
    metadata, noticed at the wrong moment.

    Returns (lectionary_number, lectionary_string, readings_string).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, features="html.parser")

    title_block = soup.select_one("div.b-lectionary div.innerblock")
    if not title_block:
        raise ScrapingException("no title block")
    header = title_block.select_one("h2")
    if not header:
        raise ScrapingException("no header in title block")
    # A compound title -- "The Commemoration of All the Faithful Departed
    # (All Souls)" -- puts the parenthetical on its own line in the source
    # HTML, so `.text` alone carries that newline and the indentation around
    # it into the title. `.split()`/`" ".join()` collapses any run of
    # whitespace, embedded or not, to a single space.
    lectionary_string = " ".join(header.text.split())

    lect_par = title_block.select_one("p")
    if not lect_par:
        raise ScrapingException("no lectionary paragraph in title block")
    lect_num = " ".join(lect_par.text.split()).split(":")[-1].strip()
    if lect_num.isdigit():
        lect_num = int(lect_num)

    readings = []
    for block in soup.select(".wr-block.b-verse"):
        c_header = block.select_one(".content-header")
        if not c_header:
            raise ScrapingException("no header in one of the verse blocks")
        reading_header = c_header.select_one("h3.name")
        if not reading_header:
            raise ScrapingException("no reading label header in one of the verse blocks")
        label = " ".join(reading_header.text.split())
        if label.lower() in SKIP_READINGS:
            continue
        address = c_header.select_one(".address a")
        if not address:
            raise ScrapingException(f"no address found for {label}")
        citation = " ".join(address.text.split())

        if label.lower() == "or":
            if not readings:
                raise ScrapingException("alternate reading with nothing to attach to")
            readings[-1] += f" or {citation}"
        else:
            readings.append(citation)

    # Zero readings means the page parsed but nothing matched -- the exact shape a
    # USCCB redesign takes. Returning "" here would write a homily file with blank
    # readings and no complaint, so this has to be loud.
    if not readings:
        raise ScrapingException(
            "no readings found: the page structure has probably changed"
        )

    return lect_num, lectionary_string, "; ".join(readings)

# ---------------------------------------------------------------- citations

import re as _re  # noqa: E402

try:
    from books import BOOKS as _BOOKS
except ImportError:  # generated file absent; leave citations untouched
    _BOOKS = {}


def normalize_citations(text):
    """Rewrite scripture references to SBL abbreviations.

    House style, matching liturgy-script: SBL abbreviation, no space after the
    chapter colon, en-dash for verse ranges. Only the book name is rewritten --
    everything else in the string is left exactly as written, because these lines
    also carry parenthetical notes and alternate readings.
    """
    if not text or not _BOOKS:
        return text

    def punctuation(tail):
        tail = _re.sub(r"(\d)\s*:\s*(\d)", r"\1:\2", tail)
        return _re.sub(r"(\d)\s*[-\u2013]\s*(\d)", "\\1\u2013\\2", tail)

    def one(ref):
        ref = ref.strip()
        for i in range(len(ref), 0, -1):
            key = ref[:i].lower().rstrip(". ")
            if key in _BOOKS:
                return f"{_BOOKS[key]} {punctuation(ref[i:].strip())}".strip()
        # A continuation like "3:1-7" carries no book name but still gets the
        # house punctuation.
        return punctuation(ref)

    return "; ".join(one(part) for part in text.split(";"))

# ---------------------------------------------------------------- day names

_WEEKDAY_ABBR = {
    "sunday": "Sun", "sun": "Sun", "monday": "Mon", "mon": "Mon",
    "tuesday": "Tue", "tues": "Tue", "tue": "Tue",
    "wednesday": "Wed", "wed": "Wed",
    "thursday": "Thu", "thurs": "Thu", "thu": "Thu",
    "friday": "Fri", "fri": "Fri", "saturday": "Sat", "sat": "Sat",
}
_SEASONS = {
    "ot": "OT", "ordinary time": "OT", "ordinary": "OT",
    "easter": "Easter", "lent": "Lent", "advent": "Advent",
    "christmas": "Christmas", "pentecost": "Pentecost",
}
# Seasons of the Maronite and Chaldean years. Kept separate because several of
# these words also appear in Roman day names -- "Epiphany of the Lord", "the
# Resurrection of the Lord" -- where they name a feast, not a season to count
# within. They are only consulted when the draft records a rite.
_EASTERN_SEASONS = {
    "resurrection": "Resurrection", "epiphany": "Epiphany", "elijah": "Elijah",
    "disciples": "Disciples", "apostles": "Apostles", "church": "Church",
    "moses": "Moses", "cross": "Cross", "summer": "Summer",
}
# Feasts the Maronite year counts *from* rather than within.
_FEASTS = {"holy cross": "Holy Cross", "cross": "Holy Cross",
           "epiphany": "Epiphany", "pentecost": "Pentecost",
           "easter": "Easter", "resurrection": "Resurrection"}
_AFTER_RE = _re.compile(
    r"^(\d{1,2})(?:st|nd|rd|th)?\s+(sunday|sun)\b\.?\s+after\s+(.+)$", _re.I)
# "Sunday of the Faithful Departed" -- a Sunday named for what it commemorates
# rather than counted. Anchored at the start so numbered days ("5th Sunday of
# Lent") never reach it.
_NAMED_DAY_RE = _re.compile(
    r"^(sunday|sun|monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thu|"
    r"friday|fri|saturday|sat)\b\.?\s+of\s+(?:the\s+)?(.+)$", _re.I)
_WEEKDAY_RE = _re.compile(
    r"\b(sunday|sun|monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thu|"
    r"friday|fri|saturday|sat)\b\.?", _re.I)
_ORDINAL_RE = _re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", _re.I)
_SEASON_RE = _re.compile(
    r"\b(ordinary\s+time|ordinary|ot|easter|lent|advent|christmas|pentecost)\b",
    _re.I)
_EASTERN_SEASON_RE = _re.compile(
    r"\b(ordinary\s+time|ordinary|ot|easter|lent|advent|christmas|pentecost|"
    r"resurrection|epiphany|elijah|disciples|apostles|church|moses|cross|summer)\b",
    _re.I)


def slugify(text):
    """A filename-safe form of a phrase: "With Baptisms" -> "with-baptisms"."""
    return _re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-").lower()


def distinguishers(metadata):
    """What could tell this draft from another on the same date, best first.

    Two homilies on one day are written YYYY-MM-DD_suffix.md, and the suffix has
    to say which one it is -- an anonymous `_b` makes the reader open both. The
    occasion and variant say it best ("Novena of Grace Day 7 Manuscript"); the
    venue says it when a day simply carried two Masses; and the liturgical day
    says it when neither does, which happens when one venue hosts a feast and a
    ferial Mass on the same date.

    Returned as a list rather than a single answer because the best one may
    already be taken: on 2025-08-17 both homilies were preached at the same
    church, so the venue distinguishes nothing and the caller falls through to
    the day.
    """
    occasion = str(metadata.get("occasion", "")).strip()
    variant = str(metadata.get("variant", "")).strip()
    candidates = [
        " ".join(x for x in (occasion, variant) if x),
        str(metadata.get("location", "")).strip(),
        str(metadata.get("title", "")).strip(),
    ]
    seen = []
    for candidate in candidates:
        slug = slugify(candidate)
        if slug and slug not in seen:
            seen.append(slug)
    return seen


def distinguishing_slug(metadata, others, taken=()):
    """The first of this draft's distinguishers that no other draft that day has.

    A venue both homilies were preached at names neither of them, and a variant
    the two share says nothing about which is which -- so what counts is not the
    best field in the abstract but the best one the others lack. None when
    nothing this draft holds is its own.
    """
    shared = {slug for other in others for slug in distinguishers(other)}
    for slug in distinguishers(metadata):
        if slug not in shared and slug not in taken:
            return slug
    return None


def sibling_name(date, metadata, taken=()):
    """The filename a second homily on `date` should take.

    `taken` is the names already in use, so the suffix that distinguishes
    nothing is skipped rather than collided with.
    """
    taken = set(taken)
    for slug in distinguishers(metadata) + list("bcdefgh"):
        candidate = f"{date}_{slug}.md"
        if candidate not in taken:
            return candidate
    return f"{date}.md"


def is_eastern(rite):
    """The Roman rite is written two ways -- an empty field, or the word itself.

    Truthiness is therefore the wrong test: `rite: Roman` is not Eastern. Every
    caller that slices the archive by rite goes through here so they cannot
    disagree about it.
    """
    return str(rite or "").strip().lower() not in ("", "roman")


_CYCLE_TAIL = _re.compile(r"\s*[-–—(]?\s*(?:Year\s+)?[ABC]\s*\)?\s*$")


def _named_day(text):
    """"Tuesday of Easter Octave" -> "Tue of Easter Octave".

    A day named for what it observes rather than counted. Tried only after the
    numbered-season rule declines, or it would swallow "Wednesday of 8th OT" and
    return "Wed of 8th OT" -- the abbreviation applied, the counting lost.
    """
    named = _NAMED_DAY_RE.match(text.strip())
    if not named:
        return text
    return (f"{_WEEKDAY_ABBR[named.group(1).lower()]} of "
            f"{named.group(2).strip(' .,-–—')}")


def _ordinal_suffix(number):
    return ("th" if 11 <= number % 100 <= 13
            else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th"))


def standardize_day(text, rite=None):
    """One liturgical day, written one way.

    Three shapes, the first two genuinely different and not variants of each other:

        Wed 12th of OT                a numbered day *within* a season
        3rd Sunday after Holy Cross   a Sunday counted *from* a fixed feast
        Sun of Faithful Departed      a day named for what it observes

    Roman and Chaldean days count within a season; much of the Maronite year
    counts from a feast. `rite` widens the season vocabulary to the Eastern
    seasons -- Resurrection, Elijah, Church, Moses, Disciples -- which is opt-in
    because several of those words name a *feast* in Roman day titles. `Roman`
    counts as no rite; see is_eastern().

    The archive writes the first shape six ways -- "Wednesday of 8th OT", "Tues 15th OT",
    "Tuesday 13th in OT", "4th Sun of Easter", "Wed of 1st Lent", "1st Sunday of
    Lent". Anything that is not a numbered day in a season is returned untouched:
    "Ash Wednesday" and "Ss. Simon and Jude" are not patterns to be rewritten.
    """
    if not text:
        return text

    # "Sun 13th of OT Year A" -- the cycle is a property of the year, not of the
    # day, and `lectionary_number` already encodes it.
    text = _CYCLE_TAIL.sub("", text).strip(" ,-–—")

    # "3rd Sunday after Holy Cross" counts *from* a feast rather than within a
    # season. It is a different structure, not a spelling variant of one, so it
    # is matched first -- "after" is the whole of the signal, and without that
    # test "1st Sun after Epiphany" reads as the 1st Sunday *of* Epiphany.
    after = _AFTER_RE.match(text.strip())
    if after:
        number = int(after.group(1))
        feast = after.group(3).strip(" .,-–—")
        return (f"{number}{_ordinal_suffix(number)} Sun after "
                f"{_FEASTS.get(feast.lower(), feast)}")

    weekday = _WEEKDAY_RE.search(text)
    season = (_EASTERN_SEASON_RE if is_eastern(rite)
              else _SEASON_RE).search(text)
    if not weekday or not season:
        return _named_day(text)

    # The ordinal must not be part of the weekday or season match.
    ordinal = None
    for candidate in _ORDINAL_RE.finditer(text):
        if not (weekday.start() <= candidate.start() < weekday.end()
                or season.start() <= candidate.start() < season.end()):
            ordinal = candidate
            break
    if not ordinal:
        return _named_day(text)

    spans = sorted([weekday.span(), ordinal.span(), season.span()])
    head = text[: spans[0][0]]
    inner = text[spans[0][1]: spans[1][0]] + " " + text[spans[1][1]: spans[2][0]]
    tail = text[spans[2][1]:]

    # Only the words *between* the three parts are grammar to discard. The tail
    # carries real content -- "/St. Anselm", "(Our Lady of the Rosary)" -- and
    # stripping connectives from it mangles the parenthetical.
    inner = _re.sub(r"\b(of|in|the)\b", " ", inner, flags=_re.I)
    remainder = " ".join(x for x in (head.strip(), inner.strip(), tail.strip()) if x)
    remainder = _re.sub(r"[ \t]{2,}", " ", remainder).strip(" ,-–—/")

    number = int(ordinal.group(1))
    key = season.group(1).lower()
    name = _SEASONS.get(key) or _EASTERN_SEASONS[key]
    day = (f"{_WEEKDAY_ABBR[weekday.group(1).lower()]} "
           f"{number}{_ordinal_suffix(number)} of {name}")
    if not remainder:
        return day
    # A slash or dash in the original joined the day to a concurrent memorial or
    # its proper name -- keep that relationship rather than turning it into a
    # loose trailing phrase. An em dash is the archive's convention for it.
    if _re.search(r"[/–—]", text) and not remainder.startswith("("):
        return f"{day} — {remainder}"
    return f"{day} {remainder}"

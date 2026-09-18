#!/bin/sh
''''exec "$(dirname "$0")/env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env! :D

import os
import re
import shlex
import shutil
import sys
import calendar
from datetime import date, timedelta
import subprocess

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl

import requests

import homilist
import lectionary
import litcal_api
import liturgical

# Overridable so the test suite can force the local fallback deterministically;
# USCCB answers intermittently, so a test that depends on it failing would be
# as flaky as one that depends on it working.
USCCB_WEB_TEMPLATE = os.environ.get(
    "USCCB_URL_TEMPLATE", "https://bible.usccb.org/bible/readings/%m%d%y.cfm")


HOMILIES = homilist.homilies_dir()
TMP = homilist.tmp_dir()

os.chdir(HOMILIES)

calendar.setfirstweekday(calendar.SUNDAY)

class DatePicker:
    def __init__(self):
        self.selected = date.today()
        self.control = FormattedTextControl(self.render)
        self.app: Application|None = None

    def render(self):
        d = self.selected
        cal = calendar.monthcalendar(d.year, d.month)
        month = calendar.month_name[d.month]

        out = []

        out.append(("bold", f"\n{month} {d.year}\n"))
        out.append(("bold", "Su Mo Tu We Th Fr Sa\n"))

        for week in cal:
            for day in week:
                if day == 0:
                    out.append(("", "   "))
                elif day == d.day:
                    out.append(("reverse", f"{day:2d} "))
                else:
                    out.append(("", f"{day:2d} "))
            out.append(("", "\n"))

        return out

_preset_date = None
for _i, _a in enumerate(sys.argv[1:]):
    if _a == "--date" and _i + 2 < len(sys.argv):
        try:
            _preset_date = date.fromisoformat(sys.argv[_i + 2])
        except ValueError:
            sys.stderr.write(f"--date wants YYYY-MM-DD, got {sys.argv[_i + 2]!r}\n")
            sys.exit(2)
    elif _a.startswith("--date="):
        try:
            _preset_date = date.fromisoformat(_a.split("=", 1)[1])
        except ValueError:
            sys.stderr.write(f"--date wants YYYY-MM-DD, got {_a!r}\n")
            sys.exit(2)

_preset_occasion = None
for _i, _a in enumerate(sys.argv[1:]):
    if _a == "--occasion" and _i + 2 < len(sys.argv):
        _preset_occasion = sys.argv[_i + 2]
    elif _a.startswith("--occasion="):
        _preset_occasion = _a.split("=", 1)[1]

_preset_variant = None
_preset_location = None
for _i, _a in enumerate(sys.argv[1:]):
    if _a == "--variant" and _i + 2 < len(sys.argv):
        _preset_variant = sys.argv[_i + 2]
    elif _a.startswith("--variant="):
        _preset_variant = _a.split("=", 1)[1]
    elif _a == "--location" and _i + 2 < len(sys.argv):
        _preset_location = sys.argv[_i + 2]
    elif _a.startswith("--location="):
        _preset_location = _a.split("=", 1)[1]

# A second draft on a date starts as a copy of the first, because deleting a
# copied body takes a second and rebuilding a base you wanted does not. --blank
# is for the other case: a different homily that only shares the date's readings.
_blank = "--blank" in sys.argv[1:]

# Anything else on the command line is a mistake, and a silent one until now:
# the flags are matched by exact string, so `-variant "Morning"` (one dash)
# matched nothing, the value was read as a stray word, and a draft was scaffolded
# with an empty variant and no complaint. A flag that does nothing has to say so.
_FLAGS = ("--date", "--occasion", "--variant", "--location")
_SWITCHES = ("--blank",)
_unknown, _skip = [], False
for _i, _a in enumerate(sys.argv[1:]):
    if _skip:
        _skip = False
        continue
    if _a in _SWITCHES:
        continue
    if _a in _FLAGS:
        if _i + 2 >= len(sys.argv):
            sys.stderr.write(f"{_a} wants a value\n")
            sys.exit(2)
        _skip = True
        continue
    if any(_a.startswith(_f + "=") for _f in _FLAGS):
        continue
    _unknown.append(_a)
if _unknown:
    sys.stderr.write("unrecognized argument: " + ", ".join(_unknown) + "\n")
    # One dash instead of two is the way this goes wrong, and the result used to
    # look like success, so name the likely cause rather than only the rule.
    _near = [_u for _u in _unknown
             if not _u.startswith("--") and _u.lstrip("-") in
             [_f.lstrip("-") for _f in _FLAGS + _SWITCHES]]
    if _near:
        sys.stderr.write("flags take two dashes: "
                         + ", ".join(f"-{_n}" for _n in _near) + "\n")
    else:
        sys.stderr.write("usage: new.py [--date YYYY-MM-DD] [--occasion TEXT] "
                         "[--variant TEXT] [--location TEXT] [--blank]\n")
    sys.exit(2)

picker = DatePicker()
kb = KeyBindings()

@kb.add("left")
def _(event):
    picker.selected -= timedelta(days=1)

@kb.add("right")
def _(event):
    picker.selected += timedelta(days=1)

@kb.add("up")
def _(event):
    picker.selected -= timedelta(days=7)

@kb.add("down")
def _(event):
    picker.selected += timedelta(days=7)

@kb.add("t")
def _(event):
    picker.selected = date.today()

@kb.add("enter")
def _(event):
    event.app.exit(result=picker.selected)

@kb.add("c-c")
def _(event):
    event.app.exit(result=None)

app = Application(
    layout=Layout(Window(content=picker.control)),
    key_bindings=kb,
    full_screen=False,
)

picker.app = app

# --date skips the picker. It exists so the whole path can be exercised by the
# test suite -- an interactive picker cannot be, and the fallback below is the
# part most worth testing.
if _preset_date:
    target_date: date|None = _preset_date
else:
    target_date: date|None = app.run()

if not target_date:
    sys.stderr.write("No date selected!\n")
    sys.exit(1)


def variant_slug(text):
    return homilist.slugify(text)


def drafts_for(day):
    """Drafts already written for this date, most recently edited first."""
    names = [n for n, _ in homilist.homily_files(".")
             if n == f"{day}.md" or n.startswith(f"{day}_")]
    return sorted(names, key=lambda n: os.path.getmtime(f"./{n}"), reverse=True)


def editor_command(config, environ):
    """The editor to open a new draft in, as argv, or None.

    Named in config.toml first, because that is where the rest of this
    preacher's setup lives; then $VISUAL and $EDITOR, the convention every
    other tool honours; then the terminal's own editor when it says which one
    it is. Each candidate is checked for on the PATH before it is chosen -- the
    old code called `code` on faith, and failed after the draft was written.
    """
    candidates = [config.get("editor", ""),
                  environ.get("VISUAL", ""), environ.get("EDITOR", "")]
    if environ.get("TERM_PROGRAM", "") == "vscode":
        candidates.append("code")
    if environ.get("ZED_TERM", "") == "true":
        candidates.append("zed")
    for candidate in candidates:
        argv = shlex.split(candidate) if candidate else []
        if argv and shutil.which(argv[0]):
            return [shutil.which(argv[0])] + argv[1:]
    return None


def open_in_editor(path):
    """Open the draft where you write. Quietly does nothing when there is no
    editor to be found, or when nobody is at the keyboard to see it."""
    if not sys.stdin.isatty():
        return
    argv = editor_command(homilist.config(), os.environ)
    if argv is None:
        return
    print(f"📝 Opening in {os.path.basename(argv[0])}...")
    try:
        subprocess.call(argv + [path])
    except OSError as exc:
        print(f"   couldn't: {exc}")


def read_draft(name):
    return homilist.split_frontmatter(open(f"./{name}", encoding="utf-8").read())


def suffix_the_base(base_name, day, new_meta, taken):
    """Give the first draft of a date a suffix of its own, and return its name.

    Neither of two homilies on one date is the default one, so neither should
    hold the plain YYYY-MM-DD.md: leaving the first unsuffixed makes it read as
    the homily and the other as an afterthought. Its own frontmatter names it, by
    whatever it does not share with the new draft -- its venue when the new one
    is preached somewhere else, its variant when both are at the same church.
    """
    meta, body = read_draft(base_name)
    others = [new_meta] + [read_draft(n)[0] for n in drafts_for(day)
                           if n != base_name]
    slug = homilist.distinguishing_slug(meta, others, taken)

    # Nothing it holds tells it apart. The usual case is "With Baptisms" and
    # "Without" at one church, where the first was written before anyone knew
    # there would be a second. Ask, since the answer belongs in the file anyway:
    # the variant prints on the page.
    if slug is None and sys.stdin.isatty():
        try:
            answer = input(f"What tells the existing {base_name} apart from the "
                           "new one? (its variant: With Baptisms, Manuscript, ...) > ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            raise SystemExit(130)
        if answer:
            meta["variant"] = answer
            with open(f"./{base_name}", "w", encoding="utf-8") as f:
                f.write(homilist.format_frontmatter(meta))
                f.write(body.rstrip() + "\n")
            slug = homilist.distinguishing_slug(meta, others, taken)

    # Unattended, or no answer: the best it has, even if the new draft shares it.
    # A suffix that says little still beats one draft posing as the default.
    if slug is None:
        slug = next((s for s in homilist.distinguishers(meta) if s not in taken),
                    None)
    if slug is None:
        return None
    target = f"{day}_{slug}.md"
    os.rename(f"./{base_name}", f"./{target}")
    return target


# A second homily on a date that already has one. What tells the two apart is
# whichever field you name: --location when they are preached to different
# congregations (the venue already prints, so nothing else is needed), --variant
# when they share a church and the venue cannot tell them apart ("With
# Baptisms" and "Without"), --occasion when the Mass itself is a different one.
#
# Two homilies on one date are not the same homily -- a different congregation
# usually means different text -- so the copy below is a starting point and
# nothing more. It is the default because deleting a copied body takes a second
# and rebuilding a base you wanted does not; --blank skips it.
_given = {field: str(value).strip()
          for field, value in (("occasion", _preset_occasion),
                               ("variant", _preset_variant),
                               ("location", _preset_location))
          if value is not None and str(value).strip()}
_day = target_date.isoformat()
_existing = drafts_for(_day)

if _given and _existing:
    # The suffix is what you typed, so the filename is never a surprise.
    _out = f"{_day}_{homilist.slugify(' '.join(_given.values()))}.md"
    if os.path.exists(f"./{_out}"):
        sys.stderr.write(f"Output file ./{_out} already exists!\n")
        sys.exit(1)

    # The unsuffixed draft if there is one -- it is the one that needs a suffix
    # anyway -- otherwise whichever sibling was edited last.
    _base = f"{_day}.md" if f"{_day}.md" in _existing else _existing[0]
    _meta, _body = read_draft(_base)
    _meta.update(_given)

    # A funeral is never a copy of the day's Mass: it has its own readings, so
    # nothing from the lectionary carries over and there is no text to start from.
    _funeral = bool(re.search(r"\bfunerals?\b", _meta.get("occasion", ""), re.I))
    if _funeral:
        for _field in ("lectionary_number", "lectionary_string", "readings",
                       "preached"):
            _meta[_field] = ""
    _start_blank = _blank or _funeral

    with open(f"./{_out}", "w", encoding="utf-8") as _f:
        _f.write(homilist.format_frontmatter(_meta))
        if not _start_blank:
            _f.write(_body.rstrip() + "\n")

    _said = " · ".join(f"{k}: {v}" for k, v in _given.items())
    print(f"✅ Second draft for {_day} at {os.path.join(HOMILIES, _out)}")
    if _start_blank:
        print(f"   frontmatter from {_base}, text left blank · {_said}")
    else:
        print(f"   copied from {_base} · {_said}")

    if _base == f"{_day}.md":
        _taken = {n[len(_day) + 1:-3] for n in _existing if n.startswith(f"{_day}_")}
        _taken.add(_out[len(_day) + 1:-3])
        _renamed = suffix_the_base(_base, _day, _meta, _taken)
        if _renamed:
            print(f"   renamed {_base} → {_renamed}, so neither reads as the default")
            # Its summary moves with it, or the summaries task writes a second
            # one under the new name and the old is orphaned.
            _moved = homilist.rename_summary(_base, _renamed)
            if _moved == "renamed":
                print(f"   and its summary → {homilist.summary_name(_renamed)}")
            elif _moved == "conflict":
                print(f"   ⚠️  {homilist.summary_name(_renamed)} already exists, so "
                      f"{homilist.summary_name(_base)} was left where it is")
        else:
            print(f"   {_base} keeps its name: nothing in it says which homily it is")

    if _funeral:
        print("   ↳ fill in `readings` and set `preached:` — a funeral uses its own")
    elif not _start_blank:
        print("   ↳ a starting point: rewrite as much as the congregation needs")
    open_in_editor(_out)
    sys.exit(0)

# Any draft for that date is a clash, not just one with the same name: writing
# a plain YYYY-MM-DD.md beside an existing YYYY-MM-DD_maple-court.md puts back the
# very shape the suffixes exist to avoid. Checked before anything is asked, so a
# refusal does not come after you have answered the prompts.
if _existing and not _given:
    sys.stderr.write(f"{_day} already has a draft: " + ", ".join(_existing) + "\n")
    sys.stderr.write(
        "For a second homily that day, say what tells it apart:\n"
        "  --location \"Arrupe House\"   preached somewhere else\n"
        "  --variant \"Without Baptisms\"   same church, different Mass\n"
        "  --occasion \"Healing Mass\"      a different kind of Mass\n"
        "It starts as a copy of that draft (--blank for an empty one), and both\n"
        "drafts get a suffix.\n")
    sys.exit(1)


if _preset_date and not sys.stdin.isatty():
    location, occasion = _preset_location or "", _preset_occasion or ""
else:
    try:
        location = (_preset_location if _preset_location is not None
                    else input("Location? (leave blank to copy most recent) > "))
        occasion = _preset_occasion if _preset_occasion is not None else input(
            "Occasion? (Healing Mass, Novena Day 1, Smith Funeral, ... or blank) > ")
    except (KeyboardInterrupt, EOFError):
        print()
        raise SystemExit(130)

metadata = {
    "date": target_date.strftime("%Y-%m-%d"),
    "lectionary_number": "",
    "lectionary_string": "",
    "title": "",
    "occasion": occasion.strip(),
    "location": "",
    "readings": "",
    "preached": "",
    "variant": "",
}

if _preset_variant:
    metadata["variant"] = _preset_variant
    output_file_path = f"./{metadata['date']}_{variant_slug(_preset_variant)}.md"
else:
    output_file_path = f"./{metadata['date']}.md"
if os.path.exists(output_file_path):
    sys.stderr.write(f"Output file {output_file_path} already exists!\n")
    sys.exit(1)

if location == "":
    files = homilist.homily_files(".")
    if files:
        content = open(files[-1][1], encoding="utf-8").read()
        try:
            previous, _ = homilist.split_frontmatter(content)
            metadata["location"] = previous.get("location", "")
        except homilist.FrontmatterError:
            sys.stderr.write(
                f"Couldn't read frontmatter of {files[-1][0]} to copy the "
                "location (run check.py); leaving it blank.\n"
            )
else:
    metadata["location"] = location.strip()


err = False

# The liturgical day comes from the local calendar either way: it is the short
# form this archive writes, and no lookup is needed to know it.
metadata["title"] = liturgical.describe(target_date)

# A funeral is not the day's Mass. Its readings are chosen for the funeral --
# usually with the family -- so there is no lectionary number to look up and
# nothing the calendar could tell us about what will be proclaimed. The day
# itself still stands, so `title` keeps it.
FUNERAL = re.search(r"\bfunerals?\b", metadata["occasion"], re.I)

# USCCB is tried once. It is the more current source and it owns
# `lectionary_string`, the calendar's own full name for the date -- nothing
# else supplies that; LiturgicalCalendarAPI and the offline route both leave it
# empty rather than substitute their own wording. But USCCB sits behind a bot
# challenge that a script usually fails, so a failure falls through: first to
# LiturgicalCalendarAPI (live, but independent of USCCB's uptime), then to the
# offline calendar and lectionary table, then to whatever
# tools/sync_litcal_api.py has already cached for a date the offline route
# cannot answer on its own. One attempt at each, not a retry loop: the failure
# is a policy, not a hiccup.
if FUNERAL:
    print(f"Funeral ({metadata['occasion']}) — no lectionary number; "
          "the readings are chosen for the Mass.")
    if sys.stdin.isatty():
        try:
            chosen = input("Readings? (blank to fill in later) > ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            raise SystemExit(130)
    else:
        chosen = ""
    metadata["readings"] = homilist.normalize_citations(chosen) if chosen else ""
    # lectionary_number and lectionary_string stay empty, as initialised.

else:
    print("Looking up readings from USCCB website...")

    url_req = target_date.strftime(USCCB_WEB_TEMPLATE)
    dl_path = os.path.join(TMP, os.path.basename(url_req))
    try:
        if not os.path.exists(dl_path):
            res = requests.get(url_req, timeout=20)
            if not res.ok:
                raise homilist.ScrapingException(
                    f"couldn't fetch USCCB page @ {url_req} ({res})")
            with open(dl_path, "wb") as outfile:
                outfile.write(res.content)
        page = open(dl_path, "r", encoding="utf-8").read()
        (metadata["lectionary_number"],
         metadata["lectionary_string"],
         metadata["readings"]) = homilist.scrape_readings(page)
        # USCCB writes "Jeremiah 31:1-7"; this archive is SBL throughout, and the
        # importer has always normalized. A homily scaffolded here should not be
        # the one file that is spelled differently.
        metadata["readings"] = homilist.normalize_citations(metadata["readings"])
        print(f"   USCCB: {metadata['lectionary_number']}: {metadata['lectionary_string']}")

    except (homilist.ScrapingException, requests.RequestException) as exc:
        # A requests exception stringifies to a paragraph of connection-pool detail.
        # One line is enough to say which way the draft was built.
        message = getattr(exc, "message", exc.__class__.__name__)
        print(f"   USCCB didn't answer ({message.splitlines()[0][:90]})")
        print("   Falling back to LiturgicalCalendarAPI...")

        # `readings` only: like the offline route below, this is not USCCB's
        # wording, so `lectionary_string` stays empty rather than borrow a
        # different source's phrasing for the same field.
        try:
            found = litcal_api.lookup(target_date)
        except litcal_api.LitCalAPIError as api_exc:
            print(f"   LiturgicalCalendarAPI didn't answer "
                  f"({api_exc.message.splitlines()[0][:90]})")
            found = None

        if found:
            metadata["readings"] = found["readings"]
            print(f"   LiturgicalCalendarAPI: {found['name']}")
        else:
            print("   Falling back to the offline calendar and lectionary table...")

        if not found:
            number = liturgical.lectionary_number(target_date)
            cycle = liturgical.ferial_year(target_date)

            if number:
                metadata["lectionary_number"] = number
                # `preached` is deliberately left empty, as on the USCCB route. It is
                # the line you prune by hand, and filling it here made the scaffolder
                # behave two different ways depending on whether a website answered.
                metadata["readings"] = lectionary.readings_line(number, cycle)

            if metadata["readings"]:
                print(f"   local: {metadata['lectionary_number']}: {metadata['title']}")
            else:
                # Whatever tools/sync_litcal_api.py has already cached for this
                # date, if the offline calendar and table cannot answer on their
                # own -- no network call here, so this still works with none.
                filled = litcal_api.gap_fill_lookup(target_date)
                if filled:
                    metadata["readings"] = filled["readings"]
                    print(f"   gap-fill cache: {filled['name']}")
                    print("   (from LiturgicalCalendarAPI, synced by "
                          "tools/sync_litcal_api.py — not live)")

            if not metadata["readings"]:
                err = True
                if not number:
                    sys.stderr.write(
                        f"   The calendar has no lectionary number for {target_date} "
                        "(most of the sanctoral cycle is not in it).\n")
                elif not lectionary.available():
                    sys.stderr.write(
                        "   The lectionary table has not been built yet — run "
                        "tools/fetch_lectionary.py once.\n")
                else:
                    sys.stderr.write(f"   Lectionary {number} is not in the table.\n")
                sys.stderr.write("   Creating the file with mostly blank metadata...\n")

        if metadata["readings"]:
            print("   (lectionary_string stays empty — that is USCCB's wording)")


with open(output_file_path, "w", encoding="utf-8") as outfile:
    outfile.write(homilist.format_frontmatter(metadata))

if not FUNERAL and os.path.exists(dl_path):
    os.unlink(dl_path)

if err:
    sys.exit(1)

print(f"✅ New homily created at {os.path.join(HOMILIES, os.path.basename(output_file_path))}")
named = metadata["lectionary_string"] or metadata["title"]
label = f"{metadata['lectionary_number']}: " if metadata["lectionary_number"] else ""
if named:
    print(f"   {label}{named}")
if metadata["readings"]:
    print(f"   {metadata['readings']}")
# Printed on every path, funerals included: `preached` is what the header uses,
# and it is always the preacher's to set.
print("   ↳ set `preached:` to the pruned citation line you want printed")

open_in_editor(output_file_path)

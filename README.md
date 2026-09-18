# homilist-cli

Command-line homily drafting: Markdown + YAML frontmatter →
[pandoc](https://pandoc.org) → [Typst](https://typst.app) → a PDF built for
reading at the ambo. `new.py` scaffolds a draft with the day's readings filled
in, `wc.py` tells you whether it is the right length, `render.py` prints it.

For a preacher who is comfortable at a command line and writes in Markdown. It
assumes the Roman lectionary (USCCB numbering) but handles Maronite and Chaldean
homilies too.

**This repo contains code only.** Your homilies live in a folder you point it at,
outside version control; `.gitignore` blocks `*.md`, `*.pdf` and `*.docx` as a
safety net.

Adapted from [@sjml](https://github.com/sjml)'s
[homily-scripts](https://github.com/sjml/homily-scripts) — see
[Credit and license](#credit-and-license).

## Setup

You need Python 3.11+, `pandoc`, `typst`, and the Cambria font. On a Mac:

```sh
brew install pandoc typst
python3 -m venv env
env/bin/pip install -r requirements.txt
cp config.example.toml config.toml   # then set homilies_dir
tools/fetch_lectionary.py            # builds the readings table, once
```

Cambria ships with Microsoft Office. If you have Word, copy `Cambria*.tt[cf]`
from `/Applications/Microsoft Word.app/Contents/Resources/DFonts/` into
`~/Library/Fonts/`; without it Typst silently falls back to a default serif.

No activation is needed afterward: each script starts with a shell header that
runs it under `env/bin/python`. The venv must be named `env` and sit in this
directory.

## Where the homilies live

`homilies_dir` in `config.toml` (or `$HOMILIES_DIR`, which wins) is the
**drafts** folder. Its parent is the archive root, and the other folders are
found relative to it:

```
Homilies/                 ← archive root: rendered PDFs land here
├── Drafts/               ← homilies_dir: one .md per homily, plus _worksheets
├── Word/                 ← optional: .docx originals, for import; never written
└── Homily Summaries/     ← optional: one summary per homily, for the themes index
```

Only `Drafts/` has to exist. Files starting with `~$` (Word owner files), `._`
(AppleDouble forks) or `.` are ignored everywhere, so a cloud-synced folder is
fine.

The rest of `config.toml`:

| Key | Used by | |
|---|---|---|
| `copy_roots` | `render.py --to` | Folders that hold a per-occasion copy of a PDF |
| `editor` | `new.py` | Where a new draft opens; else `$VISUAL`, `$EDITOR` |
| `[pace]` | `wc.py` | Your words per minute and the word counts you aim for |
| `presider_names`, `known_locations` | `import_docx.py` | Only needed when importing a `.docx` archive |

## Commands

| Command | What it does |
|---|---|
| `./new.py [--date] [--location] [--variant] [--occasion] [--blank]` | Scaffolds a draft with the day's readings. On a date that already has one, opens a second draft |
| `./render.py [draft] [--to FOLDER]` | Renders to PDF at the archive root; `--to` also copies it into an occasion's folder. No argument: the most recent draft |
| `./wc.py [--watch] [draft]` | Word count, time at your pace, and whether it is in range for a Sunday or a daily Mass |
| `./check.py` | Lints the archive: filename/date mismatches, empty required fields, unknown frontmatter |
| `./concat.py [- \| PATH]` | The whole corpus in one file: `tmp/all.txt`, or stdout with `-`, or a path |
| `tools/themes.py` | Writes `Drafts/_themes.md`: every homily's themes and images, one line each |
| `tools/fetch_lectionary.py` | Builds the lectionary-number → readings table |
| `tools/sync_litcal_api.py` | Fills the offline calendar's gaps from LiturgicalCalendarAPI, ahead of time |
| `tools/import_docx.py` | Creates drafts from an existing `.docx` archive |
| `tools/verify_import.py` | Audits imported drafts against their sources; writes a metadata table |
| `tools/locations.py`, `tools/readings.py` | Worksheets for filling a field across many drafts |
| `tools/gen_books.py` | Regenerates `books.py`, the SBL book-abbreviation table |

Every tool takes `--help`. A draft argument can be a path or just the draft's
name, with or without `.md`.

Three modules are libraries rather than commands: `liturgical.py` (the offline
calendar: `lectionary_number`, `dates_for_lectionary`, `describe`, `easter`),
`lectionary.py` (the offline readings for a number), and `litcal_api.py`
(LiturgicalCalendarAPI: `lookup`, the live fallback between USCCB and the
offline route; `gap_fill_lookup`, the cache `tools/sync_litcal_api.py` builds).

## Writing a homily

### 1. Scaffold

```bash
./new.py                                # calendar picker
./new.py --date 2026-08-05              # skip the picker
./new.py --occasion "Smith Funeral"     # set the occasion up front
```

Arrow keys move, `t` is today, `Enter` chooses. Then two prompts: **Location**
(blank copies the most recent draft's) and **Occasion** (usually blank; it is for
`Healing Mass`, `Novena of Grace Day 1`, `Smith Funeral`). The draft is written
as `Drafts/YYYY-MM-DD.md` and opened in your editor. An existing file is never
overwritten. Only `--date` skips the picker; the other flags pre-fill a prompt.

The readings come from one of four sources, tried in order until one answers:

1. **USCCB**, scraped live. It sits behind a bot challenge that scripts usually
   fail, so expect this to miss most of the time.
2. **[LiturgicalCalendarAPI](https://github.com/Liturgical-Calendar/LiturgicalCalendarAPI)**,
   queried live for the US national calendar. An independent computation of the
   same Roman Rite calendar, not dependent on USCCB's uptime. It also knows
   about the days an ordinary date doesn't cover: a Mass with more than one
   time of day (Christmas, Easter Sunday) and the Easter Vigil's own sevenfold
   shape are both handled, and the Chrism Mass never shoulders out Holy
   Thursday's evening Mass, which shares its date and its rank. Two of the
   entries this queries — Christmas and All Saints — have empty readings in
   the API's own data as of this writing, so those two dates still fall
   through to the offline route below.
3. **The offline calendar and lectionary table** (`liturgical.py` +
   `lectionary.py`), no network at all. It computes the lectionary number and
   looks the readings up in the table you fetched at setup — but it says so
   itself: it does not know the whole sanctoral calendar, so some dates (the
   O Antiphon days before Christmas, most memorials) come up empty here. The
   Easter Vigil is a subtler case: it has a lectionary number, but that
   number's entry in the fetched table doesn't resolve to readings, so it
   comes up empty here too.
4. **The gap-fill cache**, whatever `tools/sync_litcal_api.py` has already
   found for a date the offline route can't answer. Also no network at call
   time — the network happened whenever that tool last ran.

Each tries once; a failure falls through rather than retrying. Run
`tools/sync_litcal_api.py` occasionally (there's nothing to schedule it with
here, but cron or a periodic task runner both work) so tier 4 stays useful
without new.py ever depending on a network at the moment you scaffold a draft.

| Field | Filled from |
|---|---|
| `title` | Always the offline calendar, in the archive's short form (`Wed 12th of OT`) |
| `lectionary_number` | USCCB or the offline calendar; empty from the API or the gap-fill cache |
| `readings` | Whichever of the four sources above answered first |
| `lectionary_string` | USCCB only — the calendar's own name for the day. Empty otherwise |
| `preached` | Always empty: it is the line you prune by hand |

**A funeral takes neither route.** Write the occasion as `<Surname> Funeral` and
`new.py` skips the lookup: a funeral's readings are chosen for it, so there is
no lectionary number. It asks for the readings instead and leaves them empty if
you have not settled them. `title` still carries the liturgical day.

### 2. Write

Write below the `---`. Two fields print on the page you read from and are worth
setting first:

- **`preached`** — the citation line that prints. Set it to what you actually
  preach on. Until you do, the header falls back to `readings` minus the psalm.
- **`title`** — already the liturgical day. Change it only to print something
  else.

```bash
./wc.py --watch
```

Redrawn on every save: word count, time at your pace, and whether it is in
range — Sunday and daily Mass have targets, set in `[pace]`; funerals, weddings
and Eastern homilies have none.

### 3. Check, then render

```bash
./check.py
./render.py                           # most recent draft
./render.py 2026-08-23_with-baptisms  # a particular one
```

The PDF goes to the archive root, never into `Drafts/`. If a draft's PDF name
has changed since it was last rendered — a second homily on the same date
appends the venue to both, for instance — the old PDF is removed.

**A copy in the occasion's own folder.** A funeral, a wedding or a school Mass
often has a folder of its own, holding the script and the reading sheet. `--to`
puts the homily there too, named for the primary plus `-homily` so it cannot
collide with a presider script of the same name:

```bash
./render.py 2026-05-16 --to Ashgrove
```

The argument is a path or any fragment of a folder name under `copy_roots`
(case and punctuation ignored): `Ashgrove` finds
`Funerals/Ashgrove, Margaret Ellen MEMORIAL`. A fragment that matches two
folders copies nothing and lists both. Relative `copy_roots` entries are tried
against the archive root and then its parent, since these folders usually sit
beside the archive.

### A second homily on the same day

Say what tells it apart from the one already there:

```bash
./new.py --location "Arrupe House"      # preached somewhere else
./new.py --variant "Without Baptisms"   # same church, a different Mass
./new.py --occasion "Healing Mass"      # a different kind of Mass
```

Use the field that can actually distinguish the two. My rule: different venues
are told apart by `location`, which already prints, so `variant` stays empty —
putting the venue there too prints it twice. `variant` is for two homilies at
the same church. The code only assumes that *some* field differs.

The new draft is named for what you typed (`2026-09-16_arrupe-house.md`) and
starts as a copy of the day's existing draft, since that is usually the text you
want to start from; `--blank` keeps only the frontmatter. A funeral takes
neither the text nor the lectionary.

**Both drafts get a suffix.** The first is renamed by whatever it does not share
with the new one — its venue, or its variant — so neither reads as the default;
if nothing tells them apart you are asked. Its summary, if it has one, is
renamed with it. After that, `new.py` refuses a plain `YYYY-MM-DD.md` on that
date and points you at these flags.

## Have I preached this before?

```bash
tools/themes.py
```

Writes `Drafts/_themes.md`, one line per homily, oldest first:

```
date | rite | title | occasion | variant | location | lect | preached | themes | images
```

`themes` and `images` come from the homily's **summary**: a Markdown file in
`Homily Summaries/` named `<draft name> Summary.md` — for
`2026-08-23_with-baptisms.md`, `2026-08-23_with-baptisms Summary.md`. Two
sections are read:

```markdown
## Core Themes
- One bullet per theme, copied verbatim into `themes`

## Preaching Notes
- Free prose; the proper nouns, quotations and titles in it become `images`
```

How the summaries get written is up to you (a scheduled LLM task works well).
A homily without one gets a row with those columns blank and is listed in the
file's header. The whole archive reads in one pass, which is the point: checking
whether a story has been used before otherwise means opening a dozen files, and
so does not get done.

The extraction is deliberately mechanical — themes copied, images
pattern-matched, header stamped with the newest input's date rather than the
clock — so two runs over an unchanged archive produce an identical file. Image
matching errs toward including too much: a spurious entry costs a glance, a
missing one is the failure the file exists to prevent.

## Frontmatter

```yaml
---
date: '2026-04-12'
rite: ''                                  # empty or Roman; else Maronite / Chaldean
lectionary_number: 43
lectionary_string: ''                     # USCCB's name for the day; scraped or empty
title: Sun 2nd of Easter — Divine Mercy   # the liturgical day, short form
occasion: ''                              # Healing Mass, Smith Funeral, ...
location: St. Anne
readings: 1 Pet 1:3–9; Ps 118; John 20:19–31   # the whole liturgy of the word
preached: 1 Pet 1:3–9; John 20:19–31      # what you preach on; this prints
variant: With Baptisms
source: ''                                # the .docx this was imported from, if any
---
```

Some of what follows the code depends on; the rest is how I keep my archive.
The table says which. The conventions are worth adopting as a set — they are
what make the archive sortable and searchable — but they are mine, and nothing
breaks if yours differ, as long as you are consistent.

| Field | | |
|---|---|---|
| `date` | Must match the filename | code |
| `title` | **The liturgical day**, in the short form below. Prints | convention; the tools write it this way |
| `occasion` | Why this Mass happened: `Healing Mass`, `<Surname> Funeral`. Prints bold; omitted when blank | convention — except that the word `Funeral` is what `new.py` keys on |
| `location` | The venue. Prints | code |
| `preached` | The pruned citation line. Blank falls back to `readings` minus the psalm | code |
| `variant` | Title-cased: `Manuscript`, `Preaching Text`, `With Baptisms`. Never the venue | convention |
| `rite` | Empty or `Roman`; otherwise `Maronite` or `Chaldean` | code: names the PDF and picks the calendar |
| `lectionary_string` | USCCB's own wording. Never write it by hand | convention; `new.py` only ever fills it from USCCB |
| `source` | Provenance for imported drafts; what lets the importer recognise its own output | code |

**How I tell `title`, `occasion` and `lectionary_string` apart.** They are three
different kinds of thing, and an archive where they blur cannot be sorted or
searched:

| Field | Holds | Not |
|---|---|---|
| `title` | The day — what a calendar could have told you before the Mass was scheduled | An event; a Gospel theme |
| `occasion` | Why this Mass happened, on top of the day | The day repeated |
| `lectionary_string` | USCCB's name for the date | Anything you typed |

A Gospel theme (`Healing of Paralytic`) is neither: it describes the reading, so
it belongs in `preached` beside the citation. `rite` already says Maronite or
Chaldean, so the day is `Palm Sunday`, not `Chaldean Palm Sunday`. Citations are
SBL abbreviations throughout (`Matt`, `1 Cor`, `Jonah`); `new.py` and the
importer normalize them.

### Canonical day forms

These are my forms. `standardize_day()` produces them, so an imported archive
lands on them whether or not you would have chosen them; `new.py` writes them
too. If yours differ, change the tables in `homilist.py` — the point is one day
written one way, so the archive groups by season, not these forms in
particular:

| Shape | Form | Examples |
|---|---|---|
| Numbered day in a season | `<Day> <N>th of <Season>` | `Wed 12th of OT`, `Sun 4th of Church` |
| Sunday counted from a feast | `<N>th Sun after <Feast>` | `3rd Sun after Holy Cross` |
| Day named for what it observes | `<Day> of <Name>` | `Sun of Faithful Departed`, `Tue of Easter Octave` |
| A feast in its own right | the name alone | `Ascension`, `Ash Wednesday` |

Weekdays are `Sun Mon Tue Wed Thu Fri Sat`; seasons keep their full name except
`OT`. A tail is joined with an em dash: `Wed 12th of OT — St. Anselm`.

## Rendered filenames

| Rite | Pattern | Example |
|---|---|---|
| Roman | `YYYY-MM-DD Homily NNN [suffix].pdf` | `2026-02-06 Homily 327 Healing Mass.pdf` |
| Maronite / Chaldean | `[Rite] YYYY-MM-DD [Title].pdf` | `Chaldean 2025-04-13 Palm Sunday.pdf` |

Roman names lead with the date so a listing sorts chronologically. Eastern
homilies have no Roman lectionary number, so the day identifies them; the rite
leads so they group together, then the date so each rite sorts within its
group.

The suffix is `occasion` and `variant`. The day is used only where there is
neither a lectionary number nor an occasion to identify the homily. When a date
carries more than one homily, every one of them names its venue.

## Importing a `.docx` archive

If you have years of homilies in Word, `import_docx.py` turns each into a draft
with frontmatter filled in from the document's header, its filename, and the
calendar.

```bash
tools/import_docx.py --dry-run "Word/Homily 280.docx"
tools/import_docx.py --no-network Word/*.docx
```

The `.docx` files are opened read-only. Re-running is safe: each draft records
its `source`, so the importer recognises its own output rather than duplicating
it, and removes a draft it previously wrote under a name that has since changed.

Word splits formatting into runs at arbitrary points and uses `<w:br/>` for line
breaks inside a paragraph; both are handled, but a rendered PDF is the only
place you can see that they were. Render one after any change to the importer.

**Dating** is the hard part. Sources are tried in order of trust:

1. `_date-overrides.txt` — a correction you recorded
2. the date printed in the document's header
3. the summary, when the filename's date is ambiguous (`11-11-19`)
4. the filename
5. the summary
6. the lectionary number, resolved against the file's modification time — which
   is rarely the exact day but is reliably within a month of it, so it narrows
   the candidates to one

The calendar is computed locally: `liturgical.py` calculates Easter, derives the
movable seasons, and inverts the ferial and Sunday numbering. USCCB is consulted
only for numbers the calendar does not carry, and skipped when unreachable.

### Auditing an import

```bash
tools/verify_import.py
```

An import is a bulk edit, so it should be auditable rather than trusted. Every
check re-derives its answer from the source document: the `source` exists and is
claimed once; the body round-trips word for word; the date agrees with the one
printed in the document; the weekday matches the liturgical day; the lectionary
number agrees with the filename; each field holds the kind of value it is for;
and the header did not swallow the homily's opening lines.

Automated checks only catch what they were told to look for, so the same tool
writes the archive as one table for reading by eye:

```bash
tools/verify_import.py --table table.md                  # everything
tools/verify_import.py --table table.md --rite eastern   # Maronite and Chaldean
tools/verify_import.py --table table.md --new            # only what you have not read
tools/verify_import.py --mark-checked                    # having read it
```

Only `--mark-checked` writes: it appends to `_checked.txt`, which is what `--new`
consults. `--rite` takes `eastern`, `roman`, or a rite's name.

### Corrections

The `.docx` files are never edited, so corrections live beside the drafts and
are re-applied on every import — a date in `_date-overrides.txt`:

```
Homily 375.docx = 2026-06-26   # "Friday 12th OT" + lect 375; printed Thu 06-25
```

and any other field in `_metadata-overrides.txt`, keyed the same way. An override
is a correction, not an exemption: a day written there still goes through
`standardize_day()`, a venue through the location aliases, a citation through
SBL normalization.

### Filling a field across many drafts

```bash
tools/locations.py --report locations.txt   # or tools/readings.py
# ...fill in the blanks...
tools/locations.py --apply locations.txt
```

The worksheet is plain `name: value`; everything else is a comment. Each entry
carries enough context to answer from memory, plus a menu of the values already
in use. Blank means skip, so a half-filled worksheet is safe to apply; a single
`-` clears the field. Applied answers are also written to
`_metadata-overrides.txt`, so the next import keeps them.

`readings.py` proposes readings from the lectionary table, or where a number is
not in it, from citations found in the homily's summary — never from memory.

### What lives beside the drafts

| File | |
|---|---|
| `_date-overrides.txt` | Dates corrected or supplied by hand |
| `_metadata-overrides.txt` | Field corrections, keyed by source document |
| `_location-aliases.txt` | Spelling variants of one venue, folded together |
| `_checked.txt` | Sources already read by eye, so `--new` shows only what changed |
| `_locations.txt`, `_readings.txt` | Worksheets, written and read back by their tools |
| `_metadata-table*.md`, `_unresolved.md` | The scannable tables, and what could not be dated |
| `_themes.md` | Every homily's themes and images |

## The lectionary table

`lectionary.py` maps a lectionary number to its readings, from a table
`tools/fetch_lectionary.py` builds out of the tables Felix Just SJ publishes at
<https://catholic-resources.org/Lectionary/> — the only public source keyed by
number rather than by date. It is fetched on demand, cached under `tmp/`, and
not committed: it is someone else's compilation.

| | Readings per number | Resolved by |
|---|---|---|
| Ordinary Time weekdays | two — same Gospel, different first reading | Year I in odd liturgical years, Year II in even |
| Other weekdays | one | — |
| Sundays | one — the number is already cycle-specific | — |

Where a number heads several rows, the table keeps the appointed readings and
records the alternates beside them; choosing is the preacher's call.

## Filling the offline calendar's gaps

```bash
tools/sync_litcal_api.py             # today through ~13 months out
tools/sync_litcal_api.py --days 30   # a narrower window
tools/sync_litcal_api.py --refresh   # recheck dates already cached
```

`liturgical.py` computes the temporal cycle (Advent, Lent, Easter, Ordinary
Time) but not the whole sanctoral calendar, so some dates — the O Antiphon days
before Christmas, most memorials — have no offline answer. The Easter Vigil is
in range too, for a different reason: `liturgical.py` does resolve it to a
lectionary number, but that number's entry in the fetched table doesn't
resolve to readings, so it reads as a gap the same way a missing number does.
This script asks
[LiturgicalCalendarAPI](https://github.com/Liturgical-Calendar/LiturgicalCalendarAPI)
for every date in range where the offline route would currently come up empty,
and writes what it finds to `tmp/litcal_api/gap_fill.json`. `new.py` checks
that cache, with no network call of its own, after `liturgical.py` and
`lectionary.py` have both had nothing to say.

Run it whenever there's a network — after cloning, and every so often after
that — the same way `tools/fetch_lectionary.py` is a once-off rather than
something `new.py` does for you. Nothing here schedules it; cron or a periodic
task runner both work, or just remember to run it now and then. Its window
looks forward from today, so a date already in the past when you run it (last
Easter, say) never gets cached — moot for actual use, since a past date's
homily was scaffolded when it still had a chance to be tried live.

`litcal_api.py`'s live `lookup()` (tier 2 in the list above) and this script's
offline `gap_fill_lookup()` (tier 4) are two uses of the same API, one at
homily-scaffolding time and one ahead of it — see `litcal_api.py`'s own
docstring for why the API's own wording never lands in `lectionary_string`.

## Tests

```bash
./tests/regression.sh
```

Unit checks, then every command run against a throwaway homily directory, so a
test run never touches your archive. Expect `all green`. The lectionary-table
checks are skipped, not failed, until the table has been fetched.

The USCCB scraper is tested against saved fixtures with no network; the fixtures
keep the page's structure and contain no scripture text. LiturgicalCalendarAPI's
`parse()` is likewise tested against a small fixture dict rather than the live
API. `new.py`'s offline fallback is forced by pointing *both* live lookups —
USCCB and LiturgicalCalendarAPI — at a closed port, since a test that depended
on either answering, or failing, would be as flaky as one that depended on the
network at all; the gap-fill cache is tested the same way, on a date the
offline calendar itself cannot answer, with a cache entry the test writes and
then restores afterward (it lives in `tmp/`, not the sandbox, so a real cache
from `tools/sync_litcal_api.py` is never at risk of being overwritten for good).

## The template

`template.typ` keeps @sjml's page design: US Letter, 1″ sides, a 3″ bottom
margin so you are never reading at the bottom edge, Cambria 16pt, and no
paragraph split across a page break. The first page's header, top right,
carries occasion (bold), title, readings, location · date, and a dimmed
`Lectionary N · variant`. Later pages carry only the page number.

## Credit and license

Adapted, with gratitude, from [@sjml](https://github.com/sjml)'s
[homily-scripts](https://github.com/sjml/homily-scripts): the date picker, the
USCCB scraper, the word counter and the Typst template are his. He also built
[Homilist](https://shaneliesegang.com/projects/homilist/), a browser version that
runs pandoc and Typst client-side with nothing installed. What this repo adds is
the workflow around the render step: readings from an offline calendar, sibling
drafts, the themes index, and importing and auditing an existing archive.

**Data:** the lectionary table is built at run time from catholic-resources.org
and not redistributed; USCCB pages are scraped per date and never stored;
LiturgicalCalendarAPI responses are cached under `tmp/` and not committed
either; `books.py` follows the *SBL Handbook of Style*. No scripture text is in
this repository. Calendar data for tier 2 and the gap-fill cache comes from
[LiturgicalCalendarAPI](https://github.com/Liturgical-Calendar/LiturgicalCalendarAPI)
by John R. D'Orazio and contributors (Apache-2.0), an independent computation
of the Roman Rite calendar — not affiliated with this project or with USCCB.

**License:** MIT, see `LICENSE.txt`, which also carries upstream's MIT notice as
that license requires.

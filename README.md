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
| `tools/sync_litcal_api.py` | Fills the offline calendar's gaps ahead of time, or patches in a correction by hand |
| `tools/import_docx.py` | Creates drafts from an existing `.docx` archive |
| `tools/verify_import.py` | Audits imported drafts against their sources; writes a metadata table |
| `tools/locations.py`, `tools/readings.py` | Worksheets for filling a field across many drafts |
| `tools/gen_books.py` | Regenerates `books.py`, the SBL book-abbreviation table |

Every tool takes `--help`. A draft argument can be a path or just the draft's
name, with or without `.md`.

Three modules are libraries rather than commands: `liturgical.py` (the offline
calendar: `lectionary_number`, `dates_for_lectionary`, `describe`, `easter`),
`lectionary.py` (the offline readings for a number), and `litcal_api.py`
(LiturgicalCalendarAPI: `lookup`, the live source that stands in for USCCB;
`citations_agree`, whether two sources' readings are the same; `override_lookup`
and `save_override`, the curated cache in `tmp/litcal_api/overrides.json`).

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

**How readings get filled, in order:**

1. **USCCB**, scraped live. Trusted outright when it answers — the more
   current source, and the only one whose wording lands in `lectionary_string`.
   It sits behind a bot challenge that scripts usually fail, so expect to
   miss it most of the time.
2. **A saved answer** in `tmp/litcal_api/overrides.json`, if this date is
   already in it. No network call, and settled — nothing below runs.
3. **[LiturgicalCalendarAPI](https://github.com/Liturgical-Calendar/LiturgicalCalendarAPI)**
   (live, US national calendar) **and the offline calendar + lectionary
   table** (`liturgical.py` + `lectionary.py`, no network), asked together
   rather than one after the other:
   - only one answers → used, no question asked
   - both answer and **agree** → used (compared on first/second/gospel only —
     see `citations_agree()`; the psalm's punctuation can differ by source
     even when the passage doesn't)
   - both answer and **disagree** → flagged. Interactively, `new.py` prints
     both and asks which to keep, then saves the answer to `overrides.json`
     so the date is settled from then on. Non-interactively there's no one to
     ask, so `readings` is left blank rather than guessed.
   - neither answers → `readings` stays blank

Neither live source is infallible on its own, which is the point of checking
both rather than trusting whichever answers first — catholic-resources.org's
own page (which the offline table is built from) gives 1 Cor 15:12-22 for
lectionary 447/Year II, where USCCB and the API both say 12-20.

The offline route also has known gaps beyond a plain missing number: it
doesn't cover a Mass with more than one time of day (Christmas, Easter
Sunday) or the Easter Vigil's sevenfold shape, and it doesn't know the whole
sanctoral calendar (the O Antiphon days before Christmas, most memorials).
LiturgicalCalendarAPI covers all of that, including keeping the Chrism Mass
from shouldering out Holy Thursday's own Evening Mass.

| Field | Filled from |
|---|---|
| `title` | Always the offline calendar, in the archive's short form (`Wed 12th of OT`) |
| `lectionary_number` | USCCB or the offline calendar; empty from the API or a saved answer |
| `readings` | Whichever source above settled it — USCCB, agreement, your choice on a conflict, or a saved answer |
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

## The curated cache: filling gaps and fixing mistakes

```bash
tools/sync_litcal_api.py                  # today through ~13 months out
tools/sync_litcal_api.py --days 30        # a narrower window
tools/sync_litcal_api.py --refresh        # recheck dates already cached
tools/sync_litcal_api.py --patch 2026-09-18 --readings \
    "1 Cor 15:12-20; Ps 17:1bcd, 6-7, 8b+15; Luke 8:1-3"
```

`tmp/litcal_api/overrides.json` is a curated answer, one date at a time, that
`new.py` checks before asking either live source again. Two things put an
entry there:

**Gaps**, filled ahead of time. With no arguments, `tools/sync_litcal_api.py`
checks every date in its window (today onward — a past date is moot, since it
already had its chance to be tried live) for one the offline route can't
answer (see the known gaps above), and for each one tries USCCB once, then
LiturgicalCalendarAPI. USCCB rarely lands here either — Shane's own words,
closing the PR this project once sent him, were that the bot challenge means
"a script never passes it; the occasional 200 is an edge-cache hit, not a
change of heart" — but it's one cheap request, so it's worth trying first.
Nothing schedules this run; use cron, a periodic task runner, or just
remember to run it now and then.

**Corrections**, for a date the offline table answers *wrong* rather than not
at all — which only a live cross-check or a human can catch; nothing audits
the whole table against a live source on its own. `new.py`'s conflict prompt
saves one automatically when you answer it; `tools/sync_litcal_api.py --patch`
adds one by hand for a bad entry noticed some other way, which is how today's
1 Cor 15:12-22 (lectionary 447/Year II) got fixed here.

`litcal_api.py`'s live `lookup()` and this script's offline `override_lookup()`
are two uses of the same API, one at homily-scaffolding time and one ahead of
it — see `litcal_api.py`'s own docstring for what ends up in the cache and
why the API's own wording never lands in `lectionary_string`.

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
API, and `citations_agree()` has its own unit tests, today's actual conflict
(lectionary 447/Year II) among them. `new.py`'s offline fallback is forced by
pointing *both* live lookups — USCCB and LiturgicalCalendarAPI — at a closed
port, since a test that depended on either answering, or failing, would be as
flaky as one that depended on the network at all.

A disagreement between the two live sources is tested the same way, with the
API's side faked by seeding its year cache for a throwaway host rather than
depending on catholic-resources.org's table actually being wrong on the day
the tests happen to run: the test asserts that both readings are printed and
that `readings` comes back blank (there is no tty in a test run to answer the
prompt), not that a conflict happens to exist right now. The curated cache is
tested by seeding `tmp/litcal_api/overrides.json` directly, for a date the
offline calendar cannot answer at all. Both tests, plus the one before them,
touch that same file, which lives in `tmp/`, not the sandbox — the same as
USCCB's and LiturgicalCalendarAPI's page caches — so a real cache (today's
own patched correction among them) is backed up before any of the three runs
and restored once all three are done, not overwritten for good.

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
this repository. Calendar data for the live cross-check and the curated cache
comes from
[LiturgicalCalendarAPI](https://github.com/Liturgical-Calendar/LiturgicalCalendarAPI)
by John R. D'Orazio and contributors (Apache-2.0), an independent computation
of the Roman Rite calendar — not affiliated with this project or with USCCB.

**License:** MIT, see `LICENSE.txt`, which also carries upstream's MIT notice as
that license requires.

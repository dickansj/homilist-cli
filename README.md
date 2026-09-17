# homilist-cli

Command-line homily drafting: Markdown + YAML frontmatter →
[pandoc](https://pandoc.org) → [Typst](https://typst.app) → a PDF built for
reading at the ambo.

**This repo contains code only.** The homily text lives outside it, in the parish
archive — a synced folder that a document manager indexes — and stays out of
version control.
`.gitignore` blocks `*.md`/`*.pdf`/`*.docx` as a safety net.

## Credit

Adapted, with gratitude, from homily scripts by
**[@sjml](https://github.com/sjml)**, who also built **Homilist** —
<https://shaneliesegang.com/projects/homilist/> — a browser version of the same
idea that compiles pandoc *and* Typst to WebAssembly and converts entirely
client-side. That is the harder engineering problem, and for text like this the
"nothing uploaded, nothing installed" property is a real advantage. This repo
takes the easy path and assumes both are installed locally; what it adds is the
workflow around the render step — scaffolding from the day's readings, archive
linting, bulk import of an existing `.docx` archive.

`template.typ` is adapted from @sjml's original: the page geometry, type, and
pagination discipline are his. The header block was rebuilt around a different
frontmatter schema.

**Data:** the lectionary table is built at run time from the tables Felix Just SJ
publishes at catholic-resources.org and is not redistributed; USCCB is scraped
per date and never stored; `books.py` follows the *SBL Handbook of Style*.
No scripture text is in this repository.

**Licensing:** MIT, see `LICENSE.txt`. The upstream scripts are now published
at <https://github.com/sjml/homily-scripts> under MIT as well, and their notice
is reproduced in the same file, as that license requires.

## Setup

Requires `pandoc` and `typst` (`brew install pandoc typst`), and Cambria — if you
have Microsoft Word, copy `Cambria*.tt[cf]` from
`/Applications/Microsoft Word.app/Contents/Resources/DFonts/` into
`~/Library/Fonts/`, or Typst silently falls back to a default serif.

```sh
python3 -m venv env
env/bin/pip install -r requirements.txt
cp config.example.toml config.toml   # then edit homilies_dir
tools/fetch_lectionary.py            # build the readings table, once
```

No activation needed afterward — the `#!/bin/sh` + `exec env/bin/python` polyglot
header on each script finds `env/` itself. The venv must be named `env` and sit
in this directory.

## Where the homilies live

`homilies_dir` is the **drafts** directory: `$HOMILIES_DIR`, else `config.toml`,
else the parent directory (@sjml's original layout). Everything else is derived
from it, so the archive can be rearranged without editing config:

```
Homilies/                 ← archive root: rendered PDFs land here
├── Drafts/               ← homilies_dir: markdown only, plus the worksheets
├── Word/                 ← the .docx originals, never written to
└── Homily Summaries/     ← one .md per document, used for dating and readings
```

Enumeration goes through `homilist.documents()` and `homily_files()`, which drop
application and filesystem artifacts: `~$` Word owner files, `._` AppleDouble
forks (from cloud-synced volumes), and dotfiles. Word's owner files are the
awkward ones — the prefix *replaces* the first two characters rather than being
added, so `~$mily Healing of the Blind Man.docx` keeps its length and still reads
like a title, while being neither a document nor a valid ZIP.

`word_dir()` finds `Word/` when it exists and falls back to the archive root, so
both layouts work. That matters because every draft records a `source` filename,
and a move that silently broke those would invalidate the audit.

## Commands

| Command | What it does |
|---|---|
| `./new.py [--date] [--location] [--variant] [--occasion] [--blank]` | Scaffolds a draft: picker, prompts, readings. On a date already taken, opens a second draft |
| `./render.py [draft] [--to FOLDER]` | Renders to PDF at the archive root; `--to` also copies it into that occasion's own folder. No argument = most recent |
| `./wc.py [--watch] [draft]` | Word count, time at your pace, and whether it is in range for a Sunday or a daily Mass |
| `./check.py` | Lints the archive: filename/date mismatches, empty required fields, unrecognized frontmatter |
| `./concat.py [- \| PATH]` | The whole corpus in one file: `tmp/all.txt`, or stdout with `-`, or a path |
| `tools/fetch_lectionary.py` | Builds the lectionary-number → readings table |
| `tools/import_docx.py` | Reverse-generates drafts from a `.docx` archive |
| `tools/verify_import.py` | Audits drafts against their sources; writes the metadata table |
| `tools/themes.py` | Writes `Drafts/_themes.md`: every homily's themes and images, one line each |
| `tools/locations.py`, `tools/readings.py` | Worksheets for filling a field in bulk |
| `tools/gen_books.py` | Regenerates `books.py`, the SBL book-name table |

Every tool takes `--help`; the README covers the flow, not every flag.

Two libraries, not commands: **`liturgical.py`** (the calendar —
`lectionary_number`, `dates_for_lectionary`, `describe`, `easter`) and
**`lectionary.py`** (the readings — `readings_for`, `preached_line`).

## Writing a homily, start to finish

### 1. Scaffold

```bash
./new.py                                      # calendar picker
./new.py --date 2026-08-05                    # skip the picker
./new.py --occasion "Smith Funeral"           # set the occasion up front
./new.py --variant "Without Baptisms"         # a second draft for that day
```

**Each flag is independent.** Only `--date` skips the picker; the others just
pre-fill a prompt, so `--variant` on its own still asks you which day.

Arrow keys, `t` for today, `Enter` to choose. Then **Location** (blank copies the
most recent draft's, right most weeks) and **Occasion** (blank is usual; this is
for `Healing Mass`, `Novena of Grace Day 1`, `Smith Funeral`). The draft lands as
`Drafts/YYYY-MM-DD.md`; an existing file for that date is never overwritten.

**USCCB is tried once, then the local route takes over.** One attempt, not a
retry loop — the failure is a policy, not a hiccup.

| | filled from |
|---|---|
| `title` | **Always the local calendar**, so a new draft matches the archive's day form |
| `lectionary_number`, `readings` | USCCB when it answers, otherwise `liturgical.py` + `lectionary.py` |
| `preached` | **Left empty by both routes** — it is the line you prune by hand |
| `lectionary_string` | **USCCB only.** Left empty rather than substituting another source's wording |

**A funeral takes neither route.** Write the occasion as `<Surname> Funeral` —
`Smith Funeral` — and `new.py` skips the lookup entirely: a funeral is not the
day's Mass, its readings are chosen for the funeral, and there is no lectionary
number to find. It asks for the readings instead, and leaves them empty if you
have not settled them yet. `title` still carries the liturgical day, since that
is simply the day it fell on.

Both routes normalize citations to SBL, so a scaffolded draft is spelled like
every imported one. The two agree where they overlap: for 2 August 2026 USCCB
returned lectionary 112 and the calendar computes 112 independently.

The new draft opens in your editor: `editor` in `config.toml`, else `$VISUAL`
or `$EDITOR`, else whatever terminal you are in says it is. Only if it is
actually installed, and only when you are at the keyboard.

### 2. Write

Write below the `---`. Two fields are worth a moment first, because both print on
the page you read from:

- **`preached`** — the citation line that prints. Set it to what you will
  actually preach on. Until you do, the header falls back to `readings` with the
  psalm dropped, so an untrimmed draft still prints sensibly.
- **`title`** — already the liturgical day in canonical form. Change it only if
  you want something else printed.

```bash
./wc.py --watch
```

Word count, time at your pace, and whether it is in range for what it is — a
Sunday, a daily Mass — redrawn on every save. The pace and the targets are
`[pace]` in `config.toml`; funerals, weddings and Eastern homilies get no target.

### 3. Check, then render

```bash
./check.py
./render.py
```

`check.py` lints the whole archive and is worth running before a render rather
than after. `render.py` with no argument takes the most recent draft.

**To render a particular one, name it** — the full path, a path relative to
where you are, or just the draft's name with or without `.md`:

```bash
./render.py 2026-08-23_with-baptisms
```

A near miss lists the drafts it could have meant.

**The PDF goes to the archive root**, not into `Drafts/` — that folder is
markdown only.

**Re-rendering removes a PDF whose name has changed.** A PDF carries no link
back to its draft, so this works from the date: every draft sharing it is asked
what it would be called now, and any PDF bearing that date outside that set is
left over. Adding a sibling is enough to cause one — the venue is only appended
once a date carries more than one homily, so the first draft's PDF is renamed by
the arrival of the second.

### A copy in that occasion's own folder

A funeral, a wedding, a school Mass keeps its own folder with the script, the
reading sheet and the intercessions in it. `--to` puts the homily there too:

```bash
./render.py 2026-05-16 --to Ashgrove
```

**The primary copy always goes to the archive root**; `--to` adds a second one,
named for the primary plus `-homily` — matching the `-sheet` and
`-intercessions` convention those folders already use. That suffix also keeps it
from colliding with the presider script, which is frequently named identically:
both a homily and a liturgy script for the same day can render to
`2026-08-20 Faculty-Staff Mass.pdf`.

The argument is a path, or **any fragment of a folder name** under the
`copy_roots` set in `config.toml` — so `--to Ashgrove` finds
`Funerals/Ashgrove, Margaret Ellen MEMORIAL`. Matching ignores case and
punctuation. **An ambiguous fragment copies nothing** and lists what it could
have meant, because copying into the wrong person's folder is worse than being
asked twice.

Relative `copy_roots` entries resolve against the archive root and then its
parent, since these folders usually sit beside the archive rather than inside
it.

### A second homily on the same day

Say what tells it apart from the one already there:

```bash
./new.py --location "Arrupe House"   # preached somewhere else
./new.py --variant "Without Baptisms"   # same church, a different Mass
./new.py --occasion "Healing Mass"      # a different kind of Mass
```

**Pick the field that can actually tell the two drafts apart.** Different venues
are told apart by `location`, which already prints on the page, so `variant`
stays empty. Put the venue in the variant too and it appears twice — in the
filename and in the header. `variant` is for when both homilies are at the same
church and the venue cannot tell them apart. The flags combine, and the picker
still opens unless you pass `--date`.

The new draft is named for what you typed — `2026-09-16_arrupe-house.md` — and
**starts as a copy of the day's existing draft**. That is a starting point, not a
claim that the two are the same homily: a different congregation usually means
different text. Copying is the default because deleting a copied body takes a
second, while rebuilding a base you wanted does not. `--blank` keeps the
frontmatter — the date's readings and lectionary number — and leaves the text
empty. A funeral occasion takes neither the text nor the lectionary, since it has
its own readings.

**Both drafts get a suffix.** Neither is the default homily, so the first stops
holding the plain `2026-09-16.md` the moment it gains a sibling; otherwise one
reads as the homily and the other as an afterthought. It is renamed by whatever
it does not share with the new one: its venue when they are at different
churches, its variant when they are at the same one. If nothing tells it apart
you are asked, and the answer is written into its `variant`. **Its summary is
renamed with it**, heading included. The summaries task only ever writes, so a
summary left under the old name would be orphaned and a duplicate written beside
it. If a summary already exists under the new name, neither is touched and you
are told. After that, a new
draft on that date without one of the three flags is refused with the same hint,
because a plain `YYYY-MM-DD.md` beside a suffixed one puts the problem straight
back.

The renderer appends the venue to *both* PDF names, so neither is the odd one out
in a listing. It never adds a part the name already contains.

The importer names siblings from their frontmatter the same way: occasion and
variant, failing those the venue, failing that the liturgical day. It skips
whichever one the other drafts that day share. On 2025-08-17 both homilies were
preached at the same church, so only the day tells the Assumption from the
Sunday.

## Have I preached this before?

    tools/themes.py

Writes `Drafts/_themes.md` — one line per homily, pipe-delimited, oldest first:

    date | rite | title | occasion | variant | location | lect | preached | themes | images

`themes` is the Core Themes bullets from that homily's summary, copied verbatim.
`images` is the proper nouns, quotations and titles from its Preaching Notes —
the things that would read as a repeat if they turned up in a second homily.

The point is that it is **one file read**. Asking whether an image has already
been used otherwise means opening a dozen drafts and their summaries, which is
slow enough that it does not get done, and preaching the same story twice is the
result. The whole archive is about 70 KB this way.

Nothing here interprets a homily: the themes are copied, the images are
pattern-matched, and the header is stamped with the newest input's date rather
than the clock — so two runs over an unchanged archive produce an identical file
and a row can be trusted to say what the summary says. The image matching is
crude on purpose and errs towards including too much: a spurious entry is read
past in a second, a missing one is the failure the file exists to prevent.

Summaries are written by a scheduled task, not by anything here. A homily without
one gets a row with blank themes, and is listed by name in the header.

**A summary is named for its draft**: `2026-08-23_with-baptisms.md` is summarised
in `Homily Summaries/2026-08-23_with-baptisms Summary.md`, and the `# ...` heading
inside says the same. Imported homilies were once summarised under the name of
the `.docx` they came from, so the archive ran two conventions at once and every
tool had to know both; they were renamed to this one. `homilist.summary_name()`
holds the rule, and `analyze.py` in the archive root has to agree with it — where
they disagree, a summary that exists reads as missing and gets rewritten.

## Frontmatter

**The liturgical day is `title`** — `Wed 12th of OT`, `Sun 4th of Church`. That is
the field you write, the one the metadata table calls **liturgical day**, and the
one that prints.

`lectionary_string` is a different thing with a confusingly similar job: the
calendar's own full name for the date, in USCCB's words — `Memorial of Saint
Ambrose, Bishop and Doctor of the Church`. **USCCB owns it; never write it by
hand.** It is empty on every Eastern draft, and in fact across the whole imported
archive, because USCCB stopped answering scripts before the import ran.

| Field | |
|---|---|
| `date` | `2026-07-29` — must match the filename |
| `lectionary_number` | `607` |
| `lectionary_string` | The calendar's name for the date, not yours. Scraped or empty |
| `readings` | The whole liturgy of the word |
| `title` | **The liturgical day**, short: `Wed 12th of OT`, `Sun of Faithful Departed` |
| `occasion` | `Healing Mass`, `Novena of Grace Day 1`, `<Surname> Funeral`. Prints bold; omitted when blank |
| `location` | `St. Anne`, `Alumni Chapel` |
| `preached` | The pruned citation line — only what you preach on. Blank falls back to `readings` minus the psalm |
| `variant` | Title-cased: `Manuscript`, `Preaching Text`, `With Baptisms`, `Partial`. Never the venue — that is `location` |
| `rite` | Roman is empty or the word `Roman`. `Maronite` or `Chaldean` otherwise |
| `source` | The `.docx` a draft was imported from. Provenance, and what makes re-importing safe |

### Day, occasion, and the calendar's name

These three drift into each other, and an archive where they have drifted cannot
be sorted or searched. The rule is what *kind* of thing the value is:

| Field | Holds | Not |
|---|---|---|
| `title` | The liturgical day — something a calendar could have told you before the Mass was scheduled | An event, a Gospel theme |
| `occasion` | Why this Mass happened — the circumstance on top of the day | The day itself, repeated |
| `lectionary_string` | USCCB's own name for that date | Anything you typed |

So `Ash Wednesday` is a day; `End of School Year Mass`, `Baptism`, `Novena of
Grace Day 7`, `Smith Funeral` are occasions. Both can be set and often should be. What they must
not do is say the same thing twice.

**A Gospel theme is neither.** `Healing of Paralytic`, `Weeds among wheat`
describe the reading, so they belong in `preached` beside the citation — never in
the day, and never in `location`, where the importer used to strand them.

`rite` already says Maronite or Chaldean, so the day never repeats it: the day is
`Palm Sunday`, not `Chaldean Palm Sunday`.

### Canonical day forms

One day, written one way, or the archive cannot be grouped by season.
`standardize_day()` normalizes `title` to these. Every example is an *output* —
the form is idempotent, and the tests check that:

| Shape | Form | Examples |
|---|---|---|
| Numbered day in a season | `<Day> <N>th of <Season>` | `Wed 12th of OT`, `Sun 4th of Church` |
| Sunday counted from a feast | `<N>th Sun after <Feast>` | `3rd Sun after Holy Cross` |
| Day named for what it observes | `<Day> of <Name>` | `Sun of Faithful Departed`, `Tue of Easter Octave` |
| A feast in its own right | the name alone | `Ascension`, `Ash Wednesday` |

The first two are genuinely different structures: Roman and Chaldean count
*within* a season, much of the Maronite year counts *from* a fixed feast. The
third is tried **only after** the numbered rule declines — ahead of it, it
swallows `Wednesday of 8th OT` and returns `Wed of 8th OT`.

Weekdays are `Sun Mon Tue Wed Thu Fri Sat`; seasons keep their full name except
`OT`. A tail is joined by **an em dash**, whatever the original used:
`Wed 12th of OT — St. Anselm`.

## Rendered filenames

The draft keeps `YYYY-MM-DD.md` — the date makes it unique. The printed copy is
named for how it is found in a folder listing:

| Rite | Pattern | Example |
|---|---|---|
| Roman | `YYYY-MM-DD Homily NNN [suffix].pdf` | `2026-02-06 Homily 327 Healing Mass.pdf` |
| Maronite / Chaldean | `[Rite] YYYY-MM-DD [Title].pdf` | `Chaldean 2025-04-13 Palm Sunday.pdf` |

Roman leads with the date so a listing sorts chronologically. The Eastern rites
have no Roman lectionary number, so the liturgical day identifies them; the rite
leads because they group together, and the date follows it so each rite sorts
chronologically within its group, as the Roman copies do. The date is dropped
when unknown — the name still has to work.

The suffix is `occasion` and `variant`. **The day is a fallback**, used only where
neither a lectionary number nor an occasion already identifies the homily — the
number encodes the day, so `Homily 239 Wed 3rd of Lent` says it twice. The venue
is appended whenever a date carries more than one homily, all of them, not just
the pair that would collide.

## Importing a `.docx` archive

```bash
tools/import_docx.py --dry-run "Word/Homily 280.docx"
tools/import_docx.py --no-network Word/*.docx
```

**Non-destructive**: the `.docx` is opened read-only. Re-running is safe — a draft
records its `source`, so the importer recognises its own output rather than
duplicating it, and a draft orphaned by a renamed field is removed.

### How the document is read

Two things about Word's XML have caused visible damage, both now handled:

- **A run is not a phrase.** Word splits one wherever it likes — a spell-check
  boundary, a language attribute, a tracked revision — so a single italic phrase
  arrives as several runs. Marking each separately produced `*t**he souls of the
  just*`, which markdown does not read as emphasis at all: pandoc printed the
  asterisks. Adjacent runs sharing formatting are merged before any marker goes
  on.
- **`<w:br/>` is a line break inside a paragraph**, which is how scripture gets
  set in sense lines. Dropping it ran words together — "the LORD of
  hostswill provide" — so it becomes a markdown hard break.

Neither is visible in the markdown at a glance; both are obvious in a rendered
PDF. Worth rendering one after any change here.

**Dating is the hard part**, and sources are tried in descending order of trust:

1. `_date-overrides.txt` — a correction recorded by hand
2. the date printed in the document's own header
3. the summary, **when the filename date is ambiguous** — `11-11-19` is a real
   date read either way, and taking it as `yy-mm-dd` put a 2019 homily in 2011
4. the filename
5. the summary
6. the lectionary number, resolved against the file's timestamp window

That last step works because of a measured fact: against homilies whose text
carries an explicit date, the file's `modified` timestamp is exact only 74% of the
time — useless as an answer — but within 30 days **100%** of the time. So it is a
reliable *window*, and the lectionary number picks the day inside it.

**Dates are computed locally.** `liturgical.py` calculates Easter in closed form,
derives every movable season from it, and inverts the ferial and Sunday
numbering. USCCB remains only as a fallback for numbers the calendar does not
carry, and is skipped when unreachable — it sits behind a bot challenge that a
script cannot pass. An occasional request still returns 200; that is an edge-cache
hit, not a change of policy, and a single success is not evidence it is working
again.

The calendar has the property the scraper never could: **it can be tested.**

## Auditing an import

```bash
tools/verify_import.py
```

An import is a bulk edit, so it should be auditable rather than trusted. Every
check re-derives its answer from the source `.docx` — a draft that agrees with
itself proves nothing.

- the recorded `source` still exists, and no two drafts claim the same one
- **the body round-trips**: same words, same order, as the document
- the date agrees with the date printed in the document
- **the weekday matches the liturgical day** — a day saying "Sunday" must fall on one
- the lectionary number agrees with the filename, and a non-Roman rite has none
- fields hold the kind of value they are for
- **the header did not eat the homily** — measured, not re-parsed

**One blind spot is worth naming**, because it hid a real bug: the body round-trip
compares the draft against `split_header()`'s *output*, so a header that swallows
the opening lines loses the same words on both sides and the check passes. Two
measures sit outside that function — how many words the header took, and whether a
header line reads as a sentence. The lesson generalizes: a check sharing a parser
with the thing it checks can only find disagreements, not shared mistakes.

### Reading it by eye

Automated checks only catch what they were told to look for. A wrong venue that
looks like a venue passes every rule and is obvious to a person in a second, so
the same tool writes the archive out as one scannable table:

```bash
tools/verify_import.py --table table.md                  # all of it
tools/verify_import.py --table table.md --rite eastern   # Maronite and Chaldean
tools/verify_import.py --table table.md --new            # only what you have not read
tools/verify_import.py --table table.md --sort rite      # grouped by rite
tools/verify_import.py --mark-checked                    # having read it
```

Every one is read-only **except `--mark-checked`**, which appends to `_checked.txt`
and so empties the next `--new` table.

`--rite` takes `eastern`, `roman`, or a name. The Roman rite is written two ways —
an empty field or the word itself — so neither slice can be a truthiness test, and
both go through one shared `is_eastern()`.

### When a document disagrees with itself

Some homilies print a date that is not the day their named liturgical day fell on.
The `.docx` files are the archive and are never edited, so corrections live beside
the drafts and are re-applied on every import:

```
Homily 375.docx = 2026-06-26   # "Friday 12th OT" + lect 375; printed Thu 06-25
```

Field corrections work the same way in `_metadata-overrides.txt`. **An override is
a correction, not an exemption from the conventions** — a day written there still
goes through `standardize_day()`, a venue through the aliases, a citation through
SBL normalization. Applied raw, the overrides file quietly became the one place
the rules did not reach.

### What lives beside the drafts

| File | |
|---|---|
| `_date-overrides.txt` | Dates corrected or supplied by hand |
| `_metadata-overrides.txt` | Field corrections, keyed by source document |
| `_location-aliases.txt` | Spelling variants of one venue, folded together |
| `_checked.txt` | Sources already read by eye, so `--new` shows only what changed |
| `_locations.txt`, `_readings.txt` | Worksheets, written and read back by their tools |
| `_metadata-table*.md`, `_unresolved.md` | The scannable tables, and what could not be dated |
| `_themes.md` | Every homily's themes and images, for answering "have I preached this before?" |

## Filling a field in bulk

```bash
tools/locations.py --report locations.txt   # or tools/readings.py
# ...fill in the blanks...
tools/locations.py --apply locations.txt
```

The worksheet is plain `name: value`; everything else is a comment. Each entry
carries enough context to answer from memory — weekday, day, occasion, readings,
opening line — plus a menu of the values already in use.

**Blank means skip**, so a half-filled worksheet is safe to apply. **A single `-`
clears.** Those have to differ: when blank meant both, deleting a wrong value
silently did nothing. An applied answer is also written to
`_metadata-overrides.txt`, or the next import would discard it.

`locations.py` flags values used only once, or shaped oddly for a place name.
`readings.py` **proposes nothing from memory** — a proposal comes from the
lectionary table, or where a number is not in it, from citations in the homily's
summary, shown with their source.

Worth knowing: **homily bodies almost never contain a formal citation** — 1 of
127 imported, and that one is a homily *about* John 3:16 which names the verse
outright. The texts otherwise quote scripture without the reference, as you
would aloud, so the summaries are the only other evidence there is.

### How many readings a number maps to

| | sets per number | resolved by |
|---|---|---|
| Ordinary Time weekdays | **two** — same Gospel, different first reading | Year I in odd liturgical years, Year II in even |
| Lent, Easter, Advent, Christmas weekdays | one | — |
| Sundays | one — the number is already cycle-specific | — |

Checked against the archive rather than asserted: lect 280 falls in 2025 and 2026
with identical readings; lect 491 falls in two weekday years with the same Gospel,
`Wis 1:1-7` in Year I and `Titus 1:1-9` in Year II.

Some numbers head several rows, the later ones marked `opt:` — the Holy Family is
appointed `Sir 3` and `Matt 2` in every cycle, with optional alternates. The table
keeps the **appointed** form and records the alternates beside it, because
choosing between them is the preacher's call.

The table is built from the tables Felix Just SJ publishes at
<https://catholic-resources.org/Lectionary/>, the only public source found keyed
by **number** rather than by date. Fourteen pages, cached under `tmp/` and **not
committed** — it is someone else's compilation, fetched on demand rather than
redistributed.

## Tests

```bash
./tests/regression.sh
```

Unit checks plus a full command run against a throwaway homily directory, so a
test run can never touch the real archive. Expect `all green`.

- **The USCCB scraper**, against saved fixtures — no network. Its failure mode is a
  homily file with blank metadata noticed at the wrong moment; the important case
  is a **renamed wrapper class raising rather than returning nothing**.
- **The liturgical calendar.** Easter across six years, then a lectionary number
  for nineteen dates, each taken from a homily whose date came from its own
  document — so the test checks the arithmetic rather than restating it.
- **The lectionary table**, where it has been fetched; skipped, not failed, on a
  fresh clone. Every expectation was read off the source by hand.
- **`standardize_day()`** — all three shapes, Eastern seasons opt-in, and
  idempotence for every documented form, since a form that is not a fixed point
  walks the archive away from the convention one re-import at a time.
- **`header_line()`** — which opening lines are header and which are the homily.
  Length was the old test and was wrong in both directions.
- **`paragraphs()`** — that adjacent runs sharing formatting merge before
  emphasis markers are applied, built from synthetic `.docx` files whose runs are
  split the way Word splits them.
- **Frontmatter round-tripping**, since pandoc reads the same block as real YAML.
- **`new.py`'s local fallback**, forced by pointing the lookup at a closed port — a
  test depending on USCCB *failing* would be as flaky as one depending on it
  working.

The fixtures deliberately contain **no scripture text**: that text is licensed, so
the fixture keeps the real class names and nesting and drops the rest.

## The template

`template.typ` keeps @sjml's page design — US Letter, 1″ sides, a **3″ bottom
margin** so you are never reading at the bottom edge, Cambria 16pt, tight leading,
and `#show par: block(breakable: false)` so **no paragraph splits across a page
break.**

The page-1 header, top right, carries: occasion (bold), title, readings,
location · long-form date, and a dimmed `Lectionary N · variant`. Later pages
carry only the page number.

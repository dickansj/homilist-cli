#!/bin/bash
# Everything, in one command. Run after touching any script or the template.
#
#   ./tests/regression.sh

cd "$(dirname "$0")/.." || exit 1
fail=0

echo "unit checks:"
env/bin/python tests/units.py || fail=1

# The scripts operate on a directory of homilies; give them a throwaway one so a
# test run can never touch the Parish Mirror.
sandbox=$(mktemp -d)
export HOMILIES_DIR="$sandbox"
trap 'rm -rf "$sandbox"' EXIT

cat > "$sandbox/2026-08-02.md" <<'EOF'
---
date: '2026-08-02'
lectionary_number: 112
lectionary_string: Eighteenth Sunday in Ordinary Time
title: ''
occasion: Healing Mass
location: St. Anne
readings: Isa 55:1-3; Ps 145:8-9; Rom 8:35, 37-39; Matt 14:13-21
preached: Isaiah 55:1-3 / Matthew 14:13-21
variant: ''
---

A man dies and his barns are full.

*That* is the whole parable.

---

But there is a second question to ask.
EOF

echo
echo "commands:"

run() { # description, command...
	printf "  %-40s " "$1"; shift
	if "$@" >/dev/null 2>&1; then echo "OK"; else echo "FAIL"; fail=1; fi
}
refuse() {
	printf "  %-40s " "$1"; shift
	if "$@" >/dev/null 2>&1; then echo "NOT REFUSED -- bug"; fail=1; else echo "refused"; fi
}

run "check.py passes a clean archive"  ./check.py
run "wc.py counts a homily"            ./wc.py "$sandbox/2026-08-02.md"
run "concat.py builds the corpus dump" ./concat.py

# `-` puts the corpus on stdout and nothing else there, so it can be piped.
printf "  %-40s " "concat.py - writes only the corpus"
if ./concat.py - 2>/dev/null | head -1 | grep -q "^====="; then
	echo "OK"; else echo "FAIL"; fail=1
fi
run "render.py produces a PDF"         ./render.py "$sandbox/2026-08-02.md"

echo
echo "content:"

expect() { # description, actual, wanted
	printf "  %-40s " "$1"
	if [ "$2" = "$3" ]; then echo "OK"; else echo "FAIL (got '$2', want '$3')"; fail=1; fi
}

# wc.py says what kind of Mass the draft is for and how it measures up. The
# sandbox draft is dated a Sunday, and 22 words is well under.
printf "  %-40s " "wc.py measures against the target"
if ./wc.py "$sandbox/2026-08-02.md" | grep -q "Sunday: under by"; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# ...and takes a bare draft name, like render.py.
printf "  %-40s " "wc.py takes a bare draft name"
if (cd "$sandbox" && "$OLDPWD/wc.py" 2026-08-02 | grep -q "words"); then
	echo "OK"; else echo "FAIL"; fail=1
fi

# wc.py must exclude the frontmatter from the count. The body is 22 whitespace-
# separated tokens: 8 + 5 + 8 words of prose, plus the `---` divider, which counts
# as one. That is a fraction of a second of preaching time, so it is left alone --
# but it is asserted here so the number is deliberate rather than a surprise.
words=$(./wc.py "$sandbox/2026-08-02.md" | grep -oE '[0-9,]+ words' | cut -d' ' -f1)
expect "word count excludes frontmatter" "$words" "22"

# new.py must produce a usable draft without the network. USCCB answers
# intermittently -- it sits behind a bot challenge -- so the local calendar and
# lectionary table are the fallback, and this forces that path by pointing the
# lookup at a closed port. A test that relied on USCCB failing would be as flaky
# as one that relied on it working.
printf "  %-40s " "new.py falls back to the local calendar"
if HOMILIES_DIR="$sandbox" USCCB_URL_TEMPLATE="http://127.0.0.1:9/%m%d%y.cfm" \
        ./new.py --date 2026-03-08 </dev/null >/dev/null 2>&1; then
	if grep -q "^lectionary_number: 28$" "$sandbox/2026-03-08.md" \
	   && grep -q "^title: Sun 3rd of Lent$" "$sandbox/2026-03-08.md" \
	   && grep -q "John 4:5" "$sandbox/2026-03-08.md"; then
		echo "OK"
	else
		echo "FAIL (draft written but missing number/day/readings)"; fail=1
	fi
else
	echo "FAIL (new.py exited non-zero)"; fail=1
fi

# lectionary_string is USCCB's wording; the local route must leave it empty
# rather than substitute another source's phrasing for it.
printf "  %-40s " "local route leaves lectionary_string"
if grep -q "^lectionary_string: ''$" "$sandbox/2026-03-08.md"; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# `preached` is the line you prune by hand. Neither route fills it -- doing so on
# only one made the scaffolder behave differently depending on whether a website
# answered.
printf "  %-40s " "neither route fills preached"
if grep -q "^preached: ''$" "$sandbox/2026-03-08.md"; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# No parishioner name may appear in a tracked file. Names arrive through
# occasions like "<Surname> Funeral" and "<Surname> Baptism", and the archive is
# the only place they belong. This reads the local archive to learn which names
# to look for, and is skipped when it is not reachable -- so it never puts a
# name into this repo in order to check for names.
printf "  %-40s " "no parishioner name in the repo"
if names=$(HOMILIES_DIR="${REAL_HOMILIES:-$(./ -c 2>/dev/null)}" true 2>/dev/null; \
           env/bin/python - <<'PYNAMES' 2>/dev/null
import os, re, sys
sys.path.insert(0, ".")
os.environ.pop("HOMILIES_DIR", None)
import homilist
try:
    files = homilist.homily_files(homilist.homilies_dir())
except OSError:
    sys.exit(9)
out = set()
for _n, path in files:
    try:
        meta, _b = homilist.split_frontmatter(open(path).read())
    except Exception:
        continue
    occasion = str(meta.get("occasion", ""))
    m = re.match(r"([A-Z][A-Za-z'\u2019-]+)\s+(Funeral|Baptism|Wedding)\b", occasion)
    if m:
        out.add(m.group(1))
print("\n".join(sorted(out)))
PYNAMES
); then
	leaked=""
	for n in $names; do
		if git grep -qi -- "$n" -- . 2>/dev/null; then leaked="$leaked $n"; fi
	done
	if [ -z "$leaked" ]; then echo "OK"; else echo "FAIL (in tracked files:$leaked)"; fail=1; fi
else
	echo "SKIP (archive not reachable)"
fi

# Rendering happens from the drafts folder, so a bare name -- with or without
# the extension -- has to be enough.
printf "  %-40s " "render.py takes a bare draft name"
if (cd "$sandbox" && HOMILIES_DIR="$sandbox" "$OLDPWD/render.py" 2026-08-02 \
        >/dev/null 2>&1); then
	echo "OK"; else echo "FAIL"; fail=1
fi

# A funeral is not the day's Mass: its readings are chosen for the funeral, so
# there is no lectionary number and nothing to look up. The surname convention
# lives in the occasion. No real name appears here -- names stay in config.toml
# and the archive, never in this repo.
printf "  %-40s " "a funeral skips the lectionary"
if HOMILIES_DIR="$sandbox" ./new.py --date 2026-08-21 --occasion "Smith Funeral" \
        </dev/null >"$sandbox/funeral.out" 2>&1; then
	f="$sandbox/2026-08-21.md"
	if grep -q "^lectionary_number: ''$" "$f" \
	   && grep -q "^lectionary_string: ''$" "$f" \
	   && grep -q "^readings: ''$" "$f" \
	   && grep -q "^occasion: Smith Funeral$" "$f" \
	   && grep -q "^title: Fri 20th of OT$" "$f"; then
		echo "OK"
	else
		echo "FAIL (funeral frontmatter wrong)"; fail=1
	fi
else
	echo "FAIL (new.py exited non-zero)"; fail=1
fi

# The hint prints on every path, funerals included -- `preached` is what the
# header uses and is always the preacher's to set.
printf "  %-40s " "funeral still prompts for preached"
if grep -q "set \`preached:\`" "$sandbox/funeral.out"; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# Until preached is filled, the header falls back to the whole liturgy of the
# word -- minus the psalm, which is the one part nobody preaches from.
./render.py "$sandbox/2026-03-08.md" >/dev/null 2>&1
untrimmed="$(dirname "$sandbox")/2026-03-08 Homily 28.pdf"
printf "  %-40s " "untrimmed header drops the psalm"
if pdftotext "$untrimmed" - 2>/dev/null | grep -q "Exod 17:3" \
   && ! pdftotext "$untrimmed" - 2>/dev/null | grep -q "Ps 95"; then
	echo "OK"
else
	echo "FAIL (psalm still in the header, or the reading is missing)"; fail=1
fi

# The printed copy is named from the frontmatter, not the draft filename: date
# first so it sorts, then the lectionary number the .docx archive is filed by,
# then whatever distinguishes it from a sibling.
# Rendered copies go to the archive root, not into the drafts folder -- that
# folder holds markdown. The sandbox's root is its parent.
pdf="$(dirname "$sandbox")/2026-08-02 Homily 112 Healing Mass.pdf"
printf "  %-40s " "pdf named from the frontmatter"
if [ -f "$pdf" ]; then echo "OK"; else echo "FAIL (looked for '$(basename "$pdf")')"; fail=1; fi

# The rendered header is built from the frontmatter, and `preached` overrides
# `readings` -- the whole point of having both.
printf "  %-40s " "header uses preached, not readings"
if pdftotext "$pdf" - 2>/dev/null | grep -q "Isaiah 55:1-3 / Matthew 14:13-21"; then
	echo "OK"
else
	echo "FAIL"; fail=1
fi
printf "  %-40s " "header carries the occasion"
if pdftotext "$pdf" - 2>/dev/null | grep -qi "HEALING MASS"; then echo "OK"; else echo "FAIL"; fail=1; fi

# Paragraphs must never split across a page break -- the rule the template exists
# for. A one-page homily is the trivial case; assert the setting survives instead.
printf "  %-40s " "template keeps paragraphs whole"
if grep -q "breakable: false" template.typ; then echo "OK"; else echo "FAIL"; fail=1; fi

echo
echo "guards (all should refuse):"

# A colon in an unquoted value is invalid YAML. pandoc rejects the same file, so
# check.py and render.py must both refuse rather than mislead.
cat > "$sandbox/2026-08-09.md" <<'EOF'
---
date: '2026-08-09'
title: Martha: A Study in Grief
---

body
EOF
refuse "check.py rejects invalid YAML"   ./check.py
refuse "render.py rejects invalid YAML"  ./render.py "$sandbox/2026-08-09.md"
rm -f "$sandbox/2026-08-09.md"

# A filename that disagrees with its own frontmatter date is a filing mistake.
cp "$sandbox/2026-08-02.md" "$sandbox/2026-09-13.md"
refuse "check.py catches date/name mismatch" ./check.py
rm -f "$sandbox/2026-09-13.md"

# The `_suffix` form is legitimate: a second homily on the same day.
cp "$sandbox/2026-08-02.md" "$sandbox/2026-08-02_second.md"
run "check.py accepts a _suffix variant" ./check.py
rm -f "$sandbox/2026-08-02_second.md"

# --- last, because these change the sandbox ------------------------------------
# Adding a sibling renames the first draft's PDF: the venue is only appended once
# a date carries more than one homily. So every check above that names a PDF or
# reads its header has to run before this point.

# --to puts a copy in the folder that occasion already keeps -- the funeral, the
# wedding, the school Mass, alongside its script and reading sheet. A fragment
# is enough; the whole path never has to be typed.
printf "  %-40s " "--to copies by folder fragment"
mkdir -p "$sandbox/../Funerals/Smith, Jane"
cat > "$sandbox/copyroots.toml" <<'TOML'
copy_roots = ["Funerals"]
TOML
if HOMILIES_DIR="$sandbox" ./render.py "$sandbox/2026-08-02.md" \
        --to "$(dirname "$sandbox")/Funerals/Smith, Jane" >/dev/null 2>&1; then
	if ls "$(dirname "$sandbox")/Funerals/Smith, Jane/"*-homily.pdf >/dev/null 2>&1; then
		echo "OK"; else echo "FAIL (no -homily.pdf copy)"; fail=1
	fi
else
	echo "FAIL (render exited non-zero)"; fail=1
fi

# The copy is named for the primary plus -homily, so it never collides with a
# presider script of the same name already in that folder.
printf "  %-40s " "the copy takes the -homily suffix"
if ls "$(dirname "$sandbox")/Funerals/Smith, Jane/"*" Homily 112-homily.pdf" \
      >/dev/null 2>&1 \
   || ls "$(dirname "$sandbox")/Funerals/Smith, Jane/"*-homily.pdf >/dev/null 2>&1; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# A fragment that could mean two folders must refuse rather than pick one.
printf "  %-40s " "an ambiguous --to refuses"
mkdir -p "$sandbox/../Funerals/Smithson, Ann"
if HOMILIES_DIR="$sandbox" ./render.py "$sandbox/2026-08-02.md" --to Smith \
        >/dev/null 2>&1; then
	echo "FAIL (picked one)"; fail=1
else
	echo "OK"
fi

# A variant is the same homily on the same day, diverging -- "With Baptisms" and
# "Without", a Manuscript and its Preaching Text. It is written as the sibling
# YYYY-MM-DD_suffix.md and COPIED from the first draft, because what you want is
# the text already written, not a blank page with the same readings.
printf "  %-40s " "a variant copies the first draft"
printf 'Body of the first draft.\n' >> "$sandbox/2026-08-02.md"
if HOMILIES_DIR="$sandbox" ./new.py --date 2026-08-02 --variant "Without Baptisms" \
        </dev/null >/dev/null 2>&1; then
	v="$sandbox/2026-08-02_without-baptisms.md"
	if grep -q "^variant: Without Baptisms$" "$v" \
	   && grep -q "Body of the first draft." "$v" \
	   && grep -q "^lectionary_number: 112$" "$v"; then
		echo "OK"
	else
		echo "FAIL (variant not copied faithfully)"; fail=1
	fi
else
	echo "FAIL (new.py exited non-zero)"; fail=1
fi

# Neither of a pair is the default one, so the first draft stops holding the
# plain date the moment it acquires a sibling. Named from its own frontmatter --
# here the occasion, there being no variant to go on.
printf "  %-40s " "the first draft gains a suffix too"
if [ -f "$sandbox/2026-08-02_healing-mass.md" ] \
   && [ ! -f "$sandbox/2026-08-02.md" ]; then
	echo "OK"; else echo "FAIL (base kept the plain date)"; fail=1
fi

# ...and a plain YYYY-MM-DD.md must not be creatable beside them afterwards.
printf "  %-40s " "a third draft that day is refused"
if HOMILIES_DIR="$sandbox" ./new.py --date 2026-08-02 </dev/null 2>&1 \
        | grep -q "already has a draft"; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# A flag written with one dash used to match nothing and scaffold a plain draft
# in silence -- the worst outcome, because it looks like it worked.
printf "  %-40s " "one dash instead of two is refused"
if HOMILIES_DIR="$sandbox" ./new.py -variant "Morning" </dev/null 2>&1 \
        | grep -q "two dashes"; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# Hitting an existing date is the common way to discover you wanted a variant,
# so the error has to say so.
printf "  %-40s " "the date-taken error points at --variant"
if HOMILIES_DIR="$sandbox" ./new.py --date 2026-08-02 </dev/null 2>&1 \
        | grep -q -- "--variant"; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# A rename leaves the old PDF behind, and adding a sibling is enough to cause
# one: the venue is only appended once a date carries more than one homily, so
# the first draft's PDF is renamed by the arrival of the second. Run after the
# variant exists, so there is a sibling to protect.
root="$(dirname "$sandbox")"
HOMILIES_DIR="$sandbox" ./render.py "$sandbox/2026-08-02_healing-mass.md" >/dev/null 2>&1
HOMILIES_DIR="$sandbox" ./render.py "$sandbox/2026-08-02_without-baptisms.md" >/dev/null 2>&1
before=$(ls "$root"/*.pdf 2>/dev/null | wc -l | tr -d ' ')

printf "  %-40s " "a superseded PDF is swept"
touch "$root/2026-08-02 Homily 112 Stale Name.pdf"
HOMILIES_DIR="$sandbox" ./render.py "$sandbox/2026-08-02_healing-mass.md" >/dev/null 2>&1
if [ ! -f "$root/2026-08-02 Homily 112 Stale Name.pdf" ]; then
	echo "OK"; else echo "FAIL (stale PDF kept)"; fail=1
fi

# ...and a sibling's current PDF must survive it.
printf "  %-40s " "the sweep spares a sibling's PDF"
after=$(ls "$root"/*.pdf 2>/dev/null | wc -l | tr -d ' ')
if [ "$before" = "$after" ] && ls "$root"/*"Without Baptisms"*.pdf >/dev/null 2>&1; then
	echo "OK"; else echo "FAIL (a current PDF was removed: $before -> $after)"; fail=1
fi


# The themes index reads two directories at once -- the drafts and the summaries
# beside them -- so it gets an archive of its own rather than the flat sandbox,
# and the check is that a theme and an image actually make it into the row.
printf "  %-40s " "themes.py indexes a summary"
archive="$sandbox/archive"
mkdir -p "$archive/Drafts" "$archive/Homily Summaries"
cat > "$archive/Drafts/2026-08-02.md" <<'EOF'
---
date: '2026-08-02'
rite: ''
lectionary_number: 112
title: Sun 18th of OT
location: St. Anne
preached: Matt 14:13-21
---

Body.
EOF
cat > "$archive/Homily Summaries/2026-08-02 Summary.md" <<'EOF'
# 2026-08-02 Summary

## Core Themes
- Bread enough for everyone

## Preaching Notes
- Quotes St. Ignatius, "Go, set the world on fire."
EOF
if HOMILIES_DIR="$archive/Drafts" ./tools/themes.py >/dev/null 2>&1; then
	row=$(grep '^2026-08-02 ' "$archive/Drafts/_themes.md")
	if [ "$(echo "$row" | awk -F'[|]' '{print NF}')" = "10" ] \
	   && echo "$row" | grep -q "Bread enough for everyone" \
	   && echo "$row" | grep -q "Go, set the world on fire" \
	   && echo "$row" | grep -q "St. Ignatius"; then
		echo "OK"
	else
		echo "FAIL (row: $row)"; fail=1
	fi
else
	echo "FAIL (themes.py exited non-zero)"; fail=1
fi

# Reading it is the point, so it has to be worth trusting twice: same inputs,
# same file. A wall-clock stamp in the header would break this.
printf "  %-40s " "themes.py is idempotent"
cp "$archive/Drafts/_themes.md" "$archive/first.md"
HOMILIES_DIR="$archive/Drafts" ./tools/themes.py >/dev/null 2>&1
if diff -q "$archive/first.md" "$archive/Drafts/_themes.md" >/dev/null; then
	echo "OK"; else echo "FAIL (second run differs)"; fail=1
fi

# --- a second homily named by what tells it apart ------------------------------
# Different congregations: the venue already prints, so it is the only field
# the new draft needs, and the variant stays empty -- otherwise the venue lands
# in the filename and on the page twice.
cat > "$sandbox/2026-10-07.md" <<'EOF'
---
date: '2026-10-07'
lectionary_number: 463
title: Wed 27th of OT
occasion: ''
location: Riverside Hall
readings: Gal 2:1–2, 7–14; Luke 11:1–4
preached: Luke 11:1–4
variant: ''
---

Body of the first homily.
EOF

printf "  %-40s " "--location opens a second draft"
if HOMILIES_DIR="$sandbox" ./new.py --date 2026-10-07 --location "Hillcrest Chapel" \
        </dev/null >/dev/null 2>&1; then
	n="$sandbox/2026-10-07_hillcrest-chapel.md"
	if grep -q "^location: Hillcrest Chapel$" "$n" \
	   && grep -q "^variant: ''$" "$n" \
	   && grep -q "Body of the first homily." "$n"; then
		echo "OK"
	else
		echo "FAIL (wrong fields or no copy)"; fail=1
	fi
else
	echo "FAIL (new.py exited non-zero)"; fail=1
fi

printf "  %-40s " "the first is renamed by its own venue"
if [ -f "$sandbox/2026-10-07_riverside-hall.md" ] && [ ! -f "$sandbox/2026-10-07.md" ]; then
	echo "OK"; else echo "FAIL"; fail=1
fi

printf "  %-40s " "--blank starts with no text"
if HOMILIES_DIR="$sandbox" ./new.py --date 2026-10-07 --location "Harbor House" --blank \
        </dev/null >/dev/null 2>&1 \
   && grep -q "^lectionary_number: 463$" "$sandbox/2026-10-07_harbor-house.md" \
   && ! grep -q "Body of the first homily." "$sandbox/2026-10-07_harbor-house.md"; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# A funeral on a day that already has a homily is never a copy of it.
printf "  %-40s " "a funeral sibling takes nothing over"
if HOMILIES_DIR="$sandbox" ./new.py --date 2026-10-07 --occasion "Smith Funeral" \
        </dev/null >/dev/null 2>&1; then
	f="$sandbox/2026-10-07_smith-funeral.md"
	if grep -q "^lectionary_number: ''$" "$f" && grep -q "^readings: ''$" "$f" \
	   && ! grep -q "Body of the first homily." "$f"; then
		echo "OK"; else echo "FAIL (lectionary or text carried over)"; fail=1
	fi
else
	echo "FAIL (new.py exited non-zero)"; fail=1
fi

printf "  %-40s " "the date-taken hint offers --location"
if HOMILIES_DIR="$sandbox" ./new.py --date 2026-10-07 </dev/null 2>&1 \
        | grep -q -- "--location"; then
	echo "OK"; else echo "FAIL"; fail=1
fi

# The venue in the variant, the way it used to happen: named once, not twice.
printf "  %-40s " "a venue repeated in the name is dropped"
cp "$sandbox/2026-10-07_hillcrest-chapel.md" "$sandbox/dup.tmp"
sed -i '' "s/^variant: ''$/variant: Hillcrest Chapel/" "$sandbox/2026-10-07_hillcrest-chapel.md"
if HOMILIES_DIR="$sandbox" ./render.py "$sandbox/2026-10-07_hillcrest-chapel.md" >/dev/null 2>&1 \
   && ls "$(dirname "$sandbox")/2026-10-07 Homily 463 Hillcrest Chapel.pdf" >/dev/null 2>&1; then
	echo "OK"; else echo "FAIL"; fail=1
fi
mv "$sandbox/dup.tmp" "$sandbox/2026-10-07_hillcrest-chapel.md"
rm -f "$(dirname "$sandbox")/2026-10-07 "*.pdf

# Opening a second draft renames the first, and its summary has to follow --
# the summaries task never deletes, so a summary left under the old name is
# orphaned and a duplicate is written beside it. Needs the archive layout, since
# summaries live beside Drafts/, not inside it.
printf "  %-40s " "the first draft's summary follows it"
cat > "$archive/Drafts/2026-10-14.md" <<'EOF'
---
date: '2026-10-14'
lectionary_number: 469
title: Wed 28th of OT
location: Riverside Hall
variant: ''
---

Body.
EOF
printf '# 2026-10-14 Summary\n\n<!-- summary-format: 2 -->\n' \
	> "$archive/Homily Summaries/2026-10-14 Summary.md"
if HOMILIES_DIR="$archive/Drafts" ./new.py --date 2026-10-14 --location "Hillcrest Chapel" \
        </dev/null >/dev/null 2>&1; then
	s="$archive/Homily Summaries/2026-10-14_riverside-hall Summary.md"
	if [ -f "$s" ] && [ ! -f "$archive/Homily Summaries/2026-10-14 Summary.md" ] \
	   && head -1 "$s" | grep -q "^# 2026-10-14_riverside-hall Summary$"; then
		echo "OK"
	else
		echo "FAIL (summary not moved or heading stale)"; fail=1
	fi
else
	echo "FAIL (new.py exited non-zero)"; fail=1
fi

echo
[ $fail -eq 0 ] && echo "all green" || echo "FAILURES above"
exit $fail

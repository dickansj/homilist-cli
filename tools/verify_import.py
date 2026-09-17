#!/bin/sh
''''exec "$(dirname "$0")/../env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env

"""Check every imported draft against the .docx it came from.

    tools/verify_import.py [--verbose]

An import is a bulk edit of an archive, so it needs to be auditable rather than
trusted. Every check here re-derives the answer from the source document and
compares, rather than inspecting the draft alone -- a draft that agrees with
itself proves nothing.

What is checked:

  * the recorded source still exists, and no two drafts claim the same one
  * the body text round-trips: same words, in the same order, as the .docx
  * the date agrees with the date printed in the document, where there is one
    -- and, separately, whether the document agrees with *itself*
  * the weekday matches the liturgical day named in the draft -- a homily whose
    day says "Sunday" must fall on a Sunday
  * the lectionary number agrees with the filename
  * fields hold the kind of value they are for: a location is not a citation, a
    liturgical day is not a paragraph of prose
  * the header did not swallow the homily's opening lines

That last one exists because the round-trip above cannot see it: it compares the
draft with split_header()'s own output, so a header that eats body text loses the
same words on both sides. It is measured instead -- how many words the header
took, and whether any header line reads as a sentence.
"""

import argparse
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import homilist  # noqa: E402
import import_docx as imp  # noqa: E402

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tues": 1, "tue": 1, "wed": 2, "thurs": 3, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

problems = []
notes = []


def problem(name, message):
    problems.append(f"  ❌ {name}: {message}")


def note(name, message):
    notes.append(f"  ⚠️  {name}: {message}")


def words(text):
    """Comparable word sequence: punctuation and whitespace differences ignored."""
    return re.findall(r"\w+", text.lower())


CHECKED = "_checked.txt"


def reviewed_sources(drafts_dir):
    """Sources already scanned by eye. Reading a table is the slow step, so the
    next one should show only what has changed since."""
    path = os.path.join(drafts_dir, CHECKED)
    if not os.path.exists(path):
        return set()
    return {line.strip() for line in open(path, encoding="utf-8")
            if line.strip() and not line.startswith("#")}


def mark_checked():
    drafts_dir = homilist.homilies_dir()
    seen = reviewed_sources(drafts_dir)
    added = []
    for _, path in homilist.homily_files(drafts_dir):
        try:
            meta, _ = homilist.split_frontmatter(open(path, encoding="utf-8").read())
        except homilist.FrontmatterError:
            continue
        source = str(meta.get("source", "")).strip()
        if source and source not in seen:
            seen.add(source)
            added.append(source)
    target = os.path.join(drafts_dir, CHECKED)
    with open(target, "a", encoding="utf-8") as f:
        if not os.path.exists(target) or os.path.getsize(target) == 0:
            f.write("# Sources reviewed by eye. verify_import.py --table --new\n"
                    "# lists only what is missing from here.\n\n")
        f.write("\n".join(sorted(added)) + ("\n" if added else ""))
    print(f"marked {len(added)} newly reviewed ({len(seen)} total)")
    return 0


def write_table(path, new_only=False, rite=None, sort="date"):
    """Every draft's metadata as one markdown table, for reading by eye.

    The automated checks only catch what they were told to look for. A wrong
    location that looks like a location, or a day name that belongs to a
    different feast, passes every rule and is obvious to a human in a second.
    """
    drafts_dir = homilist.homilies_dir()
    overrides = imp.date_overrides(drafts_dir)
    field_overrides = imp.metadata_overrides(drafts_dir)
    reviewed = reviewed_sources(drafts_dir) if new_only else set()

    rows = []
    for name, file_path in homilist.homily_files(drafts_dir):
        try:
            meta, body = homilist.split_frontmatter(open(file_path, encoding="utf-8").read())
        except homilist.FrontmatterError:
            continue
        if new_only and str(meta.get("source", "")).strip() in reviewed:
            continue
        # The Roman rite is written two ways -- an empty field, or the word
        # itself -- so neither "eastern" nor "roman" can be a truthiness test.
        draft_rite = str(meta.get("rite", "")).strip()
        if rite == "eastern" and not homilist.is_eastern(draft_rite):
            continue
        if rite == "roman" and homilist.is_eastern(draft_rite):
            continue
        if rite not in (None, "eastern", "roman") \
                and draft_rite.lower() != rite.lower():
            continue
        rows.append((name, meta, body))

    if sort == "rite":
        # An empty rite *is* Roman, so it sorts under that name rather than
        # ahead of everything as the empty string.
        rows.sort(key=lambda r: (str(r[1].get("rite", "")).strip() or "Roman",
                                 str(r[1].get("date", ""))))
    else:
        rows.sort(key=lambda r: str(r[1].get("date", "")))

    def cell(value, limit=44):
        text = str(value or "").replace("|", "\\|").strip()
        if not text:
            return "—"
        return text if len(text) <= limit else text[: limit - 1] + "…"

    with open(path, "w", encoding="utf-8") as f:
        f.write("# Imported homily metadata\n\n")
        f.write(f"{len(rows)} drafts, "
                + ("grouped by rite, oldest first within each. "
                   if sort == "rite" else "oldest first. ")
                + "Flag anything that looks wrong.\n\n")
        if rite:
            f.write(f"Limited to **{rite}**"
                    + (" — Maronite and Chaldean.\n\n" if rite == "eastern"
                       else ".\n\n"))
        if new_only:
            f.write("Only drafts not yet listed in `_checked.txt`. Once you have "
                    "scanned these, run `--mark-checked` so the next table shows "
                    "only what is new.\n\n")
        f.write("`!` marks something already worth a look: a missing location, a "
                "corrected date, or a day name long enough to be prose.\n\n")
        f.write("| | date | rite | lect | liturgical day | USCCB day | occasion "
                "| variant | location | readings | words | source |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")

        for name, meta, body in rows:
            flags = []
            if not str(meta.get("location", "")).strip():
                flags.append("no location")
            if meta.get("source") in overrides:
                flags.append("date corrected")
            if len(str(meta.get("title", ""))) > 60:
                flags.append("long day")
            if not str(meta.get("preached", "")).strip():
                flags.append("no readings")

            f.write("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |\n".format(
                "!" if flags else "",
                cell(meta.get("date"), 12),
                cell(meta.get("rite"), 10) if meta.get("rite") else "",
                cell(meta.get("lectionary_number"), 6),
                cell(meta.get("title")),
                cell(meta.get("lectionary_string"), 30),
                cell(meta.get("occasion"), 30),
                cell(meta.get("variant"), 16),
                cell(meta.get("location"), 32),
                cell(meta.get("preached"), 36),
                len(body.split()),
                cell(meta.get("source"), 44),
            ))

        f.write("\n\n## Flagged\n\n")
        for name, meta, body in rows:
            bits = []
            if not str(meta.get("location", "")).strip():
                bits.append("no location")
            if meta.get("source") in overrides:
                bits.append(f"date corrected to {meta.get('date')}")
            if not str(meta.get("preached", "")).strip():
                bits.append("no readings")
            if bits:
                f.write(f"- **{name}** — {', '.join(bits)}  \n")
                f.write(f"  _{cell(meta.get('source'), 70)}_\n")

    print(f"wrote {path} ({len(rows)} drafts)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--table", metavar="FILE",
                    help="write every draft's metadata as a table, and stop")
    ap.add_argument("--new", action="store_true",
                    help="with --table, list only drafts not yet in _checked.txt")
    ap.add_argument("--sort", choices=("date", "rite"), default="date",
                    help="with --table, row order (default: date)")
    ap.add_argument("--rite", metavar="RITE", type=str.lower,
                    help="with --table, limit to one rite: 'eastern', 'roman', "
                         "or a name. Roman covers both an empty field and the "
                         "word itself")
    ap.add_argument("--mark-checked", action="store_true",
                    help="record every current draft's source as reviewed")
    args = ap.parse_args()
    if args.mark_checked:
        return mark_checked()
    if args.table:
        return write_table(args.table, new_only=args.new, rite=args.rite,
                           sort=args.sort)

    drafts_dir = homilist.homilies_dir()
    docx_dir = homilist.word_dir()

    overrides = imp.date_overrides(drafts_dir)
    field_overrides = imp.metadata_overrides(drafts_dir)
    drafts = homilist.homily_files(drafts_dir)
    print(f"checking {len(drafts)} drafts against {docx_dir}\n")

    seen_sources = {}
    checked = 0

    for name, path in drafts:
        try:
            meta, body = homilist.split_frontmatter(open(path, encoding="utf-8").read())
        except homilist.FrontmatterError as exc:
            problem(name, f"invalid frontmatter: {exc}")
            continue

        source = str(meta.get("source", "")).strip()
        if not source:
            note(name, "no source recorded (hand-written, not imported?)")
            continue

        source_path = os.path.join(docx_dir, source)
        if not os.path.exists(source_path):
            problem(name, f"source not found: {source}")
            continue

        if source in seen_sources:
            problem(name, f"same source as {seen_sources[source]}: {source}")
        seen_sources[source] = name

        checked += 1

        # --- body round-trip ------------------------------------------------
        try:
            paras = imp.paragraphs(source_path)
        except Exception as exc:  # noqa: BLE001
            problem(name, f"cannot re-read source: {exc}")
            continue
        header_lines, source_body = imp.split_header(paras)
        expected = words("\n\n".join(md for _, md in source_body))
        actual = words(body)
        if expected != actual:
            missing = len(expected) - len(actual)
            if missing > 0:
                problem(name, f"body is missing {missing} words vs the .docx")
            elif missing < 0:
                problem(name, f"body has {-missing} words the .docx does not")
            else:
                problem(name, "body words differ from the .docx (same count)")

        # --- did the header eat the homily? ---------------------------------
        # The round-trip above compares the draft with split_header()'s own
        # output, so a header that swallows body text is invisible to it: both
        # sides lose the same words. These two checks do not go through that
        # function's judgement, they measure the result.
        header_words = words(" ".join(header_lines))
        # A note, not a problem: no rule can reliably tell a rubric ("Where
        # needed can use Votive Mass 10") from a homily's opening line. The
        # check exists to put the long ones in front of a person.
        if len(header_words) > 30:
            note(name, f"the header consumed {len(header_words)} words — "
                          f"more than any real header in this archive; the "
                          f"opening of the homily may be in it: "
                          f"{header_lines[-1][:60]!r}")
        for line in header_lines[1:]:
            stripped = line.strip()
            if (stripped.endswith((".", ",", "!", "?", ";"))
                    and not imp.parse_date(stripped)
                    and not imp.CITATION.search(stripped)):
                note(name, f"header line reads like a sentence: {stripped[:60]!r}")

        # --- header-derived fields -----------------------------------------
        header = imp.interpret_header(header_lines,
                                      ignore_names=imp.presider_names())

        recorded = str(meta.get("date", "")).strip()
        if header["date"] and recorded != header["date"].isoformat():
            # A deliberate correction is not a discrepancy. Overrides exist
            # because some documents disagree with themselves.
            expected = overrides.get(source)
            if expected and recorded == expected.isoformat():
                note(name, f"date corrected to {recorded} "
                           f"(document says {header['date'].isoformat()}) "
                           f"— per _date-overrides.txt")
            else:
                problem(name, f"date {recorded} but the document says "
                              f"{header['date'].isoformat()}")

        # `preached` is normalized to SBL on import, so compare like with like.
        if header["readings"]:
            expected = homilist.normalize_citations(
                imp.tidy_readings(header["readings"]))
            actual = str(meta.get("preached", "")).strip()
            if actual and actual != expected and actual != header["readings"]:
                overridden = (source in field_overrides
                              and "preached" in field_overrides[source])
                if not overridden:
                    problem(name, f"preached {actual!r} does not match the "
                                  f"document's citation line {expected!r}")

        # --- weekday vs liturgical day --------------------------------------
        day = str(meta.get("title", ""))
        if recorded:
            try:
                actual_date = datetime.date.fromisoformat(recorded)
            except ValueError:
                problem(name, f"date {recorded!r} is not a real date")
                actual_date = None
            if actual_date:
                for word, index in WEEKDAYS.items():
                    if re.search(rf"\b{word}\b", day, re.I):
                        if actual_date.weekday() != index:
                            # Offer the nearest date with the named weekday. The
                            # direction is not always the same, so it is computed
                            # rather than assumed.
                            shift = (index - actual_date.weekday())
                            if shift > 3:
                                shift -= 7
                            elif shift < -3:
                                shift += 7
                            suggested = actual_date + datetime.timedelta(days=shift)
                            problem(
                                name,
                                f"the document says \"{word.title()}\" but its "
                                f"printed date {recorded} is a "
                                f"{actual_date.strftime('%A')}"
                                f"  →  {suggested.isoformat()} "
                                f"({suggested.strftime('%A')}) matches the day"
                            )
                        break

        # --- lectionary number vs filename ----------------------------------
        from_name = imp.lectionary_from_name(source)
        recorded_lect = str(meta.get("lectionary_number", "")).strip()
        if meta.get("rite"):
            if recorded_lect:
                problem(name, f"rite is {meta['rite']} but a lectionary "
                              f"number {recorded_lect} is set")
        elif from_name and recorded_lect != str(from_name):
            problem(name, f"lectionary {recorded_lect or '(empty)'} but the "
                          f"filename says {from_name}")

        # --- field plausibility ---------------------------------------------
        location = str(meta.get("location", "")).strip()
        clock = re.compile(r"\d{1,2}:\d{2}\s*(?:am|pm)?", re.I)
        if location and imp.CITATION.search(clock.sub("", location)):
            problem(name, f"location looks like a citation: {location!r}")
        if location and len(location) > 45:
            note(name, f"location is unusually long: {location[:45]!r}…")

        if len(day) > 90:
            problem(name, f"title looks like prose, not a day: {day[:50]!r}…")

        rite = str(meta.get("rite", "")).strip()
        if rite and rite not in ("Maronite", "Chaldean", "Roman"):
            problem(name, f"unexpected rite {rite!r}")

        if args.verbose:
            print(f"  ✓ {name}  ←  {source}")

    print(f"\n{checked} drafts verified against their sources")
    if notes:
        print(f"\n{len(notes)} things to look at:")
        print("\n".join(notes))
    if problems:
        print(f"\n{len(problems)} PROBLEMS:")
        print("\n".join(problems))
        return 1
    print("no problems found")
    return 0


if __name__ == "__main__":
    sys.exit(main())

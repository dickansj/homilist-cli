#!/bin/sh
''''exec "$(dirname "$0")/../env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env

"""Fill in the `preached` citation line where the import found none.

    tools/readings.py --report readings.txt   # worksheet, with evidence
    # ...confirm or correct each line...
    tools/readings.py --apply readings.txt    # write them back

It **proposes nothing from memory.** A proposal comes from the lectionary table
(`tools/fetch_lectionary.py`), or where a number is not in it, from citations
found in the homily's own summary -- shown with their source, so a wrong one is
visible rather than plausible.

How many sets a number maps to depends on the season, which is why the year is
printed alongside:

  * Ordinary Time weekdays -- two sets. Same Gospel, but the first reading is
    Year I in odd liturgical years and Year II in even ones.
  * Lent, Easter, Advent and Christmas weekdays -- one set, the same every year.
    (Lect 280 appears twice in this archive, in 2025 and 2026, with identical
    readings.)
  * Sundays -- one set: the number is already cycle-specific, so 22 *is* the
    first Sunday of Lent in Year A.
"""

import argparse
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import homilist  # noqa: E402
import liturgical  # noqa: E402
import lectionary  # noqa: E402
import import_docx as imp  # noqa: E402


def summaries_dir():
    return os.path.join(
        os.path.dirname(homilist.homilies_dir().rstrip("/")), "Homily Summaries")


def summary_for(source):
    """The summary file written alongside a .docx, if there is one."""
    if not source:
        return None
    stem = os.path.splitext(source)[0]
    path = os.path.join(summaries_dir(), f"{stem} Summary.md")
    return path if os.path.exists(path) else None


# Book, chapter, and the verse list -- ranges, commas, and the a/b half-verse
# suffixes the lectionary uses. Deliberately stops before any parenthetical.
REFERENCE = re.compile(
    r"(?:[123]\s+)?[A-Z][A-Za-z]{1,11}\.?"          # book
    r"\s+\d{1,3}"                                    # chapter
    r"(?::\s*\d{1,3}[a-c]?"                          # :verse
    r"(?:\s*[-–—]\s*\d{1,3}(?::\d{1,3})?[a-c]?)?"   # -range
    r"(?:\s*,\s*\d{1,3}[a-c]?(?:\s*[-–—]\s*\d{1,3}[a-c]?)?)*"  # , more
    r")?")


def citations(text):
    """Scripture citations in order of first appearance, de-duplicated.

    Uses the same book-name-checked matcher as the importer, so "St. Anne
    7:00 pm" is not read as a citation.
    """
    out = []
    for match in imp.CITATION.finditer(text or ""):
        # Take the reference and *only* the reference. A fixed-width slice of
        # the following text drags in the summary's parenthetical gloss and
        # truncates it mid-word, which reads like a citation and is not one.
        tail = text[match.start():]
        span = re.match(REFERENCE, tail)
        if not span:
            continue
        cite = homilist.normalize_citations(span.group(0).strip(" .,–—/"))
        if cite and cite not in out:
            out.append(cite)
    return out


# Bullets in the Readings section that are commentary rather than a reading.
SUMMARY_NOISE = re.compile(
    r"(?:alleluia|context|liturgical season|weekday of|not specified|memorial|"
    r"month of|solemnity|feast of)\b", re.I)


def reading_lines(summary_path):
    """The bullets under '## Readings & Feast', where the summary has one."""
    if not summary_path:
        return []
    text = open(summary_path, encoding="utf-8").read()
    block = re.search(r"##\s*Readings?[^\n]*\n(.*?)(?=\n##|\Z)", text, re.S)
    if not block:
        return []
    lines = [line.strip("- ").strip()
             for line in block.group(1).splitlines() if line.strip().startswith("-")]
    return [x for x in lines if not SUMMARY_NOISE.match(x)]


def year_cycle(date):
    """(Sunday cycle, weekday cycle) for a date."""
    liturgical_year = date.year + (1 if date >= liturgical.advent_start(date.year) else 0)
    return liturgical.cycle(date), "I" if liturgical_year % 2 else "II"


def gather():
    """Every draft with no `preached`, with the evidence for what it should be."""
    out = []
    for name, path in homilist.homily_files(homilist.homilies_dir()):
        try:
            meta, body = homilist.split_frontmatter(open(path, encoding="utf-8").read())
        except homilist.FrontmatterError:
            continue
        if str(meta.get("preached", "")).strip():
            continue
        source = str(meta.get("source", "")).strip()
        summary = summary_for(source)
        from_table, alternates = "", []
        lect = str(meta.get("lectionary_number", "")).strip()
        date = str(meta.get("date", "")).strip()
        if lect and date and not meta.get("rite"):
            try:
                d = datetime.date.fromisoformat(date)
                _sunday, weekday = year_cycle(d)
                from_table = lectionary.preached_line(lect, weekday)
                entry = lectionary.readings_for(lect, weekday) or {}
                alternates = entry.get("alternates", [])
            except ValueError:
                pass
        out.append({
            "name": name, "meta": meta, "source": source,
            "from_table": from_table, "alternates": alternates,
            "summary_readings": reading_lines(summary),
            "summary_cites": [c for line in reading_lines(summary)
                              for c in citations(line)],
            "body_cites": citations(body)[:6],
            "has_summary": bool(summary),
        })
    return out


def write_report(path):
    rows = gather()
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Readings\n#\n")
        f.write("# Every citation below was found in the homily's own summary or\n")
        f.write("# in its text. Nothing here is recalled from a lectionary -- if a\n")
        f.write("# line is blank, neither source named a reading.\n#\n")
        f.write("# Confirm or correct the value after the colon. Blank = skip.\n")
        f.write("# A single -  clears. Then:\n")
        f.write(f"#     tools/readings.py --apply {os.path.basename(path)}\n#\n")
        f.write("# OT weekdays have two first readings (Year I odd / Year II even)\n")
        f.write("# and one Gospel; Lent, Easter, Advent and Christmas weekdays have\n")
        f.write("# one set; a Sunday number is already cycle-specific.\n\n")

        for row in sorted(rows, key=lambda r: str(r["meta"].get("date", ""))):
            meta = row["meta"]
            date = str(meta.get("date", ""))
            bits = [date]
            if meta.get("rite"):
                bits.append(str(meta["rite"]))
            if meta.get("lectionary_number"):
                bits.append(f"lect {meta['lectionary_number']}")
            if meta.get("title"):
                bits.append(str(meta["title"]))
            if date and not meta.get("rite"):
                try:
                    sunday, weekday = year_cycle(datetime.date.fromisoformat(date))
                    bits.append(f"Year {sunday}/{weekday}")
                except ValueError:
                    pass
            f.write(f"# {'  ·  '.join(bits)}\n")
            if meta.get("occasion"):
                f.write(f"#   occasion: {meta['occasion']}\n")
            if row["summary_readings"]:
                for line in row["summary_readings"]:
                    f.write(f"#   summary says: {line}\n")
            elif not row["has_summary"]:
                f.write("#   (no summary file)\n")
            else:
                f.write("#   (summary names no readings)\n")
            if row.get("from_table"):
                f.write(f"#   lectionary table: {row['from_table']}\n")
                for alt in row.get("alternates", []):
                    f.write(f"#   optional alternate: {alt}\n")
            if row["body_cites"]:
                f.write(f"#   cited in the homily: {', '.join(row['body_cites'])}\n")
            else:
                f.write("#   (no citation in the homily text)\n")
            proposed = row.get("from_table") or "; ".join(row["summary_cites"]) or ""
            f.write(f"{row['name'][:-3]}: {proposed}\n\n")

    named = sum(1 for r in rows if r["summary_cites"])
    print(f"wrote {path}")
    print(f"  {len(rows)} without readings; {named} have a citation in their summary")
    return 0


def apply_report(path):
    if not os.path.exists(path):
        sys.exit(f"no such file: {path}")
    answers = {}
    for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            sys.exit(f"{path}:{lineno}: expected 'draft-name: citations'")
        key, value = stripped.split(":", 1)
        value = value.strip()
        if value == "-":
            answers[key.strip()] = ""
        elif value:
            answers[key.strip()] = value

    if not answers:
        print("nothing filled in; no changes made")
        return 0

    directory = homilist.homilies_dir()
    changed, missing, recorded = 0, [], []
    for key, value in sorted(answers.items()):
        target = os.path.join(directory, f"{key}.md")
        if not os.path.exists(target):
            missing.append(key)
            continue
        meta, body = homilist.split_frontmatter(open(target, encoding="utf-8").read())
        value = homilist.normalize_citations(value)
        if str(meta.get("preached", "")).strip() == value:
            continue
        meta["preached"] = value
        with open(target, "w", encoding="utf-8") as f:
            f.write(homilist.format_frontmatter(meta))
            f.write(body.rstrip() + "\n")
        print(f"  {key}: {value or '(cleared)'}")
        changed += 1
        source = str(meta.get("source", "")).strip()
        if source:
            recorded.append((source, value))

    # An imported draft is regenerated from its .docx on the next import, so the
    # answer has to be recorded against the source as well or it is lost.
    if recorded:
        overrides = os.path.join(directory, "_metadata-overrides.txt")
        existing = open(overrides, encoding="utf-8").read() if os.path.exists(overrides) else ""
        lines = [f"{s} | preached = {v}" for s, v in recorded
                 if f"{s} | preached = {v}" not in existing]
        if lines:
            with open(overrides, "a", encoding="utf-8") as f:
                f.write("\n# Added by tools/readings.py --apply\n")
                f.write("\n".join(lines) + "\n")
            print(f"  recorded {len(lines)} in {os.path.basename(overrides)}, "
                  "so a re-import keeps them")

    print(f"\n{changed} updated")
    for key in missing:
        print(f"  no such draft: {key}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--report", metavar="FILE", help="write a worksheet")
    group.add_argument("--apply", metavar="FILE", help="read a filled worksheet back")
    args = ap.parse_args()
    return write_report(args.report) if args.report else apply_report(args.apply)


if __name__ == "__main__":
    sys.exit(main())

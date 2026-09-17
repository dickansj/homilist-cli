#!/bin/sh
''''exec "$(dirname "$0")/../env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env

"""Fill in the `location` field across drafts, in bulk.

    tools/locations.py --report locations.txt   # write a worksheet
    # ...fill in the blanks...
    tools/locations.py --apply locations.txt    # write them back

Importing an archive leaves gaps: not every homily's text named where it was
preached, and a few parenthetical asides were filed as locations when they were
really a Gospel theme. Rather than opening 27 files by hand, this writes one
worksheet with enough context to answer from memory, and reads it back.

The worksheet is plain `key: value`. Everything else is a comment.
"""

import argparse
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import homilist  # noqa: E402

# A location that is probably something else that got parsed into the field.
SUSPICIOUS = re.compile(r"\d|:|^(?:the|a)\b", re.I)


def load_drafts():
    directory = homilist.homilies_dir()
    out = []
    for name, path in homilist.homily_files(directory):
        try:
            meta, body = homilist.split_frontmatter(open(path, encoding="utf-8").read())
        except homilist.FrontmatterError:
            continue
        out.append((name, path, meta, body))
    return out


def location_counts(drafts):
    counts = {}
    for _, _, meta, _ in drafts:
        value = str(meta.get("location", "")).strip()
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def known_locations(counts):
    """Values used more than once -- the real venues, worth offering as a menu."""
    return sorted((k for k, n in counts.items() if n > 1),
                  key=lambda k: (-counts[k], k))


def write_report(path):
    drafts = load_drafts()
    counts = location_counts(drafts)
    known = known_locations(counts)

    # A value used once across the whole archive is either a genuine one-off venue
    # or something that was never a location -- a Gospel theme, a subtitle. Both
    # are worth an eyeball, and there are few enough to check by hand.
    missing, suspect = [], []
    for name, _, meta, body in drafts:
        value = str(meta.get("location", "")).strip()
        if not value:
            missing.append((name, meta, body))
        elif SUSPICIOUS.search(value) or counts.get(value, 0) == 1:
            suspect.append((name, meta, body))

    def context(meta, body):
        bits = []
        # The weekday is not in the draft's name and often decides the answer:
        # a Sunday is a parish Mass, a weekday is a chapel or a school.
        date = str(meta.get("date", "")).strip()
        if date:
            try:
                bits.append(datetime.date.fromisoformat(date).strftime("%a %-d %b %Y"))
            except ValueError:
                bits.append(date)
        if meta.get("rite"):
            bits.append(str(meta["rite"]))
        if meta.get("lectionary_number"):
            bits.append(f"Homily {meta['lectionary_number']}")
        if meta.get("title"):
            bits.append(str(meta["title"]))
        if meta.get("occasion"):
            bits.append(str(meta["occasion"]))
        if meta.get("preached"):
            bits.append(str(meta["preached"]))
        opening = " ".join(body.split())[:80]
        if opening:
            bits.append(f"“{opening}…”")
        return "  ·  ".join(bits)

    with open(path, "w", encoding="utf-8") as f:
        f.write("# Locations\n#\n")
        f.write("# Type a location after the colon. Leave it blank to skip, so a\n")
        f.write("# half-filled worksheet is safe to apply. Write a single -\n")
        f.write("# to CLEAR a value that was wrong. Then:\n")
        f.write(f"#     tools/locations.py --apply {os.path.basename(path)}\n#\n")
        if known:
            f.write("# Used more than once (likely the real venues):\n")
            for value in known:
                f.write(f"#     {value}\n")
        f.write("\n")

        if missing:
            f.write(f"\n# ---------- empty ({len(missing)}) ----------\n\n")
            for name, meta, body in missing:
                f.write(f"# {context(meta, body)}\n")
                f.write(f"{name[:-3]}: \n\n")

        if suspect:
            f.write(f"\n# ---------- check these ({len(suspect)}) ----------\n")
            f.write("# Either used only once in the whole archive, or shaped oddly\n")
            f.write("# for a place name. A one-off venue is fine — just confirm it.\n")
            f.write("# A one-off venue is fine — leave it. Replace a wrong one, or\n")
            f.write("# write a single -  to clear it.\n\n")
            for name, meta, body in suspect:
                f.write(f"# {context(meta, body)}\n")
                f.write(f"# currently: {meta.get('location', '')}\n")
                f.write(f"{name[:-3]}: {meta.get('location', '')}\n\n")

    print(f"wrote {path}")
    print(f"  {len(missing)} empty, {len(suspect)} to check")
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
            sys.exit(f"{path}:{lineno}: expected 'draft-name: location'")
        key, value = stripped.split(":", 1)
        value = value.strip()
        # Blank means "leave this one alone", so a half-filled worksheet is safe
        # to apply. Clearing a wrong value therefore needs to be explicit, or the
        # two meanings collide -- deleting the text did nothing, silently.
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
        try:
            meta, body = homilist.split_frontmatter(open(target, encoding="utf-8").read())
        except homilist.FrontmatterError as exc:
            print(f"⚠️ {key}: invalid frontmatter, skipped ({exc})")
            continue
        if str(meta.get("location", "")).strip() == value:
            continue
        before = meta.get("location", "")
        meta["location"] = value
        with open(target, "w", encoding="utf-8") as f:
            f.write(homilist.format_frontmatter(meta))
            f.write(body.rstrip() + "\n")
        print(f"  {key}: {before or '(empty)'} → {value or '(cleared)'}")
        changed += 1
        # An imported draft is regenerated from its .docx on the next import, so
        # writing the answer into the draft alone would lose it. Record it against
        # the source document as well.
        source = str(meta.get("source", "")).strip()
        if source:
            recorded.append((source, value))

    if recorded:
        path = os.path.join(directory, "_metadata-overrides.txt")
        existing = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        lines = []
        for source, value in recorded:
            line = f"{source} | location = {value}"
            if line not in existing:
                lines.append(line)
        if lines:
            with open(path, "a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write("\n# Added by tools/locations.py --apply\n")
                f.write("\n".join(lines) + "\n")
            print(f"  recorded {len(lines)} in {os.path.basename(path)}, "
                  "so a re-import keeps them")

    print(f"\n{changed} updated")
    if missing:
        print(f"{len(missing)} named a draft that does not exist:")
        for key in missing:
            print(f"  {key}")
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

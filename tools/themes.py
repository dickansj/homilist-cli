#!/bin/sh
''''exec "$(dirname "$0")/../env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env

"""Write Drafts/_themes.md: one line per homily, themes and images included.

    tools/themes.py [--out FILE]

Answers one question -- "have I preached this before?" -- in a single file read.
The alternative is opening a dozen drafts and their summaries to find out whether
an image has already been used, which is slow enough that it does not get done.

Each row is the draft's frontmatter followed by two columns lifted from its
summary: the Core Themes bullets, verbatim, and the proper nouns, quotations and
titles from the Preaching Notes -- the things that would read as a repeat if they
turned up in a second homily.

Nothing here interprets a homily. The themes are copied as written; the images
are pattern-matched. Both are deliberately mechanical, so that running this twice
produces the same file and a row can be trusted to say what the summary says.
"""

import argparse
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import homilist  # noqa: E402

OUT_NAME = "_themes.md"
# `variant` earns its place beside the occasion: without it a pair of drafts --
# "With Baptisms" and "Without" -- differ in no column but their themes, and read
# as one row printed twice.
COLUMNS = ["date", "rite", "title", "occasion", "variant", "location", "lect",
           "preached", "themes", "images"]
BLANK = "—"


def section(text, heading):
    """The lines under one `## heading`, up to the next heading of any level."""
    out = []
    wanted = False
    for line in text.splitlines():
        if line.startswith("#"):
            wanted = line.strip().lower() == f"## {heading}".lower()
            continue
        if wanted:
            out.append(line)
    return "\n".join(out).strip()


def bullets(text):
    """The `- ` items in a block, each on one line.

    A bullet wrapped over several lines is joined back up, because the column
    holds one item per bullet and a hard-wrapped summary must not turn into two.
    """
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            items.append(stripped[2:].strip())
        elif stripped and items:
            items[-1] += " " + stripped
    return [i for i in items if i]


# Words that open a sentence in these summaries without naming anything: the
# narration verbs the summariser writes in ("References a phrase from...",
# "Preached at...", "Quotes St. Ignatius"). They are capitalised only by
# position, so nothing in the shape of the text distinguishes them from a real
# name -- "Joanne drove the parish bus" looks identical -- and only a list can.
# A word missing from here costs a noisy cell; a name added here costs a lost
# image, so the list stays short and stops at what actually appears.
NARRATION = {
    "addressed", "adds", "also", "announces", "applies", "asks", "begins",
    "builds", "calls", "cites", "closes", "closing", "compares", "concludes",
    "connects", "contains", "delivered", "describes", "directly", "draws",
    "echoes", "ends", "explains", "explicitly", "first", "frames", "gives",
    "highlights", "holds", "identifies", "includes", "introductory", "invites",
    "keeps", "links", "marks", "mentions", "names", "notes", "offers", "opens",
    "personal", "points", "preached", "preacher", "presents", "previews",
    "provides", "quotes", "reads", "recalls", "recounts", "refers",
    "references", "repeats", "retells", "returns", "reuses", "set", "sets",
    "shares", "speaks", "story", "suggests", "takes", "tells", "the", "this",
    "ties", "uses", "weaves",
}
# Capitalised in every homily ever written, so their presence in a row says
# nothing about whether this homily has been preached before.
UBIQUITOUS = {
    "god", "jesus", "christ", "lord", "gospel", "mass", "scripture", "father",
    "son", "holy spirit", "church", "sunday", "advent", "lent", "easter",
    "christmas", "ordinary time",
}

_NAME = (r"(?:St\.|Sts\.|Fr\.|Msgr\.|Bl\.|Ven\.|Dr\.|U\.S\.|"
         r"[A-Z][A-Za-z'’‐-―]+)")
_JOINER = r"(?:of|the|de|del|della|van|von|di|da|la|le|and)"
# A run of capitalised words, allowing the small joining words a name keeps
# inside it -- "Our Lady of the Rosary", "John of the Cross".
PROPER = re.compile(rf"\b{_NAME}(?:\s+(?:{_JOINER}\s+)?(?:{_NAME}|\d{{1,4}}))*")
# Quoted matter: a hymn title, a line someone said, a phrase worth reusing.
QUOTED = re.compile(r"[\"“]([^\"“”]{2,120})[\"”]")
# Emphasis, which in these summaries means the title of a book or document.
ITALIC = re.compile(r"(?<!\*)\*([^*\n]{2,80})\*(?!\*)|(?<![\w_])_([^_\n]{2,80})_(?![\w_])")


def images(notes):
    """Distinctive matter from a Preaching Notes block, in the order written.

    Crude on purpose, and over-inclusive where it has to choose: a spurious
    entry is read past in a second, while a missing one is the exact failure
    this file exists to prevent -- preaching the same story twice.
    """
    found = []

    def add(start, text):
        text = text.strip().strip(",;:.!?—-").strip()
        if text:
            found.append((start, text))

    for match in QUOTED.finditer(notes):
        add(match.start(), match.group(1))
    for match in ITALIC.finditer(notes):
        add(match.start(), match.group(1) or match.group(2))

    for match in PROPER.finditer(notes):
        words = match.group(0).split()
        # A narration verb only ever leads: "Quotes St. Ignatius's charge" is
        # one match, and dropping the verb keeps the saint.
        while words and words[0].lower().strip(".,'’") in NARRATION:
            words.pop(0)
        while words and words[-1].lower().strip(".,'’") in {"the", "of", "and"}:
            words.pop()
        if not words:
            continue
        phrase = " ".join(words)
        if phrase.lower().strip(".") in UBIQUITOUS:
            continue
        if len(phrase) < 3:
            continue
        add(match.start(), phrase)

    # Keep the longest form of anything said twice: the quoted "Yes, Jesus Loves
    # Me" and the bare "Jesus Loves Me" are one image, not two.
    found.sort(key=lambda pair: pair[0])
    kept = []
    for _, text in found:
        key = text.lower()
        if any(key in other.lower() for other in kept):
            continue
        kept = [k for k in kept if k.lower() not in key]
        kept.append(text)
    return kept


def cell(value):
    """One field, safe to put between pipes and on a single line."""
    text = str(value if value is not None else "").strip()
    text = text.replace("|", "\\|")
    text = re.sub(r"\s+", " ", text)
    return text or BLANK


def rows(drafts_dir, summaries):
    """(row dict, missing summary?) for every draft, oldest first."""
    out = []
    for name, path in homilist.homily_files(drafts_dir):
        try:
            meta, _ = homilist.split_frontmatter(open(path, encoding="utf-8").read())
        except (OSError, homilist.FrontmatterError) as exc:
            sys.stderr.write(f"skipped {name}: {exc}\n")
            continue

        summary_file = os.path.join(summaries, homilist.summary_name(name))
        themes, notes = [], []
        has_summary = os.path.isfile(summary_file)
        if has_summary:
            text = open(summary_file, encoding="utf-8").read()
            themes = bullets(section(text, "Core Themes"))
            notes = images(section(text, "Preaching Notes"))

        out.append({
            "name": name,
            "has_summary": has_summary,
            "date": str(meta.get("date", "")).strip(),
            # An empty rite is the Roman one. Writing it out costs a word and
            # saves the reader deciding what a blank column means.
            "rite": str(meta.get("rite", "")).strip() or "Roman",
            "title": meta.get("title", ""),
            "occasion": meta.get("occasion", ""),
            "variant": meta.get("variant", ""),
            "location": meta.get("location", ""),
            "lect": meta.get("lectionary_number", ""),
            "preached": meta.get("preached", ""),
            "themes": "; ".join(themes),
            "images": "; ".join(notes),
        })

    # Undated drafts sort last rather than first, where an empty string would
    # put them: they are the unfinished ones, not the oldest.
    out.sort(key=lambda r: (r["date"] or "9999-99-99", r["name"]))
    return out


def newest(paths):
    """The most recent mtime among the inputs, as a date and time.

    Stands in for a wall-clock stamp, which would make every run differ from the
    last and turn "is this current?" into a question the file cannot answer.
    This changes only when a draft or a summary does.
    """
    times = [os.path.getmtime(p) for p in paths if os.path.exists(p)]
    if not times:
        return "unknown"
    return datetime.datetime.fromtimestamp(max(times)).strftime("%Y-%m-%d %H:%M")


def write(path, drafts_dir, summaries_dir):
    table = rows(drafts_dir, summaries_dir)
    inputs = [os.path.join(drafts_dir, r["name"]) for r in table]
    inputs += [os.path.join(summaries_dir, n)
               for n in (os.listdir(summaries_dir)
                         if os.path.isdir(summaries_dir) else [])]
    unsummarised = [r["name"] for r in table if not r["has_summary"]]

    lines = []
    lines.append("# Homily themes\n")
    lines.append(f"{len(table)} homilies, oldest first. "
                 f"Newest draft or summary: {newest(inputs)}.\n")
    lines.append(
        "One line each, pipe-delimited, so the whole archive can be read at "
        "once: what a homily was about, and what it used to say it. `themes` "
        "is the summary's Core Themes verbatim; `images` is the proper nouns, "
        "quotations and titles from its Preaching Notes -- what would read as a "
        "repeat if it turned up again. Regenerate with `tools/themes.py`.\n")
    if unsummarised:
        lines.append(f"No summary yet ({len(unsummarised)}), so their themes "
                     "and images are blank:\n")
        for name in unsummarised:
            lines.append(f"- {name}")
        lines.append("")
    lines.append(" | ".join(COLUMNS))
    lines.append(" | ".join("---" for _ in COLUMNS))
    for row in table:
        lines.append(" | ".join(cell(row[column]) for column in COLUMNS))

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path} ({len(table)} homilies, "
          f"{len(unsummarised)} without a summary)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", metavar="FILE",
                    help=f"where to write (default: Drafts/{OUT_NAME})")
    args = ap.parse_args()

    drafts = homilist.homilies_dir()
    summaries = homilist.summaries_dir()
    if not os.path.isdir(summaries):
        sys.stderr.write(f"no summaries directory at {summaries}\n"
                         "themes and images will be blank for every homily.\n")
    return write(args.out or os.path.join(drafts, OUT_NAME), drafts, summaries)


if __name__ == "__main__":
    sys.exit(main())

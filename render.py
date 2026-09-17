#!/bin/sh
''''exec "$(dirname "$0")/env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env! :D

import re
import shutil
import subprocess
import sys
import os

import homilist

def siblings(filepath):
    """Metadata of the other drafts sharing this one's date."""
    directory = os.path.dirname(filepath) or "."
    try:
        meta, _ = homilist.split_frontmatter(open(filepath, encoding="utf-8").read())
    except (OSError, homilist.FrontmatterError):
        return []
    date = str(meta.get("date", "")).strip()
    if not date:
        return []
    out = []
    for name, path in homilist.homily_files(directory):
        if os.path.abspath(path) == os.path.abspath(filepath):
            continue
        try:
            other, _ = homilist.split_frontmatter(open(path, encoding="utf-8").read())
        except homilist.FrontmatterError:
            continue
        if str(other.get("date", "")).strip() == date:
            out.append(other)
    return out


def find_folder(fragment):
    """(path, candidates) for a --to argument.

    An explicit path is taken as given. Anything else is matched, case- and
    punctuation-insensitively, against the folders under the configured
    copy_roots -- so "Ashgrove" finds "Funerals/Ashgrove, Margaret Ellen
    MEMORIAL". An ambiguous fragment resolves to nothing and returns what it
    could have meant, because copying into the wrong person's folder is worse
    than being asked again.
    """
    if os.path.isdir(fragment):
        return os.path.abspath(fragment), []

    def key(text):
        return re.sub(r"[^a-z0-9]", "", text.lower())

    wanted = key(fragment)
    if not wanted:
        return None, []

    hits = []
    for root in homilist.copy_roots():
        for name in sorted(os.listdir(root)):
            full = os.path.join(root, name)
            if os.path.isdir(full) and not homilist.is_sidecar(name) \
                    and wanted in key(name):
                hits.append(full)
    if len(hits) == 1:
        return hits[0], []
    return None, hits


def copy_name(primary):
    """The name a per-occasion copy takes: the primary's, plus -homily.

    Matches the convention those folders already use for the other pieces of a
    liturgy -- "-sheet.pdf", "-intercessions.pdf" -- and keeps the homily from
    colliding with the presider script, which is often named identically.
    """
    stem, ext = os.path.splitext(os.path.basename(primary))
    return f"{stem}-homily{ext}"


def superseded(filepath, keep):
    """PDFs for this draft's date that no current draft would produce.

    A PDF carries no link back to its draft, so this works from the date: every
    draft sharing it is asked what it would be called now, and any PDF bearing
    that date outside the resulting set is left over from a name that changed.
    Adding a sibling is enough to do it -- the venue is only appended once a
    date carries more than one homily, so the first draft's PDF is renamed by
    the arrival of the second.
    """
    try:
        meta, _ = homilist.split_frontmatter(open(filepath, encoding="utf-8").read())
    except (OSError, homilist.FrontmatterError):
        return []
    date = str(meta.get("date", "")).strip()
    if not date:
        return []

    directory = os.path.dirname(filepath) or "."
    expected = {keep}
    for name, path in homilist.homily_files(directory):
        try:
            other, _ = homilist.split_frontmatter(open(path, encoding="utf-8").read())
        except homilist.FrontmatterError:
            continue
        if str(other.get("date", "")).strip() == date:
            expected.add(pdf_name(other, name[:-3], siblings(path)))

    out = []
    for name in sorted(os.listdir(homilist.pdf_dir())):
        if name.endswith(".pdf") and date in name and name not in expected:
            out.append(os.path.join(homilist.pdf_dir(), name))
    return out


def distinct(parts):
    """Join name parts, dropping any the name already says.

    Fields overlap more often than they should -- a variant typed as the venue,
    an occasion that names its church -- and each one is appended on its own
    merits, so the name came out as "Maple Court Maple Court". Compared word by word,
    so "St. Anne" is found inside "End of School St Anne" and a short venue
    is never found inside an unrelated longer word.
    """
    def words(text):
        return re.findall(r"[a-z0-9]+", text.lower())

    kept = []
    for part in parts:
        part = str(part).strip()
        if not part:
            continue
        have, want = words(" ".join(kept)), words(part)
        if want and any(have[i:i + len(want)] == want
                        for i in range(len(have) - len(want) + 1)):
            continue
        kept.append(part)
    return " ".join(kept).strip()


def pdf_name(meta, fallback, others=()):
    """The printed copy's filename, which depends on the rite.

    Roman (the default, `rite` empty):
        YYYY-MM-DD Homily NNN [suffix].pdf
    Date first so it sorts, then the lectionary number the existing .docx archive
    is filed by, then whatever distinguishes it from a sibling -- "Healing",
    "Maple Court", "with baptisms".

    Maronite or Chaldean:
        [Rite] [Title] YYYY-MM-DD.pdf
    These have no Roman lectionary number, so the liturgical day identifies them.
    Rite leads because they group together in a listing, and the date is omitted
    when unknown -- many are undated and must still produce a usable filename.

    Drafts keep YYYY-MM-DD.md regardless: the date is what makes a draft unique.
    """
    date = str(meta.get("date", "")).strip()
    rite = str(meta.get("rite", "")).strip()

    # What distinguishes this homily from its neighbours, shortest first. The
    # occasion and variant do that; the liturgical day mostly does not, because
    # the lectionary number already encodes it -- "Homily 239 Wed 3rd of Lent"
    # says the same thing twice and pushed some names past ninety characters.
    # So the day is only used where there is no number to stand in for it.
    number = str(meta.get("lectionary_number", "")).strip()
    occasion = str(meta.get("occasion", "")).strip()
    # The day is the fallback, not the first choice: it is used only where
    # neither a lectionary number nor an occasion already says which homily
    # this is. "Lazarus Miracles All Around Us House Prayer Service" needs no
    # help from "Fri 5th of Lent".
    fields = (("occasion", "variant") if (number or occasion)
              else ("title", "occasion", "variant"))
    suffix = distinct(str(meta.get(k, "")).strip() for k in fields)

    if rite and rite.lower() != "roman":
        # A non-Roman homily has no Roman lectionary number, so the liturgical day
        # is what identifies it. Rite first, because these group together in a
        # folder listing, then the date so each rite sorts chronologically within
        # its group -- the Roman copies sort that way and these should match.
        # The date is dropped when unknown; the name still has to work.
        title = (str(meta.get("title", "")).strip()
                 or str(meta.get("lectionary_string", "")).strip()
                 or suffix or "Homily")
        parts = [rite] + ([date] if date else []) + [title]
        name = " ".join(parts)
        name = re.sub(r"[/:]", "-", name)
        name = re.sub(r"\s+", " ", name).strip()
        return f"{name}.pdf"

    if not date:
        return f"{fallback}.pdf"

    # "Homily" reads as a label before a number. Without one it is just noise in
    # front of the occasion, so it is dropped.
    parts = [date] + (["Homily", number] if number else [])

    # Where a date carries more than one homily, every one of them names its
    # venue -- not only the pair that would otherwise collide. Reading a folder,
    # the useful question is "which of these was which", and answering it for
    # some siblings but not others makes the odd one out look like an oversight.
    location = str(meta.get("location", "")).strip()
    # Only the descriptive parts are compared with each other. The date and the
    # lectionary number are digits that coincide by accident -- Homily 22 on the
    # 22nd -- and must never be taken as a repeat.
    tail = distinct([suffix] + ([location] if location and others else []))
    if tail:
        parts.append(tail)
    name = " ".join(parts)
    name = re.sub(r"[/:]", "-", name)          # never break a path
    name = re.sub(r"\s+", " ", name).strip()
    return f"{name}.pdf"



def main(argv):
    """Render one draft. Everything below used to run at import time, so merely
    importing this module to reuse pdf_name() rendered a PDF as a side effect."""
    args = list(argv)

    destination = None
    for flag in ("--to", "-t"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.stderr.write(f"{flag} wants a folder or part of its name\n")
                return 1
            destination = args[i + 1]
            del args[i:i + 2]

    if not args:
        # No argument: render the most recent homily.
        files = homilist.homily_files(homilist.homilies_dir())
        if not files:
            sys.stderr.write("usage: render.py [file.md]\n")
            return 1
        filepath = files[-1][1]
    elif len(args) == 1:
        filepath = homilist.find_draft(args[0])
        if filepath is None:
            sys.stderr.write(f"no draft matching {args[0]!r}\n")
            near = [n for n, _ in homilist.homily_files(homilist.homilies_dir())
                    if args[0].rstrip(".md") in n]
            if near:
                sys.stderr.write("did you mean:\n")
                for n in near[:5]:
                    sys.stderr.write(f"  {n}\n")
            return 1
    else:
        sys.stderr.write("usage: render.py [draft]\n")
        return 1

    os.chdir(homilist.SCRIPT_DIR)

    # Check the frontmatter ourselves first, so a YAML mistake produces a message
    # that points at the offending line instead of a pandoc exit code.
    try:
        metadata, _ = homilist.split_frontmatter(open(filepath, encoding="utf-8").read())
    except homilist.FrontmatterError as exc:
        sys.stderr.write(f"Invalid YAML frontmatter in {os.path.basename(filepath)}:\n")
        sys.stderr.write("  " + str(exc).replace("\n", "\n  ") + "\n")
        sys.stderr.write("\nValues containing a colon need quotes: title: \"Martha: A Study\"\n")
        return 1

    base = os.path.splitext(os.path.basename(filepath))[0]
    fdir = os.path.dirname(filepath)

    # The Drafts folder holds markdown; the printed copies go to the archive
    # root beside Word/ and Homily Summaries/.
    outdir = homilist.pdf_dir()
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, pdf_name(metadata, base, siblings(filepath)))

    cmd = [
        "pandoc",
        "--from", "markdown",
        "--template", "./template.typ",
        "--to", "pdf",
        "--pdf-engine", "typst",
        "-o", outpath,
        filepath
    ]

    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"\npandoc/typst failed (exit {exc.returncode}) — see the error above.\n")
        return exc.returncode

    print(f"✅ {outpath}")

    # A rename leaves the old PDF behind, and two near-identical names in a
    # folder is worse than one wrong one -- you cannot tell which is current.
    for stale in superseded(filepath, os.path.basename(outpath)):
        os.remove(stale)
        print(f"   removed {os.path.basename(stale)} (superseded name)")

    if destination:
        folder, candidates = find_folder(destination)
        if folder is None:
            sys.stderr.write(f"\nno single folder matching {destination!r}\n")
            if candidates:
                sys.stderr.write("could be:\n")
                for c in candidates:
                    sys.stderr.write(f"  {c}\n")
            else:
                sys.stderr.write("looked under: "
                                 + (", ".join(homilist.copy_roots()) or "(no copy_roots configured)")
                                 + "\n")
            return 1
        target = os.path.join(folder, copy_name(outpath))
        shutil.copy2(outpath, target)
        print(f"   copied to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

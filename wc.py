#!/bin/sh
''''exec "$(dirname "$0")/env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env! :D

import datetime
import os
import re
import sys
import time

import homilist

watch = False
filepath = None

for arg in sys.argv[1:]:
    if arg == "--watch":
        watch = True
    elif filepath is None:
        filepath = arg
    else:
        sys.stderr.write("usage: wc.py [--watch] [file.md]\n")
        sys.exit(1)

if filepath is None:
    # No argument: the most recent homily.
    files = homilist.homily_files(homilist.homilies_dir())
    if not files:
        sys.stderr.write("usage: wc.py [--watch] [file.md]\n")
        sys.exit(1)
    filepath = files[-1][1]

found = homilist.find_draft(filepath)
if found is None:
    sys.stderr.write(f"no draft matching {filepath!r}\n")
    sys.exit(1)
filepath = found

# What a homily should come to depends on what kind of Mass it is for. The
# targets are the preacher's own, from config.toml -- these defaults are one
# preacher's numbers, not a rule -- and the kind is read from the frontmatter.
PACE = homilist.config().get("pace", {})
WPM = int(PACE.get("wpm", 135))
SUNDAY = [int(x) for x in PACE.get("sunday", (675, 945))]
DAILY_MAX = int(PACE.get("daily_max", 405))
NO_TARGET = re.compile(r"\b(funeral|wedding|memorial)s?\b", re.I)


def kind(meta):
    """(label, low, high) for this homily. Either bound may be None.

    Sunday is found from the date, not the title, because the title is typed
    and the date is not. A funeral or a wedding has no target: its length is
    the occasion's to decide. Eastern homilies run longer and are not held to
    the Roman numbers.
    """
    rite = str(meta.get("rite", "")).strip()
    if homilist.is_eastern(rite):
        return rite, None, None
    occasion = str(meta.get("occasion", "")).strip()
    if NO_TARGET.search(occasion):
        return occasion, None, None
    try:
        sunday = datetime.date.fromisoformat(str(meta.get("date", ""))).weekday() == 6
    except ValueError:
        sunday = str(meta.get("title", "")).lower().startswith("sun")
    if sunday:
        return "Sunday", SUNDAY[0], SUNDAY[1]
    return "Daily Mass", None, DAILY_MAX


def verdict(words, low, high):
    """One phrase: in range, or how far out and which way."""
    if low is not None and words < low:
        return f"under by {low - words} (target {low}–{high})"
    if high is not None and words > high:
        bound = f"{low}–{high}" if low is not None else f"under {high}"
        return f"over by {words - high} (target {bound})"
    if low is None and high is None:
        return "no target — these run their own length"
    bound = f"{low}–{high}" if low is not None else f"under {high}"
    return f"in range (target {bound})"


def report():
    if filepath is None:
        raise RuntimeError("can't report before filepath set")
    contents = open(filepath, encoding="utf-8").read()
    try:
        meta, text = homilist.split_frontmatter(contents)
    except homilist.FrontmatterError:
        # A word count shouldn't care about bad metadata -- strip and carry on.
        end = contents.find("\n---", 3)
        text = contents[end + 4 :] if end != -1 else contents
        meta = {}

    text = text.strip()
    wc = len(text.split())
    minutes, seconds = divmod(round(wc / WPM * 60), 60)
    label, low, high = kind(meta)

    print(f"{filepath}:")
    print(f"    {wc:,} words · {minutes}:{seconds:02} at {WPM} wpm")
    print(f"    {label}: {verdict(wc, low, high)}\n")


if not watch:
    report()
    sys.exit(0)


last_mtime = None

while True:
    try:
        mtime = os.path.getmtime(filepath)

        if mtime != last_mtime:
            last_mtime = mtime
            print("\033[2J\033[H", end="", flush=True)
            report()

        time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        break

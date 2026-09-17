#!/bin/sh
''''exec "$(dirname "$0")/env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env! :D

import sys

import homilist

# Blank in these is fine -- they're either scraped or genuinely optional.
REQUIRED = ["date", "location"]

directory = homilist.homilies_dir()
problems = 0

INDENT = "\n      "

for name, fullpath in homilist.homily_files(directory):
    try:
        metadata, body = homilist.split_frontmatter(open(fullpath, encoding="utf-8").read())
    except homilist.FrontmatterError as exc:
        # pandoc reads this same block as YAML, so it would fail to render too.
        print(f"❌ {name}: invalid YAML frontmatter — render.py will fail on this")
        print("      " + str(exc).replace("\n", INDENT))
        problems += 1
        continue

    if not metadata:
        print(f"⚠️ {name}: no frontmatter")
        problems += 1
        continue

    base = name.removesuffix(".md")
    if "_" in base:
        base = base.split("_")[0]
    if str(metadata.get("date", "")) != base:
        print(f"⚠️ {name}: metadata date {metadata.get('date', '')!r} does not match filename")
        problems += 1

    for key in REQUIRED:
        if not str(metadata.get(key, "")).strip():
            print(f"⚠️ {name}: {key} is empty")
            problems += 1

    unknown = [k for k in metadata if k not in homilist.FIELDS]
    if unknown:
        print(f"⚠️ {name}: unrecognized field(s): {', '.join(unknown)}")
        problems += 1

    if not body.strip():
        print(f"·  {name}: no text yet")

print(f"\n{directory}\n{problems} problem(s) found.")
sys.exit(1 if problems else 0)

#!/bin/sh
''''exec "$(dirname "$0")/env/bin/python" "$0" "$@" # '''
# lines above let this be executed as a script but run with the virtual env! :D

"""Put the whole corpus in one file, for grepping or for handing to something.

    ./concat.py            -> tmp/all.txt, in the repo, so a document manager
                              does not index a second copy of every homily
    ./concat.py -          -> stdout, to pipe into grep or a model
    ./concat.py PATH       -> that file, relative to where you are
"""

import os
import sys

import homilist

DIVIDER = "================================================"

if len(sys.argv) > 2:
    sys.stderr.write(__doc__)
    sys.exit(1)
target = sys.argv[1] if len(sys.argv) == 2 else None

outputs: list[str] = []
for name, fullpath in homilist.homily_files(homilist.homilies_dir()):
    contents = open(fullpath, encoding="utf-8").read()
    outputs.append(f"{DIVIDER}\n{name}\n{DIVIDER}\n\n{contents}")
corpus = "\n\n\n".join(outputs)

if target == "-":
    sys.stdout.write(corpus)
    # The receipt goes where the corpus does not, so a pipe stays clean.
    sys.stderr.write(f"✅ {len(outputs)} homilies\n")
    sys.exit(0)

outpath = (os.path.abspath(target) if target
           else os.path.join(homilist.tmp_dir(), "all.txt"))
os.makedirs(os.path.dirname(outpath), exist_ok=True)
with open(outpath, "w", encoding="utf-8") as outfile:
    outfile.write(corpus)
print(f"✅ {len(outputs)} homilies → {outpath}")

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Copies the page (deckbench/ui) into a folder of a website, to host it there.

    python tools/copy_to_site.py ../commitcollective.cc/public/deckbench/app

On commitcollective.cc a Cloudflare worker serves the page (docs/hosting.md), so this is for a preview in a local
copy of the site, or for another host. The hosted page asks for the address and the token of a bench, or runs its demo. It needs nothing else. Files that are not
in the page any more are removed from the destination, so it matches the source.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "..", "deckbench", "ui")


def main():
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(sys.argv) == 2 else 2
    dest = sys.argv[1]
    os.makedirs(dest, exist_ok=True)
    wanted = sorted(f for f in os.listdir(UI) if os.path.isfile(os.path.join(UI, f)))
    for name in wanted:
        shutil.copyfile(os.path.join(UI, name), os.path.join(dest, name))
    for name in os.listdir(dest):
        if name not in wanted and os.path.isfile(os.path.join(dest, name)):
            os.remove(os.path.join(dest, name))
    print("%d files in %s: %s" % (len(wanted), os.path.abspath(dest), ", ".join(wanted)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

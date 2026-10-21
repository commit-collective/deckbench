#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Turns the output of `python -m unittest` into GitHub annotations, one for each test that failed.

    python -m unittest discover -s tests 2>&1 | tee test-output.txt
    python tools/ci_report.py test-output.txt

A failed job's log is long and needs a sign-in to download. An annotation is on the job's page, at the top, and in the API. The
summary line (a notice) also names each test that failed and why, a line each, since a failure's own annotation shows only once
the page has loaded its scripts, and not to a program that reads the page.
"""
import re
import sys

RULE = "-" * 70


def escape(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        text = f.read()
    summary = re.search(r"^Ran \d+ tests? in [^\n]*\n\n(OK|FAILED[^\n]*)", text, re.M)
    blocks = re.split(r"^={70}\n", text, flags=re.M)[1:]
    names = []
    for block in blocks:
        head, _, body = block.partition("\n")
        body = body.split("\n" + RULE + "\nRan ")[0]
        body = body.replace(RULE + "\n", "", 1).strip()
        print("::error title=%s::%s" % (escape(head.strip()[:200]), escape(body[-1800:])))
        last = [line for line in body.splitlines() if line.strip()]
        names.append("%s -> %s" % (head.strip()[:90], (last[-1].strip() if last else "")[:160]))
    if not blocks:
        print("::error title=The tests did not finish::%s" % escape(text.strip()[-1800:]))
    if summary:
        line = summary.group(0).strip().replace("\n\n", " ")
        print("::notice title=Tests::%s" % escape(line + "\n" + "\n".join(names[:30])))


if __name__ == "__main__":
    main()

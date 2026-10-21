#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Turns the output of `python -m unittest` into GitHub annotations, one for each test that failed.

    python -m unittest discover -s tests 2>&1 | tee test-output.txt
    python tools/ci_report.py test-output.txt

A failed job's log is long and needs a sign-in to download. An annotation is on the job's page, at the top, and in the API.
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
    for block in blocks:
        head, _, body = block.partition("\n")
        body = body.split("\n" + RULE + "\nRan ")[0]
        body = body.replace(RULE + "\n", "", 1).strip()
        print("::error title=%s::%s" % (escape(head.strip()[:200]), escape(body[-1800:])))
    if not blocks:
        print("::error title=The tests did not finish::%s" % escape(text.strip()[-1800:]))
    if summary:
        print("::notice title=Tests::%s" % escape(summary.group(0).strip().replace("\n\n", " ")))


if __name__ == "__main__":
    main()

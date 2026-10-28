#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Takes the hero picture of deckbench: its page with four decks playing, a mixer and some events, for the README and the website.

    hero.py [--out PNG] [--width 1400] [--height 1000] [--browser PATH]

It starts a bench of its own (on shifted ports, so a bench or rekordbox that is running does not matter), puts it in a state worth
showing, and takes a screenshot of the page with a headless Chrome or Edge. By default the picture is written where the website
keeps it, `../commitcollective.cc/public/deckbench/hero.png`. Run it again after the page's look changes, then commit the picture
in the website's repository.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from deckbench.testing import Bench  # noqa: E402

SITE_HERO = os.path.join(ROOT, "..", "commitcollective.cc", "public", "deckbench", "hero.png")
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]


def find_browser(given):
    for name in ([given] if given else BROWSERS):
        path = name if os.path.isfile(name) else shutil.which(name)
        if path:
            return path
    sys.exit("no Chrome or Edge found: name one with --browser")


def stage(bench):
    """The decks and the mixer in a state that shows what the bench does."""
    post = bench.post
    for n in (1, 2, 3, 4):
        post("api/deck/%d/tempo/126" % n)
    post("api/mixer/channel/4/fader_start/1")
    for channel, level in ((1, 100), (2, 100), (3, 70)):
        post("api/mixer/channel/%d/fader/%d" % (channel, level))
    post("api/deck/2/loop/4")
    # a few events for the list: a channel is opened, closed and opened again
    time.sleep(0.5)
    post("api/mixer/channel/4/fader/80")
    time.sleep(1.2)
    post("api/mixer/channel/4/fader/0")
    time.sleep(1.0)
    post("api/mixer/channel/4/fader/80")
    time.sleep(1.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=SITE_HERO)
    ap.add_argument("--width", type=int, default=1400)
    ap.add_argument("--height", type=int, default=1060)
    ap.add_argument("--browser")
    args = ap.parse_args()
    browser = find_browser(args.browser)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    profile = tempfile.mkdtemp(prefix="deckbench-hero-")
    try:
        with Bench(numbers=[1, 2, 3, 4], on=True, init={1: "play", 2: "play,master", 3: "play,sync", 4: "play,sync"},
                   args=["--mixer"]) as bench:
            stage(bench)
            subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--user-data-dir=" + profile,
                            "--window-size=%d,%d" % (args.width, args.height), "--timeout=5000", "--screenshot=" + out,
                            bench.url + "#events"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if not os.path.isfile(out):
        sys.exit("the browser took no picture")
    print(out)


if __name__ == "__main__":
    main()

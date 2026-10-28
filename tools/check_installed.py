#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Check the installed package, without importing the source checkout.

    python -m pip install --no-deps .
    python -I tools/check_installed.py
"""
from pathlib import Path
import subprocess
import sys

import deckbench.adapters
import deckbench.cli
import deckbench


def main():
    root = Path(deckbench.__file__).parent
    for name in ("index.html", "app.js", "app.css"):
        if not (root / "ui" / name).is_file():
            raise RuntimeError("installed package is missing ui/" + name)
    if not (root / "examples").is_dir():
        raise RuntimeError("installed package is missing examples")
    subprocess.check_call([sys.executable, "-I", "-m", "deckbench", "--help"])
    print("installed CLI, adapters and browser assets are available")


if __name__ == "__main__":
    main()

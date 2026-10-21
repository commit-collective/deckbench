# SPDX-License-Identifier: MIT OR Apache-2.0
"""Drift checks: things that are written twice, one for people and one for the code, must still say the same.

Each fails with what disagrees, and the fix is made in the place that owns the fact: the code for the version, the routes and the options.
"""
import glob
import os
import re
import unittest

import deckbench

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class Version(unittest.TestCase):
    def test_the_version_is_written_once(self):
        project = read("pyproject.toml")
        self.assertIn('dynamic = ["version"]', project, "pyproject.toml must not write the version, it reads deckbench.__version__")
        self.assertIn('attr = "deckbench.__version__"', project)

    def test_the_changelog_has_an_entry_for_it(self):
        headings = re.findall(r"(?m)^## v(\S+)", read("CHANGELOG.md"))
        self.assertIn(deckbench.__version__, headings, "CHANGELOG.md has no '## v%s' entry (it has %s)" % (deckbench.__version__, headings))
        self.assertEqual(headings[0], deckbench.__version__, "the newest released entry of the CHANGELOG is not the version of the code")


class Documented(unittest.TestCase):
    def docs(self):
        return read("README.md") + "\n".join(open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(ROOT, "docs", "*.md"))))

    def test_every_api_route_is_in_the_readme(self):
        source = read("deckbench", "web.py")
        names = set(re.findall(r'"/api/([a-z_]+)', source)) | set(re.findall(r'\["api", "([a-z_]+)"', source)) | \
            set(re.findall(r'== \["api", "([a-z_]+)"', source))
        names |= set(re.findall(r'parts\[:\d\] == \["api", "([a-z_]+)"', source))
        self.assertTrue(names >= {"state", "deck", "events", "scenario", "stream"}, names)
        readme = read("README.md")
        missing = sorted(n for n in names if "/api/" + n not in readme)
        self.assertEqual(missing, [], "routes of web.py that the README's API section does not mention: %s" % missing)

    def test_every_command_line_option_is_documented(self):
        source = read("deckbench", "cli.py")
        options = sorted(set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', source)))
        self.assertGreater(len(options), 20)
        docs = self.docs()
        missing = [o for o in options if o not in docs]
        self.assertEqual(missing, [], "options of the command line that no document mentions: %s" % missing)


if __name__ == "__main__":
    unittest.main()

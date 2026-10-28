---
name: release
description: Prepare a release of deckbench (tests, CI, version, changelog, tag, site copy). Use when asked to release, tag or cut a version of deckbench. Prepares everything and stops before the tag and the push to ask.
---

# Release deckbench

A tag makes a GitHub release with the changelog entry as its notes (`.github/workflows/release.yml`). **Do not tag or push until the
user says so.** Nothing is deployed from here by hand except the site copy in step 6.

## Steps

1. Clean tree on `main`. Run the tests where deckbench runs (`python -m unittest discover -s tests`). Run the
   scenarios of `deckbench/examples` that need no unit.
2. **CI is green** on the commit that will be tagged: Ubuntu and Windows, Python 3.8 and 3.12 (macOS is not supported: its
   loopback carries no broadcasts). Without a token the API allows few requests an hour, so do not poll it.
3. **Version.** One place: `__version__` in `deckbench/__init__.py` (`pyproject.toml` reads it). Raise it to match the tag.
4. **`CHANGELOG.md`.** Rename "Unreleased" or "Not yet released" to `## vX.Y.Z` and group it as past releases are (the page,
   the API, fixes). Write what changed for someone using the bench, in short plain sentences with no semicolons. The workflow
   fails without an entry for the tag. `python tools/release_notes.py vX.Y.Z` shows the notes GitHub will get.
5. **Docs match.** If the API or the options changed, `README.md` and `docs/` say so.
6. **The site copy.** If the page (`deckbench/ui`) changed: `python tools/copy_to_site.py ../commitcollective.cc/public/deckbench/app`.
   The site deploys on push, so leave pushing it to the user.
7. **Ask, then tag and push:** `git tag vX.Y.Z`, `git push`, `git push --tags` (a plain push does not send tags).
   To write the notes of an existing tag again after a changelog fix: Actions, release, Run workflow.

## Afterwards

The DJS-1000 mods' link tests run on this bench: tell the user if a change touches what they rely on (the API, ports, the unit
adapter), so the mods' gate is run again.

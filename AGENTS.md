# deckbench: working rules

- Deckbench is a general-purpose public protocol test bench. Keep setup and platform guidance independent of any
  particular emulator or private workflow. Device-specific adapters are optional integrations, not core requirements
- Nothing from Pioneer DJ or AlphaTheta goes in this repo: no firmware, no captures taken from a unit's firmware.
- Always commit completed changes locally on `main`. Ask before pushing, tagging or deploying, and never amend a commit that is on `origin`.
  Amending the latest commit is fine while it is not pushed and the change iterates on it.
- Commit subjects: an action verb, under 50 characters. Body optional, otherwise
  a blank line and body lines under 72 characters. No semicolons in prose,
  emojis or attribution. Omit routine check boilerplate, but mention tests or
  CI when that is the primary change.
- Downstream applications use this bench for integration tests. Changes to the API, ports or adapter contracts can
  break consumers: say so in the reply.

## Entry points and checks

- The README is the quick start. API and CLI detail belongs in
  `docs/reference.md`, test guidance in `docs/developing.md`.
- Run `python -m unittest discover -s tests -v` after code changes.
  Packaging changes also need `python -m pip install --no-deps .` followed by
  `python -I tools/check_installed.py`, preferably in a disposable environment.
- Network checks require loopback UDP broadcast on Linux or Windows. A sandbox
  failure is not a passing regression result. Do not overlap suites on the
  same port ranges or stop another session's bench.
- Prefer deterministic parser/model checks for exact state and socket checks
  for integration. There is no cross-port UDP ordering guarantee. Use bounded
  observable waits, not blanket retries or allowed CI failures.
- Read CI annotations and the first failed assertion before retrying.
  Report initial failures, skips and environmental limits honestly.
- Model profiles describe packet shapes, not full hardware fidelity. Physical
  device and phone compatibility claims need corresponding evidence.
- The hero picture of the README and the website (`public/deckbench/hero.png` in the website repo) is made by `python tools/hero.py`.
  When the page's look changes, run it and commit the new picture in the website repo, not here. The README links to it there.

## The changelog

`CHANGELOG.md` tells someone upgrading from the last release what changed for them, not the history of the work.

- The file opens with `# Changelog` and the line "Newest first. A release is a tagged commit."
- What is not released yet goes under `## Not yet released`. A release renames that heading to `## vX.Y.Z`.
- An entry opens with one or two plain sentences: what the release brings, for the person who installs it.
- Its items go under `###` headings: `Compatibility changes` first when there are any, then the repository's own
  areas, then `Fixes` last.
- One short line per item, in plain words for the person who uses it: what changed, not how it was found, why it
  broke or how it was tested. No internal formats or maintainer tooling. A compatibility note may take a second
  sentence.
- A feature new in the coming release is described as it works now. A fix to it, or a change of it, before the
  release amends that feature's line. It never gets a line of its own.
- A fix line is only for a bug that was in a published release.
- A behaviour that changes from the last release goes under `Compatibility changes`.
- Nothing that is not checked yet ("untried", "pending", "experimental") goes in unless the owner wants it said.

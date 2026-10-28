# deckbench: working rules

- Nothing from Pioneer DJ or AlphaTheta goes in this repo: no firmware, no captures taken from a unit's firmware.
- Always commit completed changes locally on `main`. Ask before pushing, tagging or deploying, and never amend a commit that is on `origin`.
- Commit subjects: an action verb, under 50 characters. Body optional, otherwise
  a blank line and body lines under 72 characters. No semicolons in prose,
  emojis or attribution. Omit routine check boilerplate, but mention tests or
  CI when that is the primary change.
- The DJS-1000 emulator and mods use this bench for their link tests. A change to the API, the ports or the unit adapter can
  break them: say so in the reply.

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

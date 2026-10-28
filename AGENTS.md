# deckbench: working rules

- Nothing from Pioneer DJ or AlphaTheta goes in this repo: no firmware, no captures taken from a unit's firmware.
- Commit on `main`. Ask before pushing, tagging or deploying, and never amend a commit that is on `origin`.
- Commit messages: an action verb, under 50 characters, a blank line, a body under 72 columns, no emojis, no attribution lines.
- The DJS-1000 emulator and mods use this bench for their link tests. A change to the API, the ports or the unit adapter can
  break them: say so in the reply.
- The hero picture of the README and the website (`public/deckbench/hero.png` in the website repo) is made by `python tools/hero.py`.
  When the page's look changes, run it and commit the new picture in the website repo, not here. The README links to it there.

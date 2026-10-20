# Changelog

## Not yet released

The first version, `v0.1.0`, once it is tagged.

- Pro DJ Link decks: discovery, status, beats, tempo master, sync and hand-off, loops, and the database server for track titles.
- A page and an HTTP API to drive them, a command line, scenarios with expectations, events of what the device under test did,
  network faults, strict decks that behave as a CDJ-2000NXS2 does, and the decks' sound.
- A new page: a card for each deck (switches, beat squares, tempo display and slider, loops, cable, a track from any deck's database),
  and tabs for events (filter, pause, export), scenarios (editor, examples, saved ones, progress), the network and the settings.
  It follows a server-sent event stream and works in light and dark. The page is files (`deckbench/ui`), not a string in Python.
- Scenarios can expect things of the device under test (`expect_unit`: its master role, sync, tempo, and the lamps an adapter
  reads) and of the decks (`expect_deck`), press its controls (`unit`), act only `when` it is in a given state, and say what
  they `require`. A scenario that needs a unit or an adapter that is not there is skipped, not failed. `--scenario` takes
  several files or a folder and ends with a summary. Matchers: `near`, `min`, `max`, `in`, `not`.
- Adapters: `--adapter djs1000-emu` reads the DJS-1000 emulator's lamps and presses its SYNC and MASTER. `GET /api/unit`,
  `POST /api/unit/press/<control>`, and the Network tab shows the unit's state with buttons.
- A library of scenarios for a unit (`deckbench/examples/unit`): it follows a master deck and its tempo, the master role passes
  between a deck and the unit, and it keeps following after a cable pull and with 30 % of the packets lost.
- More of the unit is heard: synced, playing, on air and the beat, and `unit_sync` and `unit_play` events.
- Settings that can be changed while it runs: strict decks, database refusal and the model name (`/api/settings`).
- A track can come from another deck's database and slot (`/api/deck/<n>/load/<id>?source=&slot=`). A title with a percent sign
  is no longer decoded twice.
- Example scenarios in `deckbench/examples`.
- `--port-shift` moves every port of the decks. The bench names the port it cannot have when it starts.
- `--ready-file`, `GET /api/ready` and `deckbench.testing.Bench` to start a bench from a test without guessing a delay.
- Runs on Linux, Windows and macOS. The tests use ports of their own, so a running bench or rekordbox does not matter.
  Tried on Windows 11 (Python 3.10, 3.9) and, through the emulator, WSL2 on Ubuntu 24.04.

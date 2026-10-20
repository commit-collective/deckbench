# Changelog

## Not yet released

The first version, `v0.1.0`, once it is tagged.

- Pro DJ Link decks: discovery, status, beats, tempo master, sync and hand-off, loops, and the database server for track titles.
- A page and an HTTP API to drive them, a command line, scenarios with expectations, events of what the device under test did,
  network faults, strict decks that behave as a CDJ-2000NXS2 does, and the decks' sound.
- A new page: a card for each deck (switches, beat squares, tempo display and slider, loops, cable, a track from any deck's database),
  and tabs for events (filter, pause, export), scenarios (editor, examples, saved ones, progress), the network and the settings.
  It follows a server-sent event stream and works in light and dark. The page is files (`deckbench/ui`), not a string in Python.
- Settings that can be changed while it runs: strict decks, database refusal and the model name (`/api/settings`).
- A track can come from another deck's database and slot (`/api/deck/<n>/load/<id>?source=&slot=`). A title with a percent sign
  is no longer decoded twice.
- Example scenarios in `deckbench/examples`.
- `--port-shift` moves every port of the decks. The bench names the port it cannot have when it starts.
- `--ready-file`, `GET /api/ready` and `deckbench.testing.Bench` to start a bench from a test without guessing a delay.
- Runs on Linux, Windows and macOS. The tests use ports of their own, so a running bench or rekordbox does not matter.
  Tried on Windows 11 (Python 3.10, 3.9) and, through the emulator, WSL2 on Ubuntu 24.04.

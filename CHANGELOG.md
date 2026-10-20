# Changelog

## Not yet released

The first version, `v0.1.0`, once it is tagged.

- Pro DJ Link decks: discovery, status, beats, tempo master, sync and hand-off, loops, and the database server for track titles.
- A page and an HTTP API to drive them, a command line, scenarios with expectations, events of what the device under test did,
  network faults, strict decks that behave as a CDJ-2000NXS2 does, and the decks' sound.
- `--port-shift` moves every port of the decks. The bench names the port it cannot have when it starts.
- `--ready-file`, `GET /api/ready` and `deckbench.testing.Bench` to start a bench from a test without guessing a delay.
- Runs on Linux, Windows and macOS. The tests use ports of their own, so a running bench or rekordbox does not matter.
  Tried on Windows 11 (Python 3.10, 3.9) and, through the emulator, WSL2 on Ubuntu 24.04.

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
- A simulated DJM mixer (`--mixer`, the Mixer tab, `/api/mixer`, the `mixer` scenario step): it announces itself as device 33,
  reports which channels are on the air and starts and stops players with fader start. The decks' on-air flag follows any mixer.
  `--claim` makes a deck do what a player does when it comes online (hellos, the three claim stages), and a deck that is on defends
  its number against another device that claims it. The keep-alive counts the devices on the network.
- `--profile` (and a Settings choice): the decks stand in for a CDJ-2000 (nexus), CDJ-2000NXS2, XDJ-1000MK2 or CDJ-3000, with its name,
  the length of its statuses and its nexus byte. The DJS-1000 emulator follows a master under each of them.
- Library scenario `unit/40-on-air.json`: the unit says it is on air when the mixer's channel 1 is open. Example 04 shows the
  mixer starting and stopping the decks.
- Settings that can be changed while it runs: strict decks, database refusal and the model name (`/api/settings`).
- A track can come from another deck's database and slot (`/api/deck/<n>/load/<id>?source=&slot=`). A title with a percent sign
  is no longer decoded twice.
- Example scenarios in `deckbench/examples`.
- `--port-shift` moves every port of the decks. The bench names the port it cannot have when it starts.
- `--ready-file`, `GET /api/ready` and `deckbench.testing.Bench` to start a bench from a test without guessing a delay.
- Runs on Linux, Windows and macOS. The tests use ports of their own, so a running bench or rekordbox does not matter.
  Tried on Windows 11 (Python 3.10, 3.9) and, through the emulator, WSL2 on Ubuntu 24.04.

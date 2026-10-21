# Changelog

Newest first. A release is a tagged commit.

## Not yet released

- The bench hears the link (`protocols/monitor.py`). Other players and mixers on the network get a read-only card with what they
  do and their model, and a log in the Network tab shows the Pro DJ Link packets as they come (`/api/packets`). The bench's own
  packets, statuses and beats are options. See `docs/link.md`.
- Each deck and each device has a scrolling strip with a grid of beats and bars, and a loop shows where it goes back.
- The tempo slider changes the tempo while it is dragged, not on release.
- A synced deck snaps to the master's beat grid, not only to its tempo.
- Each deck has its own sound, and other devices on the link can be heard too. The settings choose which.
- The page can play the decks' beats (the Sound button): a kick, a snare and a hat for each deck that plays, in time with it, made with Web
  Audio. With a mixer on only the decks that are on air are heard. The demo has a deck 1 too.

- The API refuses a request from a web page of another origin (any site could drive a bench on localhost), unless `--allow-origin` names it,
  and answers its CORS preflight, private network access included. `--token` makes the API want a token.
- The page works hosted on another site and from a phone: `transport.js` takes the address and token of a bench (a dialog asks for
  them), and `?demo` runs a bench made of JavaScript in the page (`demo.js`), tested in node. `docs/phone.md`,
  `tools/copy_to_site.py`.
- Releases: a tag makes a GitHub release with the changelog's entry (`.github/workflows/release.yml`, which can be run by hand for a tag
  that has none). The test workflow says which test failed, and runs on Ubuntu and Windows.
- The WSL test of `Bench` only runs where a WSL distribution starts.
- UDP sockets are shared with SO_REUSEPORT on macOS, and the page's server no longer does a reverse lookup when it starts, which held it
  up for many seconds on a macOS runner.

## v0.1.0

The first version.

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
- Runs on Linux and Windows, Python 3.8 and later: the GitHub Action passes on Ubuntu and on Windows with 3.8 and 3.12. The tests use ports
  of their own, so a running bench or rekordbox does not matter. The DJS-1000 emulator scenarios ran in WSL2.
  On macOS the loopback carries no broadcasts, so decks on 127.0.0.n are not heard and 27 of the tests fail: it is not tested. Use `--bind` there.

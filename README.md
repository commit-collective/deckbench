# deckbench

Simulated DJ decks on a network, for testing what talks to them: players,
mixers, DJ software, firmware, hardware, emulators.

Players and software that speak a DJ link protocol are tested with real decks,
which means owning them, cabling them and loading tracks. deckbench stands in:
any number of decks that announce themselves, report a loaded track, play at a
tempo with beats, sync to a master, hand the master role over, and answer the
track database, all driven from a web page, a small HTTP API or the command
line.

| Protocol | State |
|---|---|
| Pro DJ Link (Pioneer / AlphaTheta CDJs) | working: discovery, status, beats, tempo master and sync, track metadata (title) |
| StagelinQ (Denon DJ) | planned |

Written from the public protocol analyses, and checked against a Pioneer
DJS-1000 (in an emulator; see [docs/prolink.md](docs/prolink.md) for what such
a unit needs from a deck that it does not say anywhere).

## Run

Python 3.8 or later, no packages to install.

    python -m deckbench --numbers 2,3,4 --on

then open <http://127.0.0.1:8750/>. A deck is a card with ON, PLAY, SYNC and MASTER, the four beat squares of its bar and its
tempo display, its loops, its tempo (the pitch fader), its cable (pull it, or silence it for a while) and a fold to load a
track (its id, title, BPM, the deck whose database it comes from and the slot). The side panel has four tabs: **Events**
(what the device under test did: filter, pause, export), **Scenario** (an editor with the examples, saved scenarios, a run
with its progress), **Network** (the share of datagrams lost, the unit heard on the network) and **Settings** (strict decks,
database refusal, the model name, the theme, and how the bench was started). `http://127.0.0.1:8750/#scenario` opens a tab. The decks of Pro DJ Link are at 127.0.0.<number>, so
the client must see the machine's loopback: run both in one network namespace
(on Windows, in WSL, which also reaches the page at `localhost`).

Options (`python -m deckbench --help`):

- `--decks N` or `--numbers N,N,...`: the players (default 1 to 4)
- `--on`: start them on (otherwise off; switch on from the page)
- `--init DECK=play,sync,master,loopN`: start a deck on, playing, synced, the master, looping N beats
- `--loaded DECK=SOURCE:SLOT:ID`, `--titles FILE`: the track a deck has loaded
  (from another player's database) and the titles each deck knows; the
  default is track 100 + the deck's number, from itself, "Track of deck N"
- `--bind ADDRESS,...`, `--netmask`, `--broadcast`: decks on a real network, with an
  address each (see [docs/real-network.md](docs/real-network.md)); default the loopback
- `--strict`: the decks behave as a CDJ-2000NXS2 or an XDJ-1000MK2 does: they serve the players 1 to 4 that announced
  themselves, a fifth device gets no answer and a unit that is not a player (a DJS-1000 in drum machine mode) has its
  requests turned down
- `--audio-port PORT`, `--audio-decks N,N`: the decks' sound on a TCP port, in real time (see [docs/audio.md](docs/audio.md))
- `--scenario FILE`, `--then-exit`: play a timeline of what the decks do and what to expect of the device under test
  (see [docs/scenarios.md](docs/scenarios.md))
- `--events FILE`: what the device under test did, a JSON object a line
- `--port-shift N`: move every port of the decks by N (UDP 50000-50002, TCP 12523 and 1051). For a bench beside something that
  holds the real ports, or where the system keeps them back (Windows can reserve UDP 50000-50059, see
  `netsh interface ipv4 show excludedportrange protocol=udp`). A unit on the real ports does not hear such decks
- `--ready-file FILE`: once the decks and the page are up, write FILE, a JSON object with the page's address, the ports and the
  process. A script that starts the bench waits for it instead of guessing a delay
- `--model NAME`: the device name the decks announce (default `CDJ-FAKEn`)
- `--http-port PORT` (default 8750, -1 for none), `--http-host ADDRESS`

## API

    GET  /api/state                   what the decks are, as JSON
    POST /api/deck/<n>/<what>         a click on a switch: on, play, sync, master
    POST /api/deck/<n>/<what>/<0|1>   set the switch instead
    POST /api/deck/<n>/loop/<beats>   loop that many beats from the beat the deck is in (0: end it)

    POST /api/deck/<n>/tempo/<bpm>    the pitch fader: the deck plays at that tempo
    POST /api/deck/<n>/load/<id>      the deck loads that track (optional ?title=...&bpm=...&source=<player>&slot=<n>), from its first beat
    POST /api/deck/<n>/unplug         the cable is pulled (also plug, and silence/<seconds>)
    POST /api/settings/<name>/<value> strict and refuse_db (0 or 1), model (the name the decks announce)
    GET  /api/examples                the scenarios that come with the bench (deckbench/examples)
    GET  /api/stream                  the state, the events and the scenario as server-sent events (what the page follows)
    POST /api/loss/<percent>          that share of the datagrams is lost (0 for none)
    GET  /api/ready                   {"ready": true} and how the bench was started (version, pid, ports, address)
    GET  /api/events?since=<n>        what the device under test did, from the n-th event on
    POST /api/events/clear            forget them
    POST /api/scenario                play the scenario in the body (JSON), one at a time; /stop ends it; GET gives how far it is

`/api/state` has, for each deck, its switches, its tempo, its name, its track
and, while it plays, a `phase` ([time, beats into its bar, tempo]) to count the
beats on from, and for each protocol what it knows of the other side.

## Tests

    python -m unittest discover -s tests

Starts the bench in the process and checks, from a small client, the
keep-alives, the status packets' fields, the beats, sync and master, the
hand-off to a player that asks, the sync commands, the database and the API.
It runs on Linux, Windows and macOS (macOS needs the aliases 127.0.0.2 and up on `lo0`).
The tests do not use the real ports: they take the first free range, or the shift in `DECKBENCH_PORT_SHIFT`.

## Use it from a test

`deckbench.testing.Bench` starts a bench in a process of its own, on a free range of ports, waits until it is ready and
stops it at the end. Its methods drive the API:

    from deckbench.testing import Bench

    with Bench(numbers=[2, 3], on=True, init={2: "play,loop4"}) as bench:
        # point the device under test at bench.ports, then:
        bench.post("api/deck/2/tempo/126")
        event = bench.wait_event("fader_start", timeout=5, deck=2)
        result = bench.run_scenario(scenario_dict)     # result["failed"]: the expectations that failed
        print(bench.output())                          # what the bench printed

From any other language, start `python -m deckbench --http-port 0 --ready-file ready.json` and read the file.

## Layout

    deckbench/core.py             a deck, and the world of decks, whatever the protocol
    deckbench/protocols/prolink.py  Pro DJ Link
    deckbench/web.py              the API, and the page's files
    deckbench/ui/                 the page: index.html, app.css, app.js (no packages, no build step)
    deckbench/examples/           scenarios to start from (the page lists them, `--scenario` plays them)
    deckbench/events.py           what the device under test did, to wait for and check
    deckbench/scenario.py         a timeline of what the decks do and what to expect
    deckbench/audio.py            the decks' sound, in real time
    deckbench/testing.py          a bench to start from a test (Bench)
    deckbench/cli.py              the command line
    docs/prolink.md               what it sends, and what a unit under test was found to need
    docs/real-network.md          showing the decks to a real unit on a real network
    docs/scenarios.md             scenarios, faults, events and the strict decks
    docs/audio.md                 the decks' sound

A protocol is a module that gives the World what to show of the decks and
takes part in the changes that concern it (`core.Protocol`).

## Licence

MIT OR Apache-2.0, at your option ([LICENSE-MIT](LICENSE-MIT),
[LICENSE-APACHE](LICENSE-APACHE)).

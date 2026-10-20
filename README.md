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

then open <http://127.0.0.1:8750/>: a row for each deck with ON, PLAY, SYNC and
MASTER, the four beat squares of its bar and its BPM, and what is known of a
DJS-1000 on the network. The decks of Pro DJ Link are at 127.0.0.<number>, so
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
- `--model NAME`: the device name the decks announce (default `CDJ-FAKEn`)
- `--http-port PORT` (default 8750, -1 for none), `--http-host ADDRESS`

## API

    GET  /api/state                   what the decks are, as JSON
    POST /api/deck/<n>/<what>         a click on a switch: on, play, sync, master
    POST /api/deck/<n>/<what>/<0|1>   set the switch instead
    POST /api/deck/<n>/loop/<beats>   loop that many beats from the beat the deck is in (0: end it)

    POST /api/deck/<n>/tempo/<bpm>    the pitch fader: the deck plays at that tempo
    POST /api/deck/<n>/load/<id>      the deck loads that track (optional ?title=...&bpm=...), from its first beat
    POST /api/deck/<n>/unplug         the cable is pulled (also plug, and silence/<seconds>)
    POST /api/loss/<percent>          that share of the datagrams is lost (0 for none)
    GET  /api/events?since=<n>        what the device under test did, from the n-th event on
    POST /api/events/clear            forget them

`/api/state` has, for each deck, its switches, its tempo, its name, its track
and, while it plays, a `phase` ([time, beats into its bar, tempo]) to count the
beats on from, and for each protocol what it knows of the other side.

## Tests

    python -m unittest discover -s tests

Starts the bench in the process and checks, from a small client, the
keep-alives, the status packets' fields, the beats, sync and master, the
hand-off to a player that asks, the sync commands, the database and the API.
It uses UDP 50000-50002 on the loopback: nothing else may listen there.

## Layout

    deckbench/core.py             a deck, and the world of decks, whatever the protocol
    deckbench/protocols/prolink.py  Pro DJ Link
    deckbench/web.py              the page and the API
    deckbench/events.py           what the device under test did, to wait for and check
    deckbench/scenario.py         a timeline of what the decks do and what to expect
    deckbench/audio.py            the decks' sound, in real time
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

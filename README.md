# deckbench

[![release](https://img.shields.io/github/v/release/commit-collective/deckbench?display_name=tag)](https://github.com/commit-collective/deckbench/releases)
[![tests](https://github.com/commit-collective/deckbench/actions/workflows/test.yml/badge.svg)](https://github.com/commit-collective/deckbench/actions/workflows/test.yml)

Simulated DJ decks on a network, for testing what talks to them: players,
mixers, DJ software, firmware, hardware, emulators.

<p align="center">
<img src="https://commitcollective.cc/deckbench/hero.png" alt="The deckbench page: four simulated decks on air with their beat strips, tempo, loops and cable controls, another player heard on the network, and the events list" width="1000">
</p>

Follow development: [commitcollective.cc](https://commitcollective.cc), [Instagram](https://www.instagram.com/commit.collective), [YouTube](https://www.youtube.com/@CommitCollective). On GitHub, Watch, then Releases. The page runs in a browser at [commitcollective.cc/deckbench](https://commitcollective.cc/deckbench/), as a demo or as the screen of a bench of your own.

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

then open <http://127.0.0.1:8750/>. A deck is a card whose number switches it on and off, with PLAY (and PAUSE), CUE, SYNC and MASTER, the four beat squares of its bar and its
tempo display, its loops, its tempo (the pitch fader), its cable (pull it, or silence it for a while) and a fold to load a
track (its id, title, BPM, the deck whose database it comes from and the slot). The side panel has five tabs:

- **Events**: what the device under test did, with a filter, pause and export.
- **Scenario**: an editor with the examples, saved scenarios and a run with its progress.
- **Mixer**: a simulated DJM with a fader and fader start for each channel.
- **Network**: the share of datagrams lost and the unit heard on the network.
- **Settings**: strict decks, database refusal, claiming the number first, the model name, the look (Commit or Classic) and the colours (dark or light), and how the bench was started.

**Sound** in the header plays each deck's beat in the browser (a kick, a snare and a hat, made with Web Audio, or the deck's own sound file
if it has one), and with a mixer on only the decks on air are heard. It is the page's own sound, not the device under test's: see [docs/audio.md](docs/audio.md) for the stream that goes to an emulator.

`http://127.0.0.1:8750/#scenario` opens a tab. The decks of Pro DJ Link are at 127.0.0.<number>, so the device under test must
see this machine's loopback: run both on the same machine and network namespace. The bench runs on Linux and Windows (tested by CI on both, with Python 3.8 and 3.12). On macOS the loopback carries no broadcasts, so
the decks on 127.0.0.n are not heard: use the real network mode there (`--bind`, see [docs/real-network.md](docs/real-network.md)).
An emulator that lives in WSL needs the bench there too (`Bench(wsl=True)` from a test does that).

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
- `--track DECK=FILE@BPM[@START]`: a deck plays your own sound file (a WAV, or what ffmpeg reads) instead of its drum loop, at the
  tempo you say it was made at (see [docs/audio.md](docs/audio.md)). The page has the same in the deck's "Load a track" fold
- `--scenario FILE`, `--then-exit`: play a timeline of what the decks do and what to expect of the device under test
  (see [docs/scenarios.md](docs/scenarios.md))
- `--events FILE`: what the device under test did, a JSON object a line
- `--port-shift N`: move every port of the decks by N (UDP 50000-50002, TCP 12523 and 1051). For a bench beside something that
  holds the real ports, or where the system keeps them back (Windows can reserve UDP 50000-50059, see
  `netsh interface ipv4 show excludedportrange protocol=udp`). A unit on the real ports does not hear such decks
- `--ready-file FILE`: once the decks and the page are up, write FILE, a JSON object with the page's address, the ports and the
  process. A script that starts the bench waits for it instead of guessing a delay
- `--exit-on-eof`: leave when standard input is closed. For a program that starts the bench and must not leave it running if it
  dies (`deckbench.testing.Bench` does this). `--version` prints the version and leaves
- `--mixer [NAME]`, `--mixer-address`, `--mixer-channels 4|6`: a simulated DJM that tells the decks which channels are on the air
  and starts them with its faders (see [docs/mixer.md](docs/mixer.md))
- `--claim`: a deck that comes on claims its number first, as a player does (3.6 s), instead of being there at once
- `--adapter NAME[:ARGS]`: what the device under test shows beyond the network, so a scenario can expect a lamp and press a
  control. There is `djs1000-emu` for the emulator (see [docs/adapters.md](docs/adapters.md))
- `--profile MODEL`: stand in for a model of player: cdj-2000, cdj-2000nxs2, xdj-1000mk2 or cdj-3000 (its name, the length of its
  statuses and a byte of them, see [docs/prolink.md](docs/prolink.md))
- `--model NAME`: the device name the decks announce (default `CDJ-FAKEn`)
- `--http-port PORT` (default 8750, -1 for none), `--http-host ADDRESS`
- `--allow-origin ORIGIN`: a page of that origin (the hosted page, `https://commitcollective.cc`) may use the API, with CORS. Every other
  site is refused, since any web page can reach a bench on localhost otherwise. Repeat for more
- `--token TOKEN` (or `auto`): the API wants it, as `?token=...` or `Authorization: Bearer ...`. The page takes it from the address:
  `http://host:8750/#token=...`. Use it with `--http-host 0.0.0.0`

## API

    GET  /api/state                   what the decks are, as JSON
    POST /api/deck/<n>/<what>         a click on a switch: on, play, sync, master
    POST /api/deck/<n>/<what>/<0|1>   set the switch instead
    POST /api/deck/<n>/cue[/<1|0>]    CUE, pressed (1) and let go (0), or a tap: back to the cue point while playing, plays while held on it,
                                      sets the cue point when paused elsewhere
    POST /api/journal/start|stop      keeps every request that changes the decks, with its time (see docs/link.md)
    POST /api/deck/<n>/loop/<beats>   loop that many beats from the beat the deck is in (0: end it)

    POST /api/deck/<n>/tempo/<bpm>    the pitch fader: the deck plays at that tempo
    POST /api/deck/<n>/load/<id>      the deck loads that track (optional ?title=...&bpm=...&source=<player>&slot=<n>), from its first beat.
                                      With ?audio=<path>&bpm=<what it was made at>&offset=<seconds> it plays that sound file (docs/audio.md)
    POST /api/deck/<n>/audio/clear    the deck's drum loop again
    POST /api/audio/source/<n|all>    the sound port plays only deck n (the unit's input is one CDJ), or all the decks again
    GET  /api/uploads                 where the bench keeps the files the page sent and what it holds: {"dir", "files", "bytes"}
    POST /api/uploads/clear           remove them (a file a deck has loaded stays): {"removed", "bytes"}
    POST /api/upload?name=<file>      the body is a sound file from the page's computer: the bench keeps it and answers {"path": ...}
    GET  /api/deck/<n>/audio.wav      the deck's sound file as a WAV, which the page's Listen button plays for it (404 if it has none)
    GET  /api/deck/<n>/waveform       its loudness, 100 values a second of 0 to 100, which the deck's strip draws behind its grid
    POST /api/deck/<n>/unplug         the cable is pulled (also plug, and silence/<seconds>)
    POST /api/settings/<name>/<value> strict and refuse_db (0 or 1), model (the name the decks announce)
    GET  /api/unit                    what is known of the device under test (the network's word, and the adapters')
    POST /api/unit/press/<control>    press a control of the device under test through an adapter
    GET  /api/examples                the scenarios that come with the bench (deckbench/examples)
    GET  /api/stream                  the state, the events and the scenario as server-sent events (what the page follows)
    POST /api/mixer/on/<0|1>          the mixer on or off. Also master/<0|1>, channel/<n>/fader/<0-100>, channel/<n>/fader_start/<0|1>,
                                      channel/<n>/command/<start|stop>
    POST /api/loss/<percent>          that share of the datagrams is lost (0 for none)
    GET  /api/ready                   {"ready": true} and how the bench was started (version, pid, ports, address)
    GET  /api/packets?since=<n>       the Pro DJ Link packets the bench heard (docs/link.md). POST /api/packets/clear forgets them
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
It runs on Linux and Windows, and CI tests both. The tests need the whole of 127.0.0.0/8 and its broadcast address, which macOS does not give:
27 of them fail there, so macOS is not tested.
The tests do not use the real ports: they take the first free range, or the shift in `DECKBENCH_PORT_SHIFT`.

## From a phone, or a page on another site

The page is the same wherever it is served: by the bench itself, hosted (commitcollective.cc/deckbench, which asks for the address and
the token of a bench) or as a **demo** (`?demo`), a bench made of JavaScript in the page that needs no network. A phone is the screen of
a bench that runs on a machine cabled to the players, not the bench: see [docs/phone.md](docs/phone.md). How commitcollective.cc
serves it, and how to host it elsewhere (`tools/copy_to_site.py DIR`): [docs/hosting.md](docs/hosting.md).

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
    deckbench/ui/                 the page: index.html, app.css, app.js, transport.js (which bench), sound.js (the beats as sound), demo.js (the demo); no packages, no build step
    deckbench/examples/           scenarios to start from (the page lists them, `--scenario` plays them)
    deckbench/protocols/mixer.py  the simulated DJM
    deckbench/protocols/startup.py  the packets of a device coming online
    deckbench/events.py           what the device under test did, to wait for and check
    deckbench/adapters/           what the device under test shows beyond the network (the DJS-1000 emulator's lamps and buttons)
    deckbench/matching.py         matching the device's state against what a scenario expects
    deckbench/scenario.py         a timeline of what the decks do and what to expect
    deckbench/audio.py            the decks' sound, in real time
    deckbench/testing.py          a bench to start from a test (Bench)
    deckbench/cli.py              the command line
    docs/prolink.md               what it sends, and what a unit under test was found to need
    docs/real-network.md          showing the decks to a real unit on a real network
    docs/scenarios.md             scenarios, faults, events and the strict decks
    docs/audio.md                 the decks' sound
    docs/phone.md                 a phone as the screen, and what a phone as the bench would take
    docs/mixer.md                 the simulated mixer, and a player coming online
    docs/adapters.md              seeing the device under test from the inside, and writing an adapter

A protocol is a module that gives the World what to show of the decks and
takes part in the changes that concern it (`core.Protocol`).

## Licence

MIT OR Apache-2.0, at your option ([LICENSE-MIT](LICENSE-MIT),
[LICENSE-APACHE](LICENSE-APACHE)).

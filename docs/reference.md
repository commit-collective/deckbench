# Command line and HTTP API

Run these commands from a checkout or an installed package.

## Command line

The Network panel also offers adapter selection on the backend computer.
`GET /api/network` lists its configured IPv4 adapters, current bindings and
remembered choice. `POST /api/network` accepts a JSON object such as
`{"interface":"Ethernet 2","remember":true}`. An empty interface selects
loopback. These routes use the same token and origin checks as other API routes.

Reconnect requires all simulated decks and the mixer to be off, with no running
scenario or action recording. It resets discovered identities and armed player
controls, while retaining packet history and continuous capture. The HTTP server
stays at the same address. Failed network binding attempts restore the previous
network, or report explicitly if recovery fails. Embedded Python servers only
offer these routes when passed a `NetworkSetup` controller via `serve(network=...)`.
The CLI enables them by default. Existing CLI network flags still take precedence
at startup, and no remembered selection changes an automated launch.
Selecting an adapter in the browser or with `--dj-interface` enables UDP source
filtering to its subnet. Manual `--bind` launches keep their previous unfiltered
receive behavior, regardless of the mask or broadcast destination. A broadcast
address alone does not establish a subnet. This is not OS-level isolation
between adapters that share a subnet. The simulated mixer remains off after
reconnecting. On a real adapter, it needs a distinct configured address supplied
with `--mixer-address`, otherwise enabling it is refused with an explanation.

Remembered choices live in `~/.deckbench/network.json`. They are only suggestions
in the picker, never automatically connected. Adapter discovery lists configured
IPv4 addresses, not proof of a cable, firewall permission or reachable players.

Options (`python -m deckbench --help`):

- `--decks N` or `--numbers N,N,...`: the players (default 1 to 4)
- `--observe`: announce an observer, with no simulated playback decks, beat packets or database servers.
  `--observer-number N` selects its unused identity, default 7. Older players may require an unused number 1 to 4
  for metadata queries. This is an announced observer, not a silent packet capture
- `--on`: start them on (otherwise off, switch on from the page)
- `--init DECK=play,sync,master,loopN`: start a deck on, playing, synced, the master, looping N beats
- `--loaded DECK=SOURCE:SLOT:ID`, `--titles FILE`: the track a deck has loaded
  (from another player's database) and the titles each deck knows. The
  default is track 100 + the deck's number, from itself, "Track of deck N"
- `--bind ADDRESS,...`, `--netmask`, `--broadcast`: decks on a real network, with an
  address each (see [real-network.md](real-network.md)). The default is loopback
- `--dj-interface NAME`: on Windows, Linux or macOS, use existing IPv4 addresses and their mask from a named interface.
  Requires enough addresses on one subnet and cannot be combined with `--bind` or `--netmask`
- `--strict`: the decks behave as a CDJ-2000NXS2 or an XDJ-1000MK2 does: they serve the players 1 to 4 that announced
  themselves, a fifth device gets no answer and a unit that is not a player (a DJS-1000 in drum machine mode) has its
  requests turned down
- `--audio-port PORT`, `--audio-decks N,N`: the decks' sound on a TCP port, in real time (see [docs/audio.md](audio.md))
- `--track DECK=FILE@BPM[@START]`: a deck plays your own sound file (a WAV, or what ffmpeg reads) instead of its drum loop, at the
  tempo you say it was made at (see [docs/audio.md](audio.md)). The page has the same in the deck's "Load a track" fold
- `--scenario FILE`, `--then-exit`: play a timeline of what the decks do and what to expect of the device under test
  (see [docs/scenarios.md](scenarios.md))
- `--events FILE`: diagnostic events for all players, a JSON object a line
- `--capture FILE`: continuously record observed UDP packets as JSON Lines to a new file, including statuses and outgoing traffic
- `--target PLAYER|IP`: optionally select the player used by `/api/unit`, `unit_*` events and unit scenarios
  No target is selected by the standalone CLI unless a device adapter supplies its legacy default.
  Existing Python integrations retain the DJS-name default. Pass `target=None` to `Prolink` to disable it.
- `--port-shift N`: move every port of the decks by N (UDP 50000-50002, TCP 12523 and 1051). For a bench beside something that
  holds the real ports, or where the system keeps them back (Windows can reserve UDP 50000-50059, see
  `netsh interface ipv4 show excludedportrange protocol=udp`). A unit on the real ports does not hear such decks
- `--ready-file FILE`: once the decks and the page are up, write FILE, a JSON object with the page's address, the ports and the
  process. A script that starts the bench waits for it instead of guessing a delay
- `--exit-on-eof`: leave when standard input is closed. For a program that starts the bench and must not leave it running if it
  dies (`deckbench.testing.Bench` does this). `--version` prints the version and leaves
- `--mixer [NAME]`, `--mixer-address`, `--mixer-channels 4|6`: a simulated DJM that tells the decks which channels are on the air
  and starts them with its faders (see [docs/mixer.md](mixer.md))
- `--claim`: a deck that comes on claims its number first, as a player does (3.6 s), instead of being there at once
- `--adapter NAME[:ARGS]`: what the device under test shows beyond the network, so a scenario can expect a lamp and press a
  control. There is `djs1000-emu` for the emulator (see [docs/adapters.md](adapters.md))
- `--profile MODEL`: stand in for a model of player: cdj-2000, cdj-2000nxs2, xdj-1000mk2 or cdj-3000 (its name, the length of its
  statuses and a byte of them, see [docs/prolink.md](prolink.md))
- `--model NAME`: the device name the decks announce (default `CDJ-FAKEn`)
- `--http-port PORT` (default 8750, -1 for none), `--http-host ADDRESS`
- `--phone`: enable token-protected access for the hosted page and print a pairing link and, with the optional `phone`
  extra installed, a terminal QR. `--phone-address IPv4` selects the address reachable from the phone
- `--network-info`: list interface information without starting the bench or changing the network
- `--allow-origin ORIGIN`: a page of that origin (the hosted page, `https://commitcollective.cc`) may use the API, with CORS. Every other
  site is refused, since any web page can reach a bench on localhost otherwise. Repeat for more
- `--token TOKEN` (or `auto`): the API wants it, as `?token=...` or `Authorization: Bearer ...`. The page takes it from the address:
  `http://host:8750/#token=...`. Use it with `--http-host 0.0.0.0`

## HTTP API

    GET  /api/state                   what the decks are, as JSON
    POST /api/deck/<n>/<what>         a click on a switch: on, play, sync, master
    POST /api/deck/<n>/<what>/<0|1>   set the switch instead
    POST /api/deck/<n>/seek/<beat>    the deck goes to that beat of its track (0 is the first), on the grid. A loop that is set stays: waited for when it is ahead, gone round when the deck is in it, left behind when the deck is past it
    POST /api/deck/<n>/jump/<beats>   and that many beats from the beat it is at (negative: back)
                                      Switches, cue, loops, seek and jump take `?at=<bench time>`, the moment of the click: a request that arrives
                                      late acts where the deck was then (a pause stops right at the playhead)
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
    POST /api/player/<ip>/arm/<0|1>?number=<n>       opt in to transport control of a discovered online player
    POST /api/player/<ip>/command/<command>?number=<n>   start, stop, sync-on, sync-off or master, requires arming
    POST /api/player/<ip>/metadata/refresh?number=<n>    read the loaded analyzed track's metadata, no arming required
    POST /api/player/<ip>/load/<id>?number=<n>&source=<player>&slot=<2|3>    request an analyzed SD/USB track, requires arming
    POST /api/mixer/on/<0|1>          the mixer on or off. Also master/<0|1>, channel/<n>/fader/<0-100>, channel/<n>/fader_start/<0|1>,
                                      channel/<n>/command/<start|stop>
    POST /api/loss/<percent>          that share of the datagrams is lost (0 for none)
    GET  /api/ready                   {"ready": true} and how the bench was started (version, pid, ports, address)
    GET  /api/packets?since=<n>       the Pro DJ Link packets the bench heard (docs/link.md). POST /api/packets/clear forgets them
    GET  /api/events?since=<n>        what the device under test did, from the n-th event on
    POST /api/events/clear            forget them
    POST /api/mark?text=<label>        add a timestamped diagnostic marker
    POST /api/scenario                play the scenario in the body (JSON), one at a time. /stop ends it. GET gives how far it is

`/api/state` has, for each deck, its switches, its tempo, its name, its track
and, while it plays, a `phase` ([time, beats into its bar, tempo]) to count the
beats on from, and for each protocol what it knows of the other side.


## Remote loading

On a discovered player's card, open Player control, enable control and open
Load a linked track. Enter the source player number, media slot and rekordbox
track ID reported on a player card. This is not a library browser or an upload
to a physical player's USB drive.

The destination must report a recent stopped state. The source must be online
and unambiguous, and the sender must be an announced unused bench player 1 to 4
or observer. Slots are 2 for SD and 3 for USB, with analyzed rekordbox tracks
only. XDJ-XZ loading is excluded because its documented behavior differs.

The API returns HTTP 202 with `sent: true, confirmed: false`. It records
`player_load_requested` without changing observed state. A request or an
acknowledgement is not proof of a successful load. Check the actual player.
This implementation has packet and loopback coverage, not hardware validation.
See the [public wire description](https://djl-analysis.deepsymmetry.org/djl-analysis/loading_tracks.html).

Start and Stop still use conditional fader-start commands, not general
PLAY, PAUSE or CUE buttons. Genuine button, hot-cue and loop-control commands
are not implemented. Adding them needs verified packet evidence, not guesses.

## Package layout


    deckbench/core.py             a deck, and the world of decks, whatever the protocol
    deckbench/protocols/prolink.py  Pro DJ Link
    deckbench/web.py              the API, and the page's files
    deckbench/ui/                 the page and its scripts, no packages or build step
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

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
- `--no-track-info`, `--no-waveforms`: start with Read track info by itself, or Read waveforms by itself, off.
- `--press-settle SECONDS`: the wait between connecting to a real player and pressing its button, 0.1 s by
  default. Most of the delay before PLAY/PAUSE or CUE takes effect. With none a CDJ-2000NXS2 setup missed CUE,
  0.05 s worked.
  Neither setting is kept from one run to the next, so these are how to have them off from the start.
- `--observe`: announce an observer, with no simulated playback decks, beat packets or database servers.
  `--observer-number N` selects its unused identity, announced at once. Without it, the number is a free 1 to 4,
  taken after 5 seconds of listening, while track info or waveforms are read by itself, and 7 otherwise. This is an announced observer, not a silent packet capture
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
  extra installed, a terminal QR. Without it, the page's **Phone** button shares the bench on demand (docs/phone.md).
  `--phone-address IPv4` selects the address reachable from the phone, for both
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
                                      With ?audio=<path>&bpm=<what it was made at>&offset=<seconds> it plays that sound file (docs/audio.md).
                                      With a real player as the source, the bench reads the track's grid (see below)
    GET  /api/deck/<n>/track-waveform the waveform and grid of the real player's track the deck has loaded, once read
    POST /api/deck/<n>/audio/clear    the deck's drum loop again
    POST /api/audio/source/<n|all>    the sound port plays only deck n (the unit's input is one CDJ), or all the decks again
    GET  /api/uploads                 where the bench keeps the files the page sent and what it holds: {"dir", "files", "bytes"}
    GET  /api/share                   how the bench is shared with phones: on, fixed (--phone), url, direct, address, port, addresses, qr.
                                      Only for the page on the bench's machine. POST /api/share/on?address=<IPv4> and /api/share/off
                                      start and stop sharing (docs/phone.md)
    POST /api/uploads/clear           remove them (a file a deck has loaded stays): {"removed", "bytes"}
    POST /api/upload?name=<file>      the body is a sound file from the page's computer: the bench keeps it and answers {"path": ...}
    GET  /api/deck/<n>/audio.wav      the deck's sound file as a WAV, which the page's Listen button plays for it (404 if it has none)
    GET  /api/deck/<n>/waveform       its loudness, 100 values a second of 0 to 100, which the deck's strip draws behind its grid
    POST /api/deck/<n>/unplug         the cable is pulled (also plug, and silence/<seconds>)
    POST /api/settings/<name>/<value> strict, refuse_db, player_control and auto_track_info (0 or 1), model (the name the decks announce)
    GET  /api/unit                    what is known of the device under test (the network's word, and the adapters')
    POST /api/unit/press/<control>    press a control of the device under test through an adapter
    GET  /api/examples                the scenarios that come with the bench (deckbench/examples)
    GET  /api/stream                  the state, the events and the scenario as server-sent events (what the page follows)
    POST /api/player/<ip>/arm/<0|1>?number=<n>       arm one player while player_control is off (scripts, --observe)
    POST /api/player/<ip>/command/<command>?number=<n>   start, stop, sync-on, sync-off or master, requires arming
    POST /api/player/<ip>/metadata/refresh?number=<n>    read the loaded analyzed track's metadata, no arming required
    GET  /api/player/<ip>/waveform    the waveform and beat grid of the player's track, once read (see below)
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


## Real players' waveforms

While **Read waveforms by itself** is on, the bench reads the waveform of each player's analyzed SD or USB track
from the player that hosts the media, which may not be the one playing it. One bounded, read-only session asks for
the overview, the detail (150 values a second) and the beat grid, in the bench's own worker, as the
announced player 1 to 4 it uses for track info. A few tracks are kept, by the source's identity, slot and track. One
is dropped when its source leaves, or when no player has had it loaded for a minute. A failed read is tried again
after a minute.

Each player in the state has a small `waveform`: `key` and `state` (`ready`, `reading`, `waiting`, `failed` with a
`reason`, `off`, or `none` with a `reason`). The data itself is only at `GET /api/player/<ip>/waveform`:
`overview` and `detail` as heights, a byte each from 0 to 100, in base64, `rate`, `style` (`rgb` or `blue` for each)
and `grid` (`[ms, bar, bpm * 100]` a beat). The RGB style is asked first. A track with none, as one analysed for
older players can be, gets the original blue style, the overview and the detail each on its own.

The card draws the detail behind the strip's beats and the overview under it, as a bench deck's waveform. Each beat
is mapped to the track through the grid's own times, so a track whose tempo changes stays aligned. A CDJ-3000's
precise position places it while paused. Older players give only the beat they have passed, and their cue, set with
CUE, cannot be read. So the bench follows them: a pause while playing is placed from the beats it played, CUE on a
paused player sets the cue there (on the nearest beat when the reported beat allows it, as quantize does), and a
return to the cue or a held CUE starts from it. Whatever it did not see, a jog or needle move, another track, a gap in
the status or a beat that disagrees, makes it forget, and the card falls back to the beat after the reported one,
marked as an estimate.
Retrieval and the grid's alignment were tried on a CDJ-2000NXS2 (1.84), for a track on its own USB and on another
NXS2's, and an XDJ-1000MK2 has answered. Live tracking, loops, seeks and the CDJ-3000 are not yet tried on
hardware, nor its three-band style, which is not asked for.

## A real player's track on a bench deck

A bench deck can load a track from a real player's SD or USB, as a CDJ loads one over the link: in the deck's
**Load a track**, pick **A player's track** (the tracks the players have loaded) or choose the player under **From the
database of** with the slot and the rekordbox ID. The API takes the same as any load:
`POST /api/deck/<n>/load/<id>?source=<player>&slot=<2|3>`.

The deck's status then names that player, slot and track, so other devices ask that player for its title and
grid, as they would for a real deck. The bench reads the track's grid, title and waveform from the player too, in
the same worker as the players' waveforms, even with Read waveforms by itself off. Once read, the deck plays on the
grid:

- its tempo is the track's, at its first beat, with the pitch at zero. A tempo set afterwards is reported as a pitch,
  as a player reports one, with the track's tempo unchanged
- its bars are counted as the grid counts them, so a track whose first beat is not on a bar line is on the right beat
- its strip draws the track's waveform

A grid whose tempo changes is followed at its first tempo, and the deck says so. The deck still sounds like its drum
loop, at the track's tempo and on its bars: the track's audio is not read. To ask the player, the deck asks as
itself when it is a player 1 to 4, else as an unused bench player 1 to 4 or the presence, as for track info.

Each deck in the state has `linked`: `null` for a track of a bench database, else the `source`, `slot` and `rbid`, a
`state` (`waiting`, `reading`, `ready` with the `title`, `artist` and `key`, or `failed` with a `reason`) and `grid`
(`bpm`, `first`, the place in the bar of the track's first beat, `beats`, `first_ms`, `variable`). `bar_shift` is
the beats from a bar line to the track's first beat. The event `linked_track_read` says the grid was taken.

A bench deck also takes the load-track command (type 0x19) that rekordbox or Beat Link sends a player, unless it
plays, as a player refuses then. The events are `load_command`, and `load_refused` with a `reason`. This has packet
and loopback coverage only. The grid and waveform reading is the players' (see above), not yet tried on hardware
for a bench deck.

## Remote loading

With Player control on in Settings, open Load a linked track on a discovered
player's card. Enter the source player number, media slot and rekordbox
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

How a player is started and stopped depends on its model. The bench reports
`transport_method` (button presses or fader start) and `fader_start_supported`
for each discovered player:

| Model | `transport_method` | `fader_start_supported` | Commands |
|---|---|---|---|
| CDJ-3000, CDJ-3000X | `buttons` | false | `play-pause` and `cue` |
| CDJ-2000NXS2, XDJ-1000MK2 | `buttons` | true | `play-pause` and `cue`, or `start` and `stop` |
| XDJ-XZ | (empty) | false | none |
| others | `fader` | true | `start` and `stop`: fader start |

Fader start is documented as unsupported on the CDJ-3000 and XDJ-XZ. The bench
can instead press PLAY/PAUSE or CUE as a remote controller does, experimental:
it connects, presses, holds 0.1 s, releases and disconnects, as controller
number 54, unicast to the player's UDP 50001 from the bench's own. PLAY/PAUSE is
a toggle, never retried, and CUE is held like the real button.

The CDJ-3000 and the CDJ-2000NXS2 take these presses in two formats. The
NXS2's fields are little-endian and name a controller slot, which the bench
sets to the player's number (1 to 4), as tested. The presses worked on CDJ-3000
firmware run in cdj3k-emu, and PLAY, PAUSE and a short CUE worked on a physical
CDJ-2000NXS2. No physical CDJ-3000 or CDJ-3000X has been tried, nor a long CUE
hold on the NXS2. The XDJ-1000MK2 is sent the NXS2's format, untried. Other
models get no presses until they are tried. The API answers HTTP 202 with `sent: true, confirmed: false` and
records `player_button`.

`POST /api/player/IP/command/play-pause?number=N` (or `cue`, one tap) needs
player control on (or the player armed), like the other commands. The wrong command for a model is
refused with the right one named. Hot cues and loops are not implemented.

CUE can also be held, as on the player, where it plays from the cue point while
held: `cue-down` connects and presses it, `cue-up` lets go and disconnects. The
card's CUE switch does this while you hold it. `cue-up` is never refused. While
the finger stays down the page sends `cue-hold` each second, which presses nothing.
A CUE that nobody keeps for 3 seconds is let go by the bench (a page that went away),
and so is one held when the bench stops or reconnects. CUE keeps the finger or the
mouse wherever it goes until it is let go. Let go on the card's PLAY/PAUSE, marked
while CUE is held, and PLAY/PAUSE is pressed first through the same connection,
while CUE is still down, so the player plays on, as with its own buttons (untried
on hardware). While CUE is held the player sends no beats, so the card's beat lamps
follow the strip's estimate.

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

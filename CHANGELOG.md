# Changelog

Newest first. A release is a tagged commit.

## Not yet released

### Compatibility changes

- The emulator's adapter is now `--adapter djs1000-emulator`, as its repository was renamed. `djs1000-emu` still works.

## v0.7.0

The CDJ-3000's track info, waveforms and beat grids are read, and the bench refuses requests that could stop it.

### The page

- The demo's first visit is welcomed with what it shows and where to follow Deckbench.

### Observation and diagnostics

- A player's database reply that does not parse names the request and the first bytes that came back.
- Each deck of a unit that shares one address, as an all-in-one does, has a card of its own, with no player control.
  Tried only without a unit.

### Fixes

- A tempo of 0, a negative one or `nan` is refused. It stopped the page's updates and the decks' sound.
- API requests made through a host name that is not the bench's own are refused, as a page using DNS rebinding would
  send them.
- A phone loads only uploaded sound files, and a scenario over 1 MB is refused.
- The bench starts on a real network on macOS. A broadcast address of 255.255.255.255 is refused there with the one to
  use.
- The track info, waveforms and beat grids of a CDJ-3000 are read.
- A bench deck shows the title of a player's track once the bench has read the track's waveform for the player.

## v0.6.0

Real players on the page: their waveforms and beat grids, PLAY/PAUSE and CUE from their cards, and their tracks on
the bench's decks.

### Compatibility changes

- The page is dark by default. Light and Follow the system stay in Settings, Appearance, Colours.
- On a real network in Linux or macOS, the bench listens only on its own and the broadcast addresses, so it no longer
  takes packets meant for another Pro DJ Link program on the same computer.
- With every deck off, the bench announces itself as an observer: 7, or a free number 1 to 4 after listening 5 s while
  it reads track info by itself. `--observe` without `--observer-number` does the same.
- Player control and Read track info are settings for every player, on by default and off with `--observe`.
- Listen plays only the bench's decks, and a real mixer no longer silences them. The page shows what the mixer says.
- The app and the docs write the name Deckbench. The command, the package and the name on the network stay `deckbench`.

### Real players

- Each player's card draws its track's waveform and beat grid, read from the player that hosts the track.
- PLAY/PAUSE and CUE can be pressed from a player's card on the CDJ-3000, CDJ-2000NXS2 and XDJ-1000MK2.
- CUE held on the card and let go on PLAY/PAUSE plays on, as on the player.
- The card's PLAY, CUE, SYNC and MASTER light from what the player reports.
- A stopped player's strip sits on its cue or where it paused, and starts from there.
- A CDJ-3000's loop is drawn from its status, placed from its precise position.
- An analyzed SD or USB track can be loaded on a stopped player through an armed remote-load form or the API.
- `--press-settle`, `--no-track-info` and `--no-waveforms` are new.
- The status line shows how the bench is on the link while its decks are off.
- A player's full name, address and track show on hover or tap.

### Bench decks

- A bench deck loads a real player's SD or USB track and plays its audio on the track's grid.
- A bench deck takes the load-track command that rekordbox or Beat Link sends a player.
- Bench decks have a player's header, and a CUE that plays while held.
- Listen has a metronome.

### Scenarios

- `player` steps and `expect_player` press, load and check real players, with an example.
- The scenario results have a Clear button.

### The page

- A Phone button shares the bench with phones on demand, with a QR code.
- Cards are reordered by their grip, and the number in a row is set in Settings.

### Networks and other programs

- `--feed` watches the link through the packets another program forwards.
- The DJ network adapter is chosen in the Network panel, Tentative Windows cards included.
- The Windows firewall helper covers several adapters.

### Fixes

- A real player's loop is steadier on the strip and drawn more clearly.
- A player's beats stay on the strip while CUE is held on the player.
- A player with no track shows no tempo, not about 655 BPM.
- A track's title is forgotten once no player has it loaded.
- A deck's sound file no longer crackles in Listen.
- On Windows, other players' beats are no longer logged on bench decks.
- A page a phone suspended reconnects.
- Text selections stay while the page redraws.
- The link log keeps its height in a short window.
- The strips are drawn again in the Classic look's light theme.
- The DJS-1000 emulator adapter stays connected when a project name is reported.
- The bench starts again on a real network in Linux or WSL.
- A busy port is named in one line instead of a traceback.

## v0.5.0

SYNC, MASTER and fader start for real players, an observer mode, and native macOS support.

### Compatibility changes

- A plain command-line session no longer picks a device named DJS- as the unit under test. `--target PLAYER|IP` picks
  it for `/api/unit`, `unit_*` events and unit scenarios.
- Clearing Events no longer resets event times, which stay relative to the session's start, as in Network capture.
  Event numbers still restart on clear.

### MASTER, SYNC and player controls

- Discovered players' cards have SYNC and MASTER commands, when turned on.
- Discovered players have fader-start transport controls, when turned on, without the simulated mixer.
- A stopped bench master hands its role to a playing, synced follower.
- A MASTER request that comes before the sender's status still hands the role over.
- The demo's synced player follows the master's tempo and bar phase.

### Observation and diagnostics

- An observer mode announces the bench with no playback decks or database servers.
- UDP capture runs continuously, and the whole capture can be exported.
- Events and Network share one session clock.
- Other players' state changes are reported.
- Incoming database queries are recorded.
- Mixer tempo status and CDJ-3000 precise positions are decoded.
- A loaded track's metadata is read on demand.
- Captures play again offline, with chosen loss, delay and jitter.

### Platforms

- macOS finds its network interfaces natively, with setup notes for Ethernet and VM bridges.
- The bench prints a browser address with its actual port and token, phone mode included.

### Fixes

- An observer's number-conflict warning clears when the conflict ends.
- A simulated mixer switched off no longer turns channels back on air with a late packet.
- The bench shuts down without waiting on its listeners.

## v0.4.0

Phones on the bench, and simulated decks that hand MASTER and SYNC to real players.

### Phones and setup

- `--phone` gives phone pairing links, with QR codes.
- `--dj-interface` picks the wired DJ adapter, and `--network-info` lists the interfaces.
- A Windows firewall helper installs, shows and removes a scoped rule.
- The docs explain browser connectivity, DJ network addresses and setups with a second adapter.

### Real players

- MASTER and SYNC pass between simulated decks and real players.
- The bench uses its adapter's real MAC address and sends player status to each discovered player.
- Broadcast tempo and beat position show without a simulated deck.
- A real DJS-1000 is a normal player unless an emulator test adapter is configured.

### Beats and sound

- Real players' beat grids are aligned, and loop shading stays across a loop's wrap.
- A compact master beat reference sits above each deck's beats.
- The browser can play broadcast-only beats, and says when its sound is unavailable or suspended.

### Network tools

- With Follow off, the visible log holds still while packets keep coming.
- A frozen view keeps text selection and exports its held rows.
- Simulated mixer controls are set apart from discovered real mixers.

### Fixes

- Older players no longer warn about the bench's compatibility fields, and the bench offers no shared USB or SD media.

## v0.3.0

CUE and pause as on a CDJ, moves on the beat grid, tracks of your own, and sessions that can be played back.

### Compatibility changes

- Play is play and pause: a deck that pauses plays on from there. A deck is at its first beat when its track is
  loaded.
- The deck's number is its on / off switch, and the ON button is gone.
- The page's Sound button is now Listen.

### The page

- CUE works as on a CDJ, with `POST /api/deck/<n>/cue[/<1|0>]`. The status says `cued` and `cue playing`.
- A deck that is off shows only its number and its name.
- The header names each sound: the `unit input` chip is the port the decks' sound is served on, and Listen plays it in
  the browser.
- A `recording a session` chip shows while a journal is kept.
- A message that something went through has a green outline, a warning a yellow one.

### Cue, loops and moves on the grid

- CUE and a loop go to the nearest beat. A deck that sets its cue is on it, so CUE held there plays from it.
- `POST /api/deck/N/seek/BEAT`, `jump/BEATS` and a Move row on the page move the deck in its track. A loop that is set
  stays through a move.
- A pause stops where the playhead was when the page was clicked, even when the request arrives late.
- A loop that is set is drawn ahead of the playhead, with a chip such as "LOOP 4 in 1.4 beats".

### The unit's input

- `POST /api/audio/source/<n|all>` makes the sound port play one deck, or all of them, while the bench runs. The
  DJS-1000 emulator calls it when LIVE SAMPLING's INPUT SOURCE knob turns.

### Tracks of your own

- A deck plays a sound file instead of its drum loop: `--track DECK=FILE@BPM[@START]`, the page's "Load a track" fold,
  or `?audio=` in the API. It plays at the deck's own tempo.
- A deck that plays a sound file shows its waveform behind the strip's beat grid.
- The page's Browse button sends a file from the browser's computer to the bench.
- Listen plays a deck's file when it has one.
- Sent files are kept between runs in `~/.deckbench/tracks` (`--tracks-dir`, `$DECKBENCH_TRACKS`). Files unused for a
  month go, and the oldest when the folder passes 2 GB. `--clear-uploads` and a Settings button empty it.

### Sessions

- `POST /api/journal/start` and `stop` keep every request that changes the decks, with its time, so a session can be
  played back. The DJS-1000 emulator's REC uses it.

### Testing from code

- `start()` and the command line return once every socket is bound.
- A test beaten to a port takes the next range and starts again.

### Fixes

- A DJS-1000's beat strip follows the beat of its bar.
- Another device's state flags sit side by side under its tag, and the card's height no longer changes with them.
- The strips and the page's sound no longer jump when play or cue is pressed, or now and then while playing.
- The waveform is one smooth shape and does not shimmer as the strip scrolls.
- A page that opened many requests at once no longer says "The bench does not answer".

## v0.2.0

The bench listens to the whole link, and the page has a new look and a phone mode.

### Listen to the network

- The bench hears other players and mixers on the link and shows each as a read-only card.
- The Network tab logs the Pro DJ Link packets as they come (`/api/packets`).
- A synced deck snaps to the master's beat grid, not only to its tempo.

### The page

- A new look, the same as commitcollective.cc, where colour only carries meaning.
- Two looks, Commit (the default) and Classic, each in dark and light.
- Each deck and device has a scrolling strip with a grid of beats and bars.
- The tempo slider changes the tempo while you drag it.
- The Sound button plays each playing deck's beat. With a mixer, only decks on air are heard.
- The page can be hosted on another site and used from a phone.
- `?demo` runs a bench made of JavaScript inside the page, with no server.

### Safety

- The API refuses requests from web pages of another origin. `--allow-origin` lets one in.
- `--token` makes the API ask for a token.

### Releases

- A tag makes a GitHub release with the changelog entry as its notes.

### Fixes

- On macOS, UDP sockets are shared, and the page's server no longer waits on a reverse lookup at start.
- The mixer's channel rows no longer share a CSS class with the beat strips.

## v0.1.0

The first version: simulated Pro DJ Link decks and a mixer, driven from a page or an API, with scenarios that test a
DJS-1000.

### Simulated decks

- Pro DJ Link decks with discovery, status, beats, tempo master, sync and hand-off, loops, and track titles.
- `--profile` makes the decks stand in for a CDJ-2000, CDJ-2000NXS2, XDJ-1000MK2 or CDJ-3000.
- A deck can load a track from another deck's database and slot.
- `--claim` makes a deck come online as a real player does, and a deck that is on defends its number.
- Strict decks behave as a CDJ-2000NXS2 does.
- A simulated DJM mixer (`--mixer`) reports which channels are on air and starts and stops players with fader start.
- Each deck has sound.
- Network faults can be simulated, for example 30 % packet loss.

### The page and the API

- A card for each deck, with its switches, beats, tempo, loops, cable and track.
- Tabs for events, scenarios, the network and the settings, in light and dark.
- An HTTP API and a command line drive the same things.
- Some settings change while it runs (`/api/settings`).

### Scenarios

- Scenarios script the decks and check what the device under test did.
- `expect_unit` and `expect_deck` check the unit and the decks, and `unit`, `when` and `require` act on the unit.
- Matchers: `near`, `min`, `max`, `in`, `not`.
- `--scenario` takes several files or a folder and ends with a summary.
- Examples are in `deckbench/examples`.

### Testing a DJS-1000

- `--adapter djs1000-emu` reads the emulator's lamps and presses its SYNC and MASTER.
- A library of unit scenarios in `deckbench/examples/unit`.
- More of the unit is heard: synced, playing, on air and the beat.

### Running it

- `--port-shift` moves every port of the decks.
- `--ready-file`, `GET /api/ready` and `deckbench.testing.Bench` start a bench from a test without guessing a delay.
- Runs on Linux and Windows with Python 3.8 and later. Not on macOS, where the loopback carries no broadcasts.

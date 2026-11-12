# Changelog

Newest first. A release is a tagged commit.

## v0.6.0

### Compatibility changes

- The page is dark by default. Light and Follow the system stay in Settings, Appearance, Colours, and a choice made
  there before is kept.
- On a real network in Linux or macOS, the bench listens on its own and the broadcast addresses only. Bound to any address,
  it could take what players send to another Pro DJ Link program of the same computer: an emulated player lost its
  master hand-off and sync to it.
- With every simulated deck off on a real network, the bench announces itself as an observer, so players send it their
  status: the cards' PLAY, SYNC and MASTER lamps and the master's beat follow them without a deck switched on. While
  it reads track info or waveforms by itself, it takes a free number 1 to 4, which older players answer, after
  listening 5 seconds first, and so does --observe without --observer-number. Otherwise it is 7.
- Player control and the reading of track info are settings for every player at once, both on by default. Player
  control is off with --observe. A player's card shows its switches straight away, without a box to tick on each card.
- PLAY/PAUSE and CUE take effect sooner: the wait between connecting to a player and pressing is 0.1 s, down from
  0.25 s. `--press-settle SECONDS` changes it. With none, CUE was missed. 0.05 s worked.
- Listen plays only the bench's decks. A real player was heard as a beat made up for it, which only stood in the way of
  its own music, out of the mixer. The Sound settings keep the volume, and a Metronome switch: while Listen is on, a
  click on each beat of the tempo master, a bench deck or a real player, higher on the first beat of the bar.
- A bench deck is heard in Listen whatever a real mixer on the network says of its channel. A DJM said a deck off the
  air when the channel of its number was down, and the page went silent, though the mixer does not carry the
  bench's sound. Only the bench's own mixer silences a deck now, as on the sound port. The deck's card shows what a
  real mixer says.
- The app, its page title and the docs write the name Deckbench. The command, the package and the name it
  announces on the network stay `deckbench`.

### Real players: control

- Press PLAY/PAUSE and CUE on a CDJ-3000 or 3000X from its card, since it does not take fader start. Each player
  shows the start and stop its model takes.
- Hold CUE on a CDJ-3000 from its card for as long as you hold the button, so it plays from the cue point.
  The bench lets go by itself after 8 seconds, or when it stops.
- Press PLAY/PAUSE and CUE on a CDJ-2000NXS2 or an XDJ-1000MK2 too, in their own packet format. They keep fader
  start as well.
- A player card under control has switches like a bench deck's: PLAY/PAUSE, CUE, SYNC and MASTER, lit from what
  the player reports. Fader start, track info and loading stay under Player control.
- A quick tap of CUE on a real player is no longer lost: the bench keeps a release that comes early and holds every
  press at least 0.1 s.
- CUE held from the page lasts as long as the finger: the page keeps it held each second, and the bench lets go
  3 seconds after the page stops. Before, it let go after 8 seconds whatever the finger did.
- Hold CUE and let go on PLAY/PAUSE to play on, as on the player: CUE keeps the finger or the mouse until it is let
  go, and PLAY/PAUSE is marked as a place to let go while CUE is held.
- Request analyzed SD/USB tracks on stopped discovered players through an
  armed remote-load form or API. Require an online source and
  announced sender, and distinguish a sent request from a confirmed load.
- Disable Read track info when no eligible sender or track source is available,
  with the reason shown on the button. Recheck eligibility before querying.

### Real players: what the cards show

- Real players' waveforms: the bench reads each player's track waveform and beat grid from the player that hosts it,
  and the card draws it behind the strip's beats, as a bench deck's, with the whole track under it. Retrieval was
  tried on a CDJ-2000NXS2. A database answer that leaves out an empty blob after a zero is now read correctly.
- Read waveforms by itself is a setting apart from track info. `--no-track-info` and `--no-waveforms` start with
  either off.
- A track with no colour waveform gets the original blue one, so tracks analysed for older players have a waveform
  on their card too.
- A real player's loop is steadier, from a capture of 2- and 4-beat loops on a CDJ-2000NXS2. The beats ahead of
  the playhead take their place in the bar from the loop, so a 2-beat loop's numbers no longer move every pass. A
  status sent in the middle of the jump back (its bar moved on, its beat not yet) no longer puts a beat in the wrong
  place, and a beat whose packet did not come is drawn.
- A track started in a loop keeps its grid and waveform, past and to come, as it plays until its first jump back,
  when the loop's length is known and the loop is drawn. The grid no longer disappears for that moment.
- The loop is easier to read: a lighter tint, and each jump back one solid marker with a flag, the same everywhere.
- A start from a stop, PLAY or a held CUE, no longer runs a beat ahead or behind at random. A player sends no beat
  for the beat it starts on, and at a cue it reports the beat before with the cue's bar. The strip now starts from
  where the player stood, timed from its first status, and its first beat is counted from there. Checked against
  a capture of an XDJ-1000MK2 and a CDJ-2000NXS2.
- A pause is placed when its status comes, which players send at once, and a pause right before a beat keeps its
  place when the player reports that beat a moment later.
- PLAY or a held CUE from a stop starts the strip where the player stood, not a beat behind, and a beat from before
  the stop is no longer taken for the new start.
- A player held on CUE sends its beats with its play flag off. The bench hid them at each status, so the strip
  switched between the beats and an estimate and the beat lamps flashed. They now stay, as while it plays.
- A real player's strip shows the track's beats and waveform before PLAY from its first seconds, also right after
  a pause or a jump to the cue, where it was empty on the left until the beats filled it.
- While CUE is held, the card's beat lamps and the master's follow the strip, as the player sends no beats then.
- A stopped real player's waveform sits on the beat it waits on, not one beat before: a player at a cue reports
  the beat before it. While CUE is held, its strip runs on smoothly between the player's status updates.
- The bench follows where an older player stops and where its CUE-button cue is: a pause is placed from the beats it
  played, and a return to the cue or a held CUE starts there. Anything it did not see makes it forget.
- A real player cued on its first beat keeps its waveform and grid on the card. It reports beat 0 there, which
  read as no track, so the strip went blank until it played.
- A real player with no track shows no tempo. It said about 655 BPM, from the empty tempo field it sends.
- A CDJ-3000's loop is drawn on its card, tinted with its jumps back, as other players' are. The card placed it
  from its precise position and drew no loop. The bench now reads where the loop is from the player's status.
- A track's title and waveform are forgotten once no player has it loaded, so a USB or SD swapped for another
  whose track has the same ID in the same slot no longer shows the old ones.
- A loaded track's title no longer disappears for a moment every minute: its track info stays while it is loaded.
- The status line says how the bench is on the link with its decks off: listening, the number it took, or silent
  while another device has it.
- Reveal full discovered-player names, addresses and track text on hover,
  or expand them with a tap or keyboard. Keep the compact card layout.
- Keep discovered-player cards within narrow phone screens.

### Bench decks

- A bench deck can load a real player's SD or USB track: pick it from the tracks the players have loaded, or give the
  player, slot and ID. The bench reads the track's grid, title and waveform from that player, and the deck plays on
  the grid: the track's tempo, its bars counted as the grid counts them, and its waveform on the strip. A tempo set
  afterwards is reported as a pitch. The sound is still the drum loop. See docs/reference.md.
- A bench deck on a real player's track plays the track itself: the bench reads its audio file from the player's SD or
  USB over NFS, as a player loading a linked track does, and the deck plays it on the grid, in Listen and on the sound
  port. Settings has a switch for it. The files read are kept only while the bench runs, unless Keep a loaded
  track's audio is on.
- A bench deck takes the load-track command that rekordbox or Beat Link sends a player, and refuses it while it plays.
- A bench deck's header is a player's: it opens to all of it, with where its track comes from, its grid and its audio
  on a line of their own and the state under. Opening moves neither the number nor the name. The state is in one order
  on both, ON AIR first, and the folded tags are at the right with their rows balanced. A bench deck shows MASTER and
  SYNC there too. When the tags wrap, their box narrows to its widest row, and the name and the track take the room.
- A bench deck's CUE works as a real player's on the page: held, it plays from the cue point, and let go on PLAY
  it plays on (PLAY pressed while CUE is held plays on, as on a CDJ). Both kinds of deck say PLAY or PAUSE by what
  the deck does, and PLAY while CUE is held.
- Load a track takes one kind of track at a time. A player's track fills in its player, slot, ID and title and
  clears the sound file. A sound file puts the database back to the deck's own. The track picked stays shown, and
  Clear empties the form.
- A deck's sound file no longer crackles in Listen. The page started it again at every change of the deck's phase,
  with no fade: each time a synced deck was put back on its beat and each step of the pitch fader. It now plays on
  when it is within 40 ms of the deck, takes a new tempo as a new speed, and fades over a jump.
- Listen says what it waits for when nothing plays yet, and that a real player is heard as a beat, not its music.
- A bench deck no longer logs every beat of every player. On Windows its socket for commands also gets the broadcasts
  of that port (beats, the mixer's on-air report, position, fader start), and each was logged. They are left to the
  packet log now, and a packet of another kind is logged once for each sender.

### Scenarios

- A scenario can play real players: a `player` step presses a button (CUE held for a while too) or loads a track on a
  player by its number, with Player control on, and `expect_player` checks what that player says of itself. An example in the new Real players group cues,
  plays, pauses and syncs player 1.
- The Scenario tab has a Clear button for the results of the last run, as Events and the link log have. It waits for a
  run to end or be stopped.

### The page

- **Phone**, at the top of the page on the bench's machine, shares the bench with phones on demand: it listens on an
  address of the local network too, with a token of its own, and shows the QR code and the link in the page. **Stop
  sharing** closes it. Started with `--phone`, the button shows the existing link and QR. `--phone-address` now also
  sets the address the button offers first.
- The Phone button is lit whenever the bench is shared with phones, from the start with `--phone` too. It was lit only
  once its dialog had been opened.
- A page that a phone suspended (another app, the screen off) reconnects when it comes back. The browser had closed
  its stream for good, so it said reconnecting until the page was reloaded. The page now opens a new stream when its
  stream is closed, quiet for 5 seconds, or quiet when the page is shown again.
- Cards can be put in another order: drag one by the grip at its top (or move it with the arrow keys) within its grid,
  the bench decks or the real players. The order is kept in this browser, and Settings, Appearance, Card order resets it.
- Settings, Appearance, Cards per row sets how many cards sit side by side, 1 to 4, or as the width allows (the default).
- The Classic look in light shows the strips again: their waveform, numbers and playhead were drawn dark on its dark
  display.
- The link log keeps its height in a short window, such as at a high display scale: it had shrunk to a thin line.
- Text on the cards can be selected and copied: the page no longer rewrites text that did not change.
- Keep the network adapter's remember-choice checkbox beside its natural-width label.

### Networks and other programs

- `--feed [HOST:]PORT` watches the link through the packets another program forwards to that UDP port, as captures
  keep them, binding and sending nothing on the link: for a computer where that program holds the Pro DJ Link ports.
- The optional DJS-1000 emulator adapter stays connected when a project name is reported.
- A bench on a real network in Linux or WSL starts again. It stopped while reading the adapters' MAC addresses,
  which it never found there, and on an adapter without one.
- Choose the backend's DJ network adapter from the browser Network panel.
  Reconnect an idle bench without restarting its HTTP server, with explicit
  reset of discovered identities and armed controls and recovery on bind failure.
  Remember adapter choices as suggestions without changing CLI startup behavior.
- Keep manual `--bind` receivers unfiltered and require a distinct mixer address
  after switching to a real adapter. Release the reconnect guard after CLI
  scenarios finish, and prevent reconnecting unavailable remembered adapters.
- The Windows firewall helper takes several adapters, such as a DJ adapter and the network bridge
  another program makes of it, and covers each with one rule.
- List a Windows network card whose address is not usable yet (Tentative) in the adapter
  choice, marked as such, instead of hiding it. It cannot be chosen until Windows marks it Preferred.
- Say in one line which port is busy when the page or the sound cannot start, instead of a traceback.

## v0.5.0

### Compatibility changes

- Plain CLI sessions no longer automatically select devices named DJS- as the
  test target. Pass `--target PLAYER|IP` for `/api/unit`, `unit_*` events and
  unit scenarios. Existing Python defaults and the explicit emulator adapter
  keep their previous target behavior.
- Clearing Events no longer resets event timestamps. Times remain relative to
  session start, matching Network capture. Event numbering still restarts on
  clear. Use `session` and `generation` to distinguish histories.

### MASTER, SYNC and player controls

- Serialize automatic MASTER handoffs with explicit requests and skip device snapshots when no handoff is needed.
- Reconcile early MASTER commands with the sender's late status through a coordinated handoff.
- Decode acceptance in standard-length master takeover replies.
- Add opt-in SYNC and MASTER commands on discovered player cards.
- Hand a stopped virtual master's role to an eligible playing, synced follower.
- Add opt-in fader-start transport controls for discovered players without enabling the simulated mixer.
- Explain that hardware fader-start commands require a stopped player at cue to start and a playing player to return to cue.
- Keep delayed simulated-mixer packets from restoring on-air state after the mixer is switched off.
- Make the demo's observed synced player follow master tempo and bar phase, with matching packet-log values.

### Observation and diagnostics

- Add an announced observer mode without simulated playback decks or database servers.
- Clear an observer's number-conflict warning when the conflict ends, without discarding other network errors.
- Add continuous UDP capture, a full retained-capture export and explicit view limits.
- Keep Events and Network on one session clock and reset replayed history on reconnect.
- Report external-player state changes and allow an explicit test target without auto-selecting a DJS.
- Record incoming database queries for hardware troubleshooting.
- Decode mixer tempo status and CDJ-3000 precise positions without inventing beat grids.
- Query loaded-track metadata on demand and serve meaningful synthetic tempo and duration fields.
- Export full packet payloads and replay captures offline with seeded loss, delay and jitter.

### Platform support and reliability

- Add native macOS interface and MAC discovery, a dedicated CI job and Ethernet/VM bridge setup guidance.
- Print a usable browser URL with the actual port and token, including in phone mode.
- Bound listener waits during shutdown and use a configured localhost address for the Mac mixer endpoint.
- Add explicit network worker shutdown, socket cleanup and cancellable handoff timers.
- Isolate CLI sleep mocking so checks cannot interrupt other network workers.
- Make the startup-error test own its conflicting port without a timing-sensitive helper process.

## v0.4.0

### Phone access and setup

- Add phone pairing links and optional QR codes with `--phone`.
- Select the wired DJ adapter with `--dj-interface` and inspect available interfaces with `--network-info`.
- Add a Windows firewall helper with scoped installation, inspection and removal.
- Clarify browser connectivity, DJ network addressing and optional second-adapter setups.

### Real-device interoperability

- Support MASTER and SYNC handoffs between simulated decks and physical players.
- Use actual adapter MAC addresses and send player status directly to discovered peers.
- Fix compatibility fields associated with older-firmware warnings and advertise no shared USB or SD media.
- Show broadcast tempo and beat position without enabling a simulated deck.
- Treat physical DJS-1000 units as normal players unless an emulator test adapter is configured.

### Beat display and browser audio

- Align physical-player beat grids and retain loop shading across loop wraps.
- Show a compact master beat reference above each deck's beat indicators.
- Support browser audition of broadcast-only beats and explain unavailable or suspended audio.

### Network tools

- Keep the visible log stable with Follow off while packets continue collecting.
- Preserve text selection and export held rows when the view is frozen.
- Clearly distinguish simulated mixer controls from discovered physical mixers.

## v0.3.0

191 tests pass on Windows with Python 3.10. The GitHub Action passes on Ubuntu and Windows with Python 3.8 and 3.12.

### Packaging and reliability

- Installed packages include adapters, with an isolated CLI and asset check.
- The sampler phase check establishes status-before-beat ordering across UDP
  ports instead of depending on thread scheduling.
- CI keeps full verbose logs and uses fixed OS images without automatic retries.
- The README is shorter, with CLI and API detail in `docs/reference.md`.

### The page

- Play is play and pause: a deck that pauses stays where it is and plays on from there (it used to start again from its first beat). A deck is at its
  first beat when its track is loaded.
- CUE, as a CDJ has it: while playing it goes back to the cue point and pauses, held on the cue point it plays until let go, paused elsewhere it sets the
  cue point. `POST /api/deck/<n>/cue[/<1|0>]`. The status says `cued` and `cue playing` besides `paused` and `playing`.
- The deck's number is its on / off switch, and the ON button is gone.
- A deck that is off shows only its number and its name, so the page is not mostly dimmed controls. Its card is as tall as that, not as tall as the decks that are on.
- The header says what each sound is for: the chip `unit input` is the port the decks' sound is served on for a unit, and the button `Listen` plays it in the browser (it was `Sound`).
- A chip `recording a session` shows while a journal is kept (see `docs/link.md`).
- A message that something went through (a file sent, a scenario kept or copied) has a green outline, like a deck that is on. The red outline is for errors, and there is a yellow one for a warning (`toast(text, "warn")`).

### Cue, loops and moves on the grid

- CUE and a loop go to the nearest beat, before or after where the deck is (a loop started 0.3 beats late used to start on the beat before, and a cue was
  wherever it was pressed). A deck that sets its cue is on it, so CUE held there plays from it.
- The deck can be moved in its track: `POST /api/deck/N/seek/BEAT` and `jump/BEATS` (negative goes back), and a Move row on the page: to the first beat, and
  a bar or four bars back or forward. A cue set late in a track could not be left before. A loop that is set stays through a move: waited for
  when it is ahead, gone round when the deck is in it, left behind (still marked) when the deck is moved past it.
- A pause stops where the playhead was when the page was clicked. The page sends the moment of the click (`?at=`, in the bench's clock), so a request that is slow
  to arrive (a bench across WSL) no longer makes the deck run on, or the strip jump, before it stops.
- A loop that is set is drawn ahead of the playhead, with the chip "LOOP 4 in 1.4 beats", and on a stopped deck too (it only showed once the deck was in it).
- The strip and the page's sound no longer jump forward by a tenth of a second or so when play or cue is pressed. The answer to a click comes by another road than the
  stream, and a quicker one moved the page's idea of the bench's clock half way at once. It now moves by 5 ms at most for each state.

### The unit's input is one deck

- `POST /api/audio/source/<n|all>` makes the sound port play only deck n, or all the decks again, while the bench runs (`--audio-decks` still sets the decks it is
  started with). The state says which in `bench.audio_source`, the page's "unit input" chip shows it, and a journal keeps it. The DJS-1000 emulator's deck calls it when
  the INPUT SOURCE knob of LIVE SAMPLING is turned.

### Sent files are kept

- The files the page sends with Browse are kept between runs in `~/.deckbench/tracks` (`--tracks-dir`, `$DECKBENCH_TRACKS`), named by a hash of their contents, so the same
  file is one file and a path a session recorded is found again. They used to be in a temporary folder that was only removed when the bench exited by itself, and was left behind
  when it was stopped (`pkill`, the emulator's `start.py stop`).
- Files unused for a month are removed at the start, and the oldest when the folder passes 2 GB. A file a deck has loaded stays. `--clear-uploads`, `POST /api/uploads/clear` and
  a button in the page's Settings empty it, and `GET /api/uploads` says what it holds.

### A journal of a session

- `POST /api/journal/start` begins keeping every request that changes the decks, with its time, after a baseline of requests that would put
  the decks where they are. `POST /api/journal/stop` answers both. A program that records a session (the DJS-1000 emulator's REC) keeps it and
  sends it again to a bench to play the session back. See `docs/link.md`.

### Tracks of your own

- A deck can play a sound file instead of its drum loop: `--track DECK=FILE@BPM[@START]`, the page's "Load a track" fold, or
  `?audio=` on the load request of the API. You say the BPM it was made at, and the deck plays it at its own tempo. See `docs/audio.md`.
- A deck that plays a sound file has its waveform behind its strip's beat grid, laid out from the BPM and the first beat you gave, so that a wrong
  one is seen. It comes from `/api/deck/N/waveform`.
- The strips no longer jump a few pixels now and then. The page took the bench's clock from each state as it arrived, so the delay of that message (a few milliseconds, more through WSL) moved them. It now follows the quickest messages and ignores the slow ones.
- The waveform is one smooth shape, with the loudness taken between its values, and does not shimmer as the strip scrolls.
- The bench's server keeps a queue of 128 connections instead of 5. A page that opened its event stream and a dozen requests at once, with
  something else asking too, could have one held back a second, or refused through WSL's forwarding of localhost, and said "The bench does not answer."
- The page's Sound button plays a deck's file when it has one (it played the drums of every deck). It is fetched from `/api/deck/N/audio.wav`.
- The page's Browse button opens the browser's file picker and sends the file to the bench (`/api/upload`), so a bench in WSL or on
  another machine gets a file from the one the browser is on.

### Testing from code

- The bench says when every socket it listens on is bound, and `start()` and the command line wait for that, so a bench is
  listening when `start()` returns. The monitor counts the packets it reads, so a test sends a marker on each port and waits
  for it instead of sleeping.
- A test that is beaten to a port (the system hands the range's ports to client sockets) takes the next range and starts again.
- A player is heard once its keep-alive has come as well as its status. The keep-alive says who it is, comes on another port and
  can come later.

### Fixes

- A DJS-1000 on the link has its beat strip follow the beat of its bar. It sends 0 for the beat in the track, which the page kept as a place, so the strip stood on one beat.
- The state of another device on the link (MASTER, SYNC, ON AIR, LOOP, OFFLINE) is side by side, right under the UNIT UNDER TEST tag, as tall together as the number's box. When there are too many for the width they wrap onto a row under. A flag that comes or goes does not change the card's height.

## v0.2.0

Tested on Ubuntu and Windows, with Python 3.8 and 3.12. The GitHub Action passes on all four.

### Listen to the network

- The bench now hears other players and mixers on the link and shows each as a read-only card with its model and what it does.
- The Network tab has a log of the Pro DJ Link packets as they come (`/api/packets`). The bench's own packets, statuses and beats are options. See `docs/link.md`.
- A synced deck now snaps to the master's beat grid, not only to its tempo.

### The page

- New look, the same as commitcollective.cc: black and white, thin lines, square corners. Colour only carries meaning: green for on and on air, blue for sync, amber for the master, purple for a loop, red for beat 1 and for a fault.
- Two looks, each in dark and light, chosen in Settings: Commit (the default) and Classic, the first look.
- Each deck and device has a scrolling strip with a grid of beats and bars. A loop shows where it goes back.
- The tempo slider changes the tempo while you drag it, not on release.
- The Sound button plays each playing deck's beat (kick, snare, hat). With a mixer, only decks on air are heard. Settings choose which decks and devices you hear.
- The page can be hosted on another site and used from a phone. See `docs/phone.md`.
- `?demo` runs a bench made of JavaScript inside the page, with no server.

### Safety

- The API now refuses requests from web pages of another origin, since any site could otherwise drive a bench on localhost. `--allow-origin` lets one in.
- `--token` makes the API ask for a token.

### Releases and hosting

- A tag now makes a GitHub release with the changelog entry as its notes.
- The tests run on Ubuntu and Windows, and the workflow says which test failed.
- The page is served by its own Cloudflare worker, so changing it needs no push to the website. See `docs/hosting.md`.

### Fixes

- UDP sockets are shared with SO_REUSEPORT on macOS.
- The page's server no longer does a reverse lookup at start, which held it up for many seconds on a macOS runner.
- The WSL test of `Bench` only runs where a WSL distribution starts.
- The mixer's channel rows no longer share a CSS class with the beat strips.

## v0.1.0

The first version.

### Simulated decks

- Pro DJ Link decks with discovery, status, beats, tempo master, sync and hand-off, loops, and the database server for track titles.
- `--profile` makes the decks stand in for a CDJ-2000 (nexus), CDJ-2000NXS2, XDJ-1000MK2 or CDJ-3000, with its name, status length and nexus byte.
- A deck can load a track from another deck's database and slot.
- `--claim` makes a deck do what a real player does when it comes online. A deck that is on defends its number against another device.
- Strict decks behave as a CDJ-2000NXS2 does.
- A simulated DJM mixer (`--mixer`) announces itself as device 33, reports which channels are on air, and starts and stops players with fader start.
- Each deck has sound.
- Network faults can be simulated, for example 30 % packet loss.

### The page and the API

- A card for each deck: switches, beat squares, tempo display and slider, loops, cable, and a track from any deck's database.
- Tabs for events (filter, pause, export), scenarios (editor, examples, saved), the network and the settings. Works in light and dark.
- An HTTP API and a command line drive the same things.
- Some settings change while it runs (`/api/settings`): strict decks, database refusal and the model name.

### Scenarios

- Scenarios script the decks and check what the device under test did.
- `expect_unit` checks its master role, sync, tempo and lamps. `expect_deck` checks the decks.
- `unit` presses its controls, `when` acts only in a given state, and `require` says what the scenario needs. A scenario that needs a unit or adapter that is missing is skipped, not failed.
- Matchers: `near`, `min`, `max`, `in`, `not`.
- `--scenario` takes several files or a folder and ends with a summary.
- Examples are in `deckbench/examples`.

### Testing a DJS-1000

- `--adapter djs1000-emu` reads the emulator's lamps and presses its SYNC and MASTER. The Network tab shows the unit's state with buttons.
- A library of scenarios in `deckbench/examples/unit`: the unit follows a master deck and its tempo, the master role passes between deck and unit, and it keeps following after a cable pull and with 30 % packet loss. `40-on-air.json` checks that the unit says it is on air when the mixer's channel 1 is open.
- More of the unit is heard: synced, playing, on air and the beat, with `unit_sync` and `unit_play` events.

### Running it

- `--port-shift` moves every port of the decks. The bench names the port it cannot have when it starts.
- `--ready-file`, `GET /api/ready` and `deckbench.testing.Bench` start a bench from a test without guessing a delay.
- Runs on Linux and Windows with Python 3.8 and later. The tests use ports of their own, so a running bench or rekordbox does not matter.
- Not supported on macOS: the loopback carries no broadcasts, so decks on 127.0.0.n are not heard. Use `--bind` there.

### Fixes

- A title with a percent sign is no longer decoded twice.

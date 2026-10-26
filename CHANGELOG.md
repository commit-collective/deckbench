# Changelog

Newest first. A release is a tagged commit.

## Unreleased

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
  a bar or four bars back or forward. A cue set late in a track could not be left before. A loop ends on a move.
- A pause stops where the playhead was when the page was clicked. The page sends the moment of the click (`?at=`, in the bench's clock), so a request that is slow
  to arrive (a bench across WSL) no longer makes the deck run on, or the strip jump, before it stops.

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

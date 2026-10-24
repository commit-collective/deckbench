# Changelog

Newest first. A release is a tagged commit.

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

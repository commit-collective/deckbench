# Scenarios, faults and events

A scenario is what the decks do, and what to expect of the device under test, on a timeline. It makes a test of a unit or an
emulator the same each time, and it is the way to see how they take what a real network does: a track that changes, a tempo
that moves, a cable that is pulled.

    python -m deckbench --scenario loop-and-stop.json --then-exit

plays it once the bench runs and, with `--then-exit`, leaves when it is over with status 1 if an expectation failed. `--scenario`
can be given again, or a folder, to play a suite in order: the status is 1 if one failed, else 3 if one was skipped, else 0.
Without it the bench goes on, for the page and the API.

## The file

JSON (the standard library reads it, there is nothing to install): `{"name": ..., "steps": [...]}`. A step has `at` (seconds
from the start), `do`, and what the action needs. `deck` is the player number.

    {"name": "a loop and a stop",
     "steps": [
       {"at": 0,   "deck": 2, "do": "on"},
       {"at": 0.5, "deck": 2, "do": "play"},
       {"at": 4,   "deck": 2, "do": "loop", "beats": 4},
       {"at": 8,   "deck": 2, "do": "load", "id": 205, "title": "Another track", "bpm": 124},
       {"at": 12,  "deck": 2, "do": "tempo", "bpm": 126},
       {"at": 14,  "deck": 3, "do": "silence", "seconds": 3},
       {"at": 18,  "do": "loss", "percent": 20},
       {"at": 20,  "do": "expect", "event": "fader_start", "within": 5, "match": {"deck": 2, "action": "stop"}}
     ]}

| action | what it does |
|---|---|
| `on`, `off` | the deck is switched on or off |
| `play`, `stop` | it plays from the first beat of its bar, or stops |
| `sync`, `unsync` | it syncs to the master, or not |
| `master`, `release` | it takes the tempo master role (from the unit, if the unit has it) or lets go of it |
| `loop` (`beats`), `unloop` | a loop of that many beats from the beat it is in, or none |
| `load` (`id`, optional `title` and `bpm`) | a track: its rekordbox id, from the deck's own database, with that title. It starts from its first beat |
| `tempo` (`bpm`) | the pitch fader: the deck plays at that tempo |
| `unplug`, `plug` | the cable is pulled: the deck says nothing and answers nothing, until it is plugged in |
| `silence` (`seconds`) | unplugged for a while, then plugged in |
| `loss` (`percent`) | that share of the datagrams of all the decks is lost (0 for none) |
| `log` (`text`) | a line in the log |
| `expect` (`event`, `within`, `match`) | an event of the device under test is there within `within` seconds (5 by default) |
| `expect_unit` (`match`, `within`, `for`) | what is known of the device under test matches within `within` seconds (5), and then for `for` more seconds if it is given |
| `expect_deck` (`deck`, `match`, `within`, `for`) | the same for a deck: `on`, `play`, `sync`, `master`, `bpm`, `loop`, `unplugged`, `track_rbid`... (`within` is 2 by default) |
| `unit` (`press` or `send`) | press a control of the device under test through an adapter, or send it a raw line |

`load` can also take `source` (the player whose database the track is in) and `slot`.

On the page: the **Scenario** tab has the JSON in an editor that says what is wrong with it and where, the examples that come with
the bench (`deckbench/examples`, which `--scenario` plays too), the scenarios kept in the browser, OPEN and DOWNLOAD for files, RUN and
STOP. It shows a progress bar and lists each step as it is done, with the expectations that failed. The API behind it is `POST /api/scenario` (the
scenario as the body, 409 while one plays, 400 with the reason if it is not one), `POST /api/scenario/stop` and `GET /api/scenario`.

The same things can be done by hand: the page's API ([README](../README.md)) has them, and `Scenario.run(world)` plays one from
Python.

## Expecting things of the device

`expect_unit` and `expect_deck` take a `match`: a dictionary of key and wanted value. A wanted value is a plain value (equal to
it) or one of these:

| | |
|---|---|
| `{"near": 128, "tol": 0.5}` | a number within `tol` (0.5 by default) of it |
| `{"min": 100, "max": 140}` | a number in that range (an end can be left out) |
| `{"in": [1, 2]}` | one of them |
| `{"not": 3}` | anything but it, also when the key is not known |

What is known of the device is the network's word (`heard`, `master`, `synced`, `playing`, `bpm`...) and what an adapter adds
(`lamp.sync`...): the list is in [adapters.md](adapters.md). A key that is not known never matches. When an expectation fails the
message says what was wrong: `bpm is 126.0 (wanted near 130 +-0.5)`.

Any step can have `when`, a match against the device: the step is done only if it holds at that moment. It brings a device that
keeps its state to where a scenario starts: `{"do": "unit", "press": "sync", "when": {"synced": true}}`.

A scenario can say what it `requires`: `"unit"` (the device has announced itself on the link, waited for up to `unit_wait`
seconds, 10 by default) and `"adapter"` (an adapter is connected, waited for just as long). When one is missing the scenario is
skipped and not failed. The page says so, and the command line ends with status 3.

## Events

The bench writes down what it sees the device under test do. An event is a JSON object: `n` (its place, from 0), `t` (seconds
since the bench started), `kind` and what the kind adds.

| kind | when | what it adds |
|---|---|---|
| `unit_seen` | the unit announces itself with a player number | `number` |
| `unit_master` | the unit takes or leaves the tempo master role | `on` |
| `unit_sync` | the unit's sync flag turns on or off | `on` |
| `unit_play` | the unit starts or stops playing | `on` |
| `fader_start` | a fader start packet starts or stops a deck | `deck`, `action` (`start` or `stop`), `sender` |
| `sync_command` | the unit tells a deck to sync, unsync or become the master | `deck`, `command`, `sender` |
| `handoff_request` | the unit asks a deck to yield the master role | `deck`, `sender`, `granted` |
| `db_connect` | something connects to a deck's database | `deck`, `requester` |
| `db_ignored` | a strict deck gave it no answer | `deck`, `requester` |
| `metadata_request` | something asks a deck for a track's title | `deck`, `requester`, `rbid`, `answered`, `title` |

`GET /api/events?since=<n>` lists them, `--events FILE` writes them as they come (a JSON object a line), and in Python
`world.events.wait("fader_start", timeout=2, deck=2, action="stop")` waits for one.

## Strict decks

Real CDJ-2000NXS2 and XDJ-1000MK2 players serve the database to the players 1 to 4 and no others, and they turn the requests
of a device that is not a player they know down. `--strict` does the same: a device with another number (a fifth one) gets no
answer at all, and the unit under test is answered only if it announced itself with the number it asks as. A DJS-1000 in drum
machine mode has no number on the link, so a deck turns its requests down: with `--strict` a mod that reads track titles has
to cope with that (the DJS-1000 mods name the take after the deck instead).

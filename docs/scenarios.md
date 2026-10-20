# Scenarios, faults and events

A scenario is what the decks do, and what to expect of the device under test, on a timeline. It makes a test of a unit or an
emulator the same each time, and it is the way to see how they take what a real network does: a track that changes, a tempo
that moves, a cable that is pulled.

    python -m deckbench --scenario loop-and-stop.json --then-exit

plays it once the bench runs and, with `--then-exit`, leaves when it is over with status 1 if an expectation failed.
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

The same things can be done by hand: the page's API ([README](../README.md)) has them, and `Scenario.run(world)` plays one from
Python.

## Events

The bench writes down what it sees the device under test do. An event is a JSON object: `n` (its place, from 0), `t` (seconds
since the bench started), `kind` and what the kind adds.

| kind | when | what it adds |
|---|---|---|
| `unit_seen` | the unit announces itself with a player number | `number` |
| `unit_master` | the unit takes or leaves the tempo master role | `on` |
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

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
| `mixer` (`on`, `master`, `channel` with `fader`, `fader_start` or `command`) | the simulated mixer: switch it on, put its master level up or down, move a channel's fader (0 to 100), turn its fader start on, or tell its player to `start` or `stop` (see [mixer.md](mixer.md)) |

| `player` (`player`, then `press` or `load`) | a real player on the network, by its number, with Player control on in Settings: `press` one of its buttons (`play-pause`, `cue`, `sync-on`, `sync-off`, `master`, or `start` and `stop` for fader start), `cue` with `hold` (seconds) to keep CUE down that long, or `load` a track by its rekordbox id from `source` (the player whose media has it, the player itself by default) and `slot` (`usb` by default, or `sd`) |
| `expect_player` (`player`, `match`, `within`, `for`) | what that player says of itself: `play`, `sync`, `master`, `on_air`, `state`, `loop`, `bpm`, `pitch`, `bar`, `rbid`, `online`... (`within` is 5 by default) |

`load` can also take `source` (the player whose database the track is in) and `slot`.

A `player` step is sent, never confirmed: the player may ignore it (a button it does not take, a track it is playing, CUE
or PLAY with no track loaded), so follow it with an `expect_player` when the result matters. A `load` is sent from a bench
deck: players take one only from a player 1 to 4, so a bench deck with a number from 1 to 4 that no real device uses must
be on. With four real players there is no such number, and a scenario can only press the buttons of tracks loaded by
hand. Its button presses work on the
CDJ-2000NXS2 and XDJ-1000MK2 (see [link.md](link.md)). A step with `hold` lasts as long as the hold, and the steps after it
wait for it. The **Real players** group of the examples has one that cues, plays, pauses and syncs player 1. For example, a
player loads a track from its own USB, cues and plays, and the scenario checks that it plays. Here 205 stands for a
track's rekordbox id on that USB: a player's card shows the id of the track it has loaded, as `rbid` in its status.

```json
{"name": "a real player plays a track",
 "steps": [
   {"at": 0,  "do": "player", "player": 2, "load": 205},
   {"at": 3,  "do": "expect_player", "player": 2, "match": {"rbid": 205}},
   {"at": 4,  "do": "player", "player": 2, "press": "cue", "hold": 2},
   {"at": 7,  "do": "player", "player": 2, "press": "play-pause"},
   {"at": 7,  "do": "expect_player", "player": 2, "match": {"play": true}, "within": 3}
 ]}
```

On the page: the **Scenario** tab has the JSON in an editor that says what is wrong with it and where, the examples that come with
the bench (`deckbench/examples`, which `--scenario` plays too), the scenarios kept in the browser, OPEN and DOWNLOAD for files, RUN and
STOP. It shows a progress bar and lists each step as it is done, with the expectations that failed. CLEAR empties that list once the run
ends. The API behind it is `POST /api/scenario` (the scenario as the body, 409 while one plays, 400 with the reason if it is not one),
`POST /api/scenario/stop`, `POST /api/scenario/clear` (409 while one plays) and `GET /api/scenario`.

The same things can be done by hand: the page's API ([README](../README.md)) has them, and `Scenario.run(world)` plays one from
Python.

## Recording a mix

RECORD MIX, in the Scenario tab, records what the real players do until it is pressed again. The recording becomes a
scenario that does it again on the same players: it is put in the editor and kept in this browser under its name. The
bench's own decks and the device under test are left out.

A replay begins with a setup. Each player is checked: on the link, the same model, stopped. Each loads the track it had
when the recording began, and SYNC and MASTER are set as they were. The recorded changes follow, each a `player` step
then an `expect_player` that checks it, at their seconds after the start of the recording plus the setup's 12 seconds:

- a track loaded, from the same player's media and slot. A track from rekordbox on a computer, or from a CD, cannot be
  loaded by the bench: it is noted, for loading by hand
- PLAY, a pause, CUE pressed or held. A model that takes no button presses but has fader start (an older CDJ) gets
  its START and STOP instead, and its pauses become a return to the cue, as STOP does. A model with neither is noted
- SYNC on or off, MASTER taken

A PLAY pressed while another player was the tempo master and playing keeps its place on the master's beat: it becomes
a step `on_beat` that beat of the master's bar, sent half a bar before its time, so it lands on the beat nearest to
where it was even if the tempo is not quite the same. Which beat it was is read from the players' statuses, which
come five times a second: a PLAY pressed far from a beat may be put on the next one.

On a CDJ-2000NXS2 or XDJ-1000MK2, Record Mix keeps the exact loop, hot cue, beat jump, Quantize and Slip commands sent from the card or API.
Replay checks the track, plus the active-loop state for loop buttons. It also checks a loop start or exit when the
recording saw that change. The active flag cannot verify a resize or whether an exited loop is saved.

Physical presses that show up only as an unexplained loop or jump, pitch moves and ejects become timed `log` steps and
notes. A track starts from its cue or first beat when loaded, and a player that started elsewhere is noted.
Mixer faders and EQ are done by hand.

A track's title and artist go with its load when the bench has read them (Read track info, or a player's card). When a
mixer on the link reports which channels are on air, each change is noted too, "player 2 on air", for bringing its
fader up by hand. After a PLAY done on a beat, the check that follows says how far the player's beats came from the
master's, in milliseconds (`phase_to`): if they come late every time, `"early"` on the `on_beat` can make up for it.

Before a scenario with real players runs, RUN asks the bench whether everything it needs is there: each player and its
model, Player control, the presses each model takes, stopped players, a bench deck to send loads from, and each track
on its player's media, with its title compared to the recording's. What is not ready is listed under the scenario's
status, and it runs only if asked to anyway. `POST /api/scenario/check` does the same with the scenario as its body.

Replaying needs what any `player` step needs: Player control on, and for the loads a bench deck with a number from 1 to
4 that no real player uses. The media must hold the same tracks with the same ids. The setup's checks are `required`:
when one fails (a player missing, another model, a track that does not load) the replay ends there. Later, an
expectation that fails says where the replay went another way, and the replay goes on.

A capture of the link gives the same scenario offline: `python -m deckbench.mixrecord CAPTURE.json --out mix.json`
reads Export capture's file or what `--capture` wrote. The API is `POST /api/mix/start`, `POST /api/mix/stop`, which
answers `{"scenario": ...}`, and `GET /api/mix`.

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

An expectation can be `required`: when it fails, the scenario ends there, as one whose start is not right would only
go further wrong: `{"do": "expect_player", "player": 2, "match": {"online": true}, "required": true}`.

Any step can be done on a beat. `on_beat` names whose beat: `{"deck": 2}` (a bench deck), `{"player": 3}` (a real player)
or `{"master": true}` (the tempo master, a deck or a player), with `"beat": 1` to 4 for a place in the bar. When the
step's `at` comes, it waits for the next such beat, a bar at most, and is done on it. `"early": 20` does it that many
milliseconds before the beat, for a player that takes a moment to start. The beat is foreseen from the deck's place and
tempo, or from the player's last beat packet, not waited for. A deck or player that is not playing has no beat: the
step is done at once and says so.

```json
{"at": 16, "do": "player", "player": 2, "press": "play-pause", "on_beat": {"master": true, "beat": 1}}
```

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
| `on_air` | a deck is told it is on air or off it (by the bench's mixer or another) | `deck`, `on`, `sender` |
| `number_defended` | a deck told another device that the number is in use | `deck`, `claimer` |
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

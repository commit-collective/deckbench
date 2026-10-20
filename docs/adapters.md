# Adapters: seeing the device under test from the inside

The bench sees a device by what it sends on the link: its keep-alives and statuses. That tells it the unit's player number,
whether it is the tempo master, whether it plays or is synced, and its tempo. It does not tell it what the device shows or
what a button does. An adapter adds that. With one, a scenario can press a control of the device and expect a lamp to be lit.

    python -m deckbench --adapter djs1000-emu --scenario deckbench/examples/unit --then-exit

## What a scenario can say

`expect_unit` waits until what is known of the device matches (see [scenarios.md](scenarios.md)). What is known is the
network's word and each adapter's, in one flat dictionary:

| key | where from | meaning |
|---|---|---|
| `heard` | the network | the device has announced itself with a player number |
| `number`, `ip` | the network | its player number and address |
| `master`, `synced`, `playing`, `on_air` | the network | the flags of its status |
| `bpm`, `track_bpm`, `pitch`, `pitch_percent` | the network | the tempo it plays at, its track's tempo, and the pitch (0x100000 is none) |
| `beat` | the network | the beat of its bar, 1 to 4 (0 before it has sent a status) |
| `age` | the network | seconds since its last status |
| `adapter.connected` | an adapter | the adapter reaches the device |
| `lamp.sync`, `lamp.master` | `djs1000-emu` | the lamp is lit (`lamp.sync_level` is 0 off, 1 dim, 2 bright) |

`GET /api/unit` gives the same, and the page's Network tab shows it with a button for each control.

## The adapter for the DJS-1000 emulator

`djs1000-emu[:HOST:PORT]` connects to the emulator's link, the TCP port its virtual deck uses (127.0.0.1:7310 by default).
It reads the lamps from the frame the app sends its panel and presses a button by sending the panel the same
`tap <byte> <bit>` the virtual deck does. Its controls are `sync` and `master`. The bench and the emulator must see each
other's loopback, which is the case in WSL, where the emulator runs.

The library in `deckbench/examples/unit` uses it. Each scenario starts from a known state (every deck off, nobody the master,
the unit's SYNC off), because the unit keeps its state, and a deck can only take the master role from it (its MASTER button
does not let go). They check that the unit follows a master deck and its tempo changes, that the master role passes from a
deck to the unit and back, and that the unit keeps following after a cable is pulled and with 30 % of the packets lost. Run
them from the emulator's side:

    python3 -m deckbench --numbers 2,3,4 --adapter djs1000-emu --scenario deckbench/examples/unit --then-exit

The exit status is 1 if an expectation failed, else 3 if a scenario was skipped (the unit was not on the link, or the adapter was
not connected), else 0.

## Writing an adapter

An adapter is a class in `deckbench/adapters/`, named in `make()` in `deckbench/adapters/__init__.py`:

    from . import Adapter

    class MyDevice(Adapter):
        name = "my-device"
        controls = ("play", "cue")          # the names press() takes

        def __init__(self, args=""):        # what comes after the colon in --adapter my-device:ARGS
            ...
        def start(self, world):             # begin: a thread, a connection. It must not block
            ...
        def connected(self):                # whether it reaches the device
            ...
        def state(self):                    # a flat dict of what it knows now, keys like "lamp.sync"
            ...
        def press(self, control):           # (True, "") or (False, why)
            ...
        def send(self, line):               # a raw command, for what press() does not name (optional)
            ...
        def stop(self):
            ...

Keep `state()` quick, it is read every 50 ms while a scenario waits and every 100 ms by the page. Leave out the keys it cannot
tell (a lamp when the device is away) instead of guessing, since an expectation about a key that is not known does not match.
`tests/test_unit.py` has a small fake of the emulator's link that shows how to test an adapter with no device.

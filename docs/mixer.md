# The mixer, and a player coming online

Two things a real Pro DJ Link network has that a bench of bare players does not: a DJM mixer, and the way a device joins
the network. Both are in the bench, off by default, and both follow Deep Symmetry's public analysis
([startup](https://djl-analysis.deepsymmetry.org/djl-analysis/startup.html) and
[mixer integration](https://djl-analysis.deepsymmetry.org/djl-analysis/mixer_integration.html)) and Beat Link's `VirtualCdj`.
Neither was compared with a capture of the bench's own packets against a real mixer. The analysis' hardware captures are
of CDJ-2000nexus players, so those are the packets used.

## The mixer

    python -m deckbench --numbers 2,3,4 --on --mixer              # a DJM-900NXS2 as device 33, on
    python -m deckbench --mixer "DJM-V10" --mixer-channels 6      # its name, and six channels

or the **Mixer** tab of the page (also `POST /api/mixer/on/1`). It is a device of its own at 127.0.0.33 (`--mixer-address`
for another address, which `--bind` needs). Channel N is player N.

| It sends | What | When |
|---|---|---|
| keep-alive, UDP 50000 | as a mixer: device 33, kind 02, the number of devices it knows | every 1.5 s |
| on air, UDP 50001 (type 0x03) | a byte for each channel: 1 on the air, 0 off | every 0.25 s and at each change |
| fader start, UDP 50001 (type 0x02) | a byte for each player 1 to 4: 0 start, 1 stop, 2 leave it | when a fader with fader start moves, or on a command |

A channel is **on the air** while the mixer's master level is up and the channel's fader is above 0. A channel with
**fader start** on starts its player when its fader opens and stops it when it closes. `Start` and `Stop` send the command by hand.

The decks listen. Their status says they are on air (bit 3 of the flags) as the mixer reports, and a deck stops being told
when the mixer goes off, after which it says it is on air while it plays, as it does with no mixer. A mixer that is not the
bench's does the same: the decks follow any on-air packet, six channel ones included. The unit under test (player 1) gets its
own channel's flag.

In a scenario:

    {"at": 2, "do": "mixer", "on": true}
    {"at": 2, "do": "mixer", "channel": 2, "fader": 100, "fader_start": true}
    {"at": 6, "do": "mixer", "channel": 3, "command": "stop"}
    {"at": 9, "do": "mixer", "master": false}

`expect_deck` can look at `on_air`, and the `on_air` and `fader_start` events say what the decks were told.
`examples/04-mixer-drives-the-decks.json` and `examples/unit/40-on-air.json` use it.

### Found with the DJS-1000 emulator

- The unit says it is on air (its status flag) when the mixer's channel 1 is open and the master up, and not when either is
  down, within about a second.
- It does not start when a mixer sends player 1 a fader start command. It is a unit in drum machine mode.
- It goes on following its tempo master when the master's channel goes off air.
- With no master, and two decks playing and synced, one on air and one not, pressing SYNC on the unit did not make it
  follow either. The firmware's choice of a deck to sync to ranks the decks by their flags (on air among them), but nothing
  here made it use that choice.

## A player coming online

A real player does not just send keep-alives. It sends, at 300 ms, three hellos, then three stages of claiming its number
(its address, its MAC address, the number, a counter) and only then keep-alives, every 2 s. The bench does so with `--claim`
(or the Settings tab), so a deck is on the network 3.6 s after it was switched on, not at once. Off by default, because
that is slow for a test that has no use for it. With the DJS-1000 emulator the unit picks up a deck that claims its number first, and its
statuses to the deck begin about 3.8 s after the switch.

The keep-alive also says how many devices the player knows (itself included) and, in byte 0x25, whether it was alone on the
network when it came online (02 if it was, 01 if not: latched for the session). The bench's decks count the decks that are on,
the mixer and the unit, and latch it as a player does.

A deck that is on **defends its number**: a stage 2, a stage 3 or a keep-alive from another address with its number
gets a "number in use" packet (type 0x08) sent to it, at most once a second, and a `number_defended` event. The unit under
test kept the number 1 when a deck on that number defended it twice while it started. The emulator may not pass a unicast
packet to the app, so this does not say what the unit's firmware does with it.

# Pro DJ Link in deckbench

The layouts are those of Deep Symmetry's public analysis
([djl-analysis](https://djl-analysis.deepsymmetry.org/)) and of its Java
library Beat Link, which is also what to read for what a player really sends
(`VirtualCdj.java`: `STATUS_PAYLOAD`, `sendStatus`, `becomeTempoMaster`).
Nothing is copied from either.

A deck is a CDJ at `127.0.0.<player number>`, broadcasting to `127.255.255.255`.

## What a deck that is on sends

| Port | Packet | When |
|---|---|---|
| UDP 50000 | keep-alive (type 0x06, 0x36 bytes): name, player, address | every 2 s |
| UDP 50002 | CDJ status (type 0x0a, 0x124 bytes by default) | every 200 ms |
| UDP 50001 | beat (type 0x28, 0x60 bytes): the beat in the bar, the tempo, the times to the next beats | at each beat while it plays |
| TCP 12523, 1051 | the database server: port query, greeting, query context, track metadata, render menu | on request |

A deck that is off sends nothing and closes what is opened to it.

### The status packet

Fields set (offsets in the packet): after the name, byte 0x1f is 01, 0x20 the
subtype 03, 0x21 and 0x24 the player, 0x22-0x23 the length that follows
(`len - 0x24`); 0x27 activity; 0x28 the player the track came from, 0x29 the
slot, 0x2a the track type (1, rekordbox), 0x2c-0x2f the rekordbox id; 0x7b the
play mode (3 playing, 5 paused); 0x7c firmware "1.00"; 0x84 the sync counter;
**0x89 the flags**; 0x8b the second play mode (0x7a/0x7e); the pitch, four
times (0x8c, 0x98, 0xc0, 0xc4); **0x90 the master-valid word (0x8000)**; 0x92
the BPM times 100 (the tempo it plays at); 0x94 no slip play; 0x9d the third
play mode; 0x9e master meaningful; 0x9f the hand-off target (0xff for none);
0xa0 the beat in the track; 0xa4 no cue point ahead; 0xa6 the beat in the bar;
0xc8 a packet counter; 0xcc 0x0f (a nexus player).

The flags (0x89): bit 6 plays, bit 5 master, bit 4 sync, bit 3 on air; bits 7
and 2 are always set, as on a real player.

## The tempo master

Between decks the role simply passes (only one is the master). With a hand-off
the outgoing master keeps saying it is the master and, in 0x9f, to whom it
gives the role, for a second, then lets go.

A deck that asks a player for the role sends a takeover request (type 0x26,
0x28 bytes) to port 50001 of the master. A deck that is the master answers
with a response (0x27) to port 50002 of the sender and names it in 0x9f in its
statuses. Sync commands (0x2a, command byte at 0x2b: 0x10 sync on, 0x20 sync
off, 0x01 become master) are obeyed.

## Found with a unit under test (Pioneer DJS-1000, firmware 1.22)

A unit that follows the tempo master has its own idea of what a deck's status
must look like. Each of these was found by the unit not reacting:

- **The header after the name**: bytes 0x1f-0x24 as above, with the length that
  follows. Without them the unit sees decks (it lists them as linked players)
  but does not follow one.
- **The master-valid word, 0x90, 0x8000.** The analysis says a master's tempo is
  accepted only then; the unit follows a master (its display says MASTER PLAYER
  n, shows the deck's tempo and beat, its SYNC lights) once it is set.
- **Bit 7 of the flags.** The analysis calls it unknown. Without it the unit,
  asked by a deck for the master role, agrees but never stops being the
  master; with it, it stops. Beat Link's own status starts from 0x84.
- **Taking the role from the unit**: the deck sends the request to the unit's
  port 50001; the unit answers (0x27, accepted) and names the deck in its
  hand-off field (0x9f) only if the deck's status says it is synced (flag 0x10),
  so while it waits a deck's status says so (its switch is not touched). When
  the unit does not hand over within 3 seconds (it is not a unit that does),
  the deck takes the role anyway.
- **The unit sends its status to a deck's own address** (UDP 50002), not to
  the broadcast, so a listener has to be bound to the deck's address: a socket
  bound to any address loses the datagrams to others bound to it too.
- **The BPM field is the track's, the pitch is the tempo change.** A unit's
  tempo slider moves the pitch (0x8c, 0x100000 is none, 0x200000 is +100%) and
  leaves the BPM field (0x92) alone, as a CDJ does; the tempo it plays at is
  the BPM times the pitch. The bench follows that (a deck synced to the unit
  as the master takes it).
- **A unit's takeover request is 0x28 bytes**, shorter than the status-sized
  packets: a deck must not drop packets shorter than 0x2c.

## Not done

- Decks on a real network: each deck is a loopback address, so a unit on a
  real network does not see them. A mode with a real address for each deck
  would.
- Many models: the status length and the name can be chosen (`--status-length`,
  `--model`), the contents are those of a nexus player.
- Beat grids, waveforms, cues and the rest of the database.

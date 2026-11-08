# Protocol expansion

This is a staged direction, not a compatibility promise or release schedule.
Keep working Pro DJ Link behavior stable while adding independently testable services.

## Validate the current additions

- Test announced observer mode on physical players without enabling a virtual deck
- Check on-demand track metadata against the source player's display
- Validate physical SYNC and MASTER commands and stopped-master handoff
- Check precise position and mixer tempo decoding against supported hardware
- Use local full-payload captures for repeatable decoder regressions
- Finish migrating older network fixtures to explicit worker cleanup

## Add StagelinQ separately

The goal is one bench for Pioneer and Denon ecosystem testing, not an automatic network bridge.
StagelinQ is not implemented yet. A useful first release should be read-only:

1. Add a bounded discovery codec and interface-scoped UDP discovery on port 51337
2. Implement cancellable directory connections and service discovery
3. Subscribe to StateMap and BeatInfo with bounded frames, reconnects and expiry
4. Normalize device and deck-layer state for the common UI and scenario assertions
5. Validate against real hardware before claiming support for specific models

Identity must include the protocol, device token and deck layer. An IP address or player number alone is not enough
for layered players or for mixed networks. Unknown timing stays unknown. Discovery alone is not live deck support.
Keep the backend optional and avoid adding a separate JavaScript or Java runtime solely for it.

No automatic cross-protocol MASTER/SYNC translation, remote playback or file transfer in this first scope.
Those need separate semantics, explicit opt-in and hardware validation. Shared display does not make the hardware
protocols interchangeable.

Protocol references: [StageLinq](https://github.com/chrisle/StageLinq),
[go-stagelinq](https://github.com/icedream/go-stagelinq) and
[stagelinq-js protocol notes](https://github.com/honusz/stagelinq-js/blob/main/docs/PROTOCOL.md).
Implement protocol facts independently and check the license before reusing any code.

## Later Pro DJ Link work

- Automatically fetch metadata on track changes, with caching, failure backoff and a manual refresh option
- Guarded remote track loading from an existing player library, with explicit source, slot and track ID
- Browse and richer metadata
- A bench deck on a real player's track: a grid whose tempo changes followed beat by beat rather than at its first
  tempo, and media with only a Device Library Plus database (`exportLibrary.db`)
- A local rekordbox export (`export.pdb` and the analysis files of a USB) as a bench deck's database, so a sound file
  gets its grid and tempo from its analysis rather than a typed BPM
- Read a track's stored cues (memory and hot cues, the cue list): snap a stopped player to the cue it sits on, as
  Beat Link does, and mark the cues on the strip
- Control a real player's tempo from the page, for instance with the bench as tempo master and the players synced to
  it, and offer most of the player control a show tool such as TC Supply's ShowKontrol does
- Mixer-assigned player numbers and robust multi-address conflict recovery
- macOS hardware and local-software interoperability validation
- NFS audio serving only as a separate, explicitly reviewed project

## Record a mix, replay it on the players

Scenarios can press a real player's buttons and load its tracks. A full automation pass could go further: record what
the players do during a mix (the tracks they load, when they play, cue, sync and take the master, their tempo and loops)
as a scenario, then replay it on the same players, which load each track and play it from the right place by themselves.

- Record from what the players broadcast and the bench already reads (status, beats, track ids), into the scenario format
- Replay only when the setup matches: the same players and numbers, the same media with the same track ids, else say what differs
- Reach a position by what the players allow (cue, play, seek by beat jumps if a model takes them), and check it with
  expect_player after each step
- Leave the mixer out: its faders and EQs are not controlled from the network, so a replay sets the players and the
  mix is done by hand

## The hosted page with an installed runtime

A browser cannot speak Pro DJ Link (it has no UDP broadcasts or fixed ports), so something always runs on the machine
cabled to the players. The bench can become that runtime, with the hosted page as its usual screen:

- Package the bench as one executable for each system, so nothing else is installed (it needs only the standard
  library, plus the optional QR package)
- Run it in the background from login, as a service or a tray app, with the hosted page finding it on `127.0.0.1`
  by itself: no terminal and no address to type
- Keep the page working with older runtimes, from the version the bench reports, since the page updates on deploy
  and the runtime only when its user updates it
- Sign the executables for macOS and Windows, and say what the firewall asks on the first run

## A deck API of its own, eventually

The protocol layer could become a library apart from the bench: one model of a deck (state, beats, track, tempo) and
its commands over Pro DJ Link, StagelinQ and others. Beat Link is the reference for Pro DJ Link, but it is Java and
covers that protocol only. Reading state abstracts well. Control does not, since each protocol allows different
commands, so the model needs per-device capabilities rather than one command set for all.

- Keep `deckbench/protocols` free of page logic now, with its device model treated as an internal API
- Shape the shared model only once a second protocol works behind it
- Move it to its own repository when something besides the bench uses it

Remote loading must reject a playing target and report sent versus confirmed state separately.
It must not imply that files uploaded to the bench are available as a physical player's USB library.

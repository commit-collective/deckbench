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

- Guarded remote track loading from an existing player library, with explicit source, slot and track ID
- Browse and richer metadata, then real beat grids, cues and waveforms
- Mixer-assigned player numbers and robust multi-address conflict recovery
- Native macOS adapter discovery and hardware validation
- NFS audio serving only as a separate, explicitly reviewed project

Remote loading must reject a playing target and report sent versus confirmed state separately.
It must not imply that files uploaded to the bench are available as a physical player's USB library.

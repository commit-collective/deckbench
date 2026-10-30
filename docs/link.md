# What the bench hears on the link

The bench listens on the three Pro DJ Link ports (50000, 50001, 50002) and keeps what it hears. The page shows it in three places.

## Other devices

A player or a mixer that is not one of the bench's decks gets a read-only card. It says what the device does according to its own
packets: the model if the name is a known one, its number and address, whether it plays, is master, is synced or on air, its tempo,
its place in the track and its loop. A device is known by its name and number, not by the address it sends from, so a unit under test
that sends its keep-alives from its network address and its statuses from the loopback is one card. A device that has been silent for
8 seconds is offline, and one that has been silent for 60 seconds is dropped.

`GET /api/state` has them in `protocols.prolink.devices`. Each has `name`, `model`, `number`, `ip`, `kind`, `unit` (a legacy
DJS-1000 marker), `online`, `status`, `phase` (only while it plays), `at` (only while it does not), `air` and `fader`.

A physical DJS-1000 appears as a regular player. The "UNIT UNDER TEST" badge and the dedicated header chip are shown
only when the DJS emulator test adapter is explicitly configured. The existing `unit` API field remains compatible.

Fresh broadcast beats provide `phase` even before a virtual deck is enabled and full status is available. `bar_phase`
separately tracks the reported beat within the bar, which need not match the absolute track count. The four slim amber
segments above each deck's beat squares repeat the current master's beat, so comparison does not require scrolling.
They stay dark when the master or its live phase is unknown. Identifying a physical master requires full status.
New beat packets can also revive the grid after an older paused status. A newer pause status stops that extrapolation.
Without status, the grid shows bar beats rather than absolute track numbers or loop details.

## Strips

Each deck, and each device with beats, has a strip: a grid that scrolls past a fixed playhead, one line for every beat and a heavier
line for every bar, with the beat of the track written on it. It has no waveform, except for a bench deck that plays a sound file of its own (see audio.md): its waveform is drawn faintly behind the grid, beat by beat, so that the beats can be seen to fall where they should and a loop's jump back shows in it. All the strips share one time scale, so decks that
are synced line up and one that is not drifts. A loop is tinted and marked where it goes back. For a device the page draws the beats
it was told of, and goes on at its tempo from the last.

Player loop boundaries are inferred from backward jumps in track position, then retained while that loop is active.
They do not disappear when the last wrap scrolls out of view. Leaving a loop or changing tracks clears the estimate.
If wrap status arrives after its beat packet, the bench corrects that beat's track count without moving its timestamp.
The page replaces the provisional observation instead of drawing an extra beat. Until the first wrap is observed,
the page may know that a player is looping without knowing the loop's boundaries.

## Sync

A deck that is synced to the master snaps to its beat grid, not only to its tempo. The bench takes the master's place from the
master's own beat packets, including the unit's.

## The journal

`POST /api/journal/start` begins a journal and answers `{"began", "baseline"}`: the requests (paths with their query) that would put the decks where
they are now (which are on, their tempo, a sync or master, a file they play, a loop, which play). From then on each `POST` that changes something
(a deck's switch, tempo, load, loop, unplug, the mixer, a setting) is kept with its time. `POST /api/journal/stop` ends it and answers
`{"began", "baseline", "actions": [[time, "/api/..."], ...]}`, the times from the bench's clock (`time.time()`). Playing it back is sending the baseline and
then each action at its time after the start. A deck that plays starts from the first beat of its bar, as it does when it is started, so the phase of a
deck that was already playing when the journal began is not the same. A deck's file is named by the path it had on the bench's machine. Uploads are kept only
until the bench leaves. Requests for `journal`, `upload`, `packets`, `events` and `scenario` are not kept, and neither is a `token`.

## The log

The Network tab has a real-time log of the packets. Keep-alives, claims, on air, fader start and the like are shown by default.
Statuses and beats are many, so they are an option ("status and beats"). The bench's own packets are an option too ("ours"). The
log can be paused, cleared, followed and exported.

    GET  /api/packets?since=<n>&noisy=<0|1>&limit=<n>   the lines after n, and the counts by kind
    POST /api/packets/clear                              forget them

Windows delivers a broadcast on the loopback to every socket bound to the port, so the monitor drops a copy of a packet that
arrives twice within 30 ms.

## Sound

The Listen button plays the bench's decks, each with its own voice (bass, drums, keys, percussion). The settings choose whether the
bench's own decks and other devices are heard. A device is heard while it plays, and with a mixer known, while it is on air.

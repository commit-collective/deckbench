# SPDX-License-Identifier: MIT OR Apache-2.0
"""What differs between the models of player the bench can stand in for.

From Deep Symmetry's analysis (vcdj.html), which gives, per model, the length of the status packet, byte 0xcc and the
sync counter:

    CDJ-2000 (nexus)   status 0xd4 bytes, nx byte 0x0f
    CDJ-2000NXS2       status 0x124 bytes (0x11c on older firmware), nx 0x0f
    XDJ-1000           status 0x11b bytes, nx 0x0f. The MK2 was not captured: it is taken to be the same
    CDJ-3000           status 0x200 bytes, nx 0x1f, a sync counter fixed at 0, players 1 to 6

The contents past what the bench fills in (waveform position, the settings blocks, the key shift...) are zeros: this is
the shape of the packets, not a copy of a player's state. What the analysis says of the CDJ-3000's other packets (the
precise position packets, the streaming sources) is not sent.
"""

PROFILES = {
    "cdj-2000": {"title": "CDJ-2000 (nexus)", "model": "CDJ-2000nexus", "status_length": 0xD4, "nexus": 0x0F, "sync_counter": True},
    "cdj-2000nxs2": {"title": "CDJ-2000NXS2", "model": "CDJ-2000NXS2", "status_length": 0x124, "nexus": 0x0F, "sync_counter": True},
    "xdj-1000mk2": {"title": "XDJ-1000MK2", "model": "XDJ-1000MK2", "status_length": 0x11B, "nexus": 0x0F, "sync_counter": True},
    "cdj-3000": {"title": "CDJ-3000", "model": "CDJ-3000", "status_length": 0x200, "nexus": 0x1F, "sync_counter": False},
}


def get(name):
    """The profile called `name` (as in `--profile`). ValueError if there is none."""
    if name not in PROFILES:
        raise ValueError("no profile %r (there is: %s)" % (name, ", ".join(PROFILES)))
    return PROFILES[name]

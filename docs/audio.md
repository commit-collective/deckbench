# The decks' sound

Each playing deck is a drum loop in time with it: a kick on every beat, a hat between the beats and a higher tick on the bar
line, each deck at a pitch of its own so that they can be told apart. The loop follows the deck as it plays: its tempo and a
change of it, its loop, a stop. A deck that is off, stopped or unplugged is silent. It is a few clicks, not a track, and there
is nothing in it of anyone's music.

    python -m deckbench --numbers 2,3 --on --audio-port 7320

serves it on `tcp://127.0.0.1:7320`, in real time, to each client that connects: **raw stereo 16-bit little-endian samples at
44.1 kHz** (what the DJS-1000 emulator takes as its input: `python app/virtual_djs.py --input-tcp 127.0.0.1:7320`). With
`--audio-decks 2` only that deck is heard. To listen, or to make a file:

    ffplay -f s16le -ar 44100 -ac 2 tcp://127.0.0.1:7320
    ffmpeg -f s16le -ar 44100 -ac 2 -i tcp://127.0.0.1:7320 -t 10 decks.wav

What it is for: a test of a sampler or a recorder that listens to a deck can then record something that is in time with the
deck, start on its bar, stop with it and loop with it, from the first run to the last, with no CDJ and no sound card.

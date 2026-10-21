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

## In the page

The **Sound** button of the page plays something like it in the browser, with no stream and no port: for each deck that plays, a kick
on the beats 1 and 3, a snare on 2 and 4 and a hat between, made with Web Audio from the deck's tempo and place in its bar (the
page counts the beats on from the bench's `phase`, as it does for the beat squares). Each deck has its place in the stereo field. With a
mixer on only the decks that are on the air are heard. A browser starts sound only after a click, so it is off when the page opens.
It is for hearing the decks. The stream above is what a device under test is fed.

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

## A track of your own

A deck can play a sound file instead of its drum loop, which is what a sampler or a recorder is then fed:

    python -m deckbench --numbers 2,3 --on --audio-port 7320 --track "2=C:\loops\break.wav@128" --init 2=play

`DECK=FILE@BPM[@START]`: the file, the tempo it was made at, and the seconds of the file before its first beat (default 0). Nothing
finds the beats for you, so the BPM and the start are what you say, and the deck's bar lines are counted from the start you give.
The deck loads it as a track (the unit hears its title, the file's name, and its BPM over the link) and the sound is the file played at
the deck's tempo, the way a CDJ does with its master tempo off: the pitch fader makes it faster and higher or slower and lower, a
synced deck follows the master's tempo, a loop goes round, a stop is silence, and the deck starts the file again each time it loads it.
After the end of the file it is silent.

A PCM WAV (8, 16, 24 or 32 bits, mono or stereo) of 44.1 kHz is read by the bench itself, with no packages. Any other file (mp3,
flac, a WAV of another rate) is read by `ffmpeg`, which has to be on the path, and the whole file is kept in memory (30 minutes at most).
Cut a track down to a loop if it is long. A bench that lives in WSL (the DJS-1000 emulator's `start.py` starts one there) reads the
file where it runs: give it the WSL path (`/mnt/c/loops/break.wav`), not the Windows one.

In the page, the deck's "Load a track" fold has a **Sound file** field and **First beat at**. **Browse** opens the browser's own file
picker: the file is sent to the bench (up to 300 MB) and its path fills the field, so the bench and the browser need not be on the same machine, or on the same side of WSL. The title and the BPM are filled from the
file's name if they are empty (a "128bpm" in it is taken). Or type a path on the machine the bench runs on. The BPM there is the one the
file was made at.

**Where a sent file goes.** A browser tells a page only what is in a file, never where it is, so Browse has to send the bytes. The bench keeps them
on the machine it runs on, in `~/.deckbench/tracks` (`--tracks-dir` or `$DECKBENCH_TRACKS` change it), under a name made of a hash of the contents and
the file's name, such as `3f9a1c20bb-break.wav`. The same file sent twice is one file, and the folder stays between runs, so a path that a session
recorded (a journal, the emulator's REC) is found again. Files unused for a month are removed when the bench starts, and the oldest go if the folder
holds over 2 GB. A file a deck has loaded is never removed. **Clear sent files** in the page's Settings, `POST /api/uploads/clear` and `--clear-uploads`
empty it. Typing a path loads the file where it is and copies nothing. Through the API:

    POST /api/deck/2/load/1002?audio=C:/loops/break.wav&bpm=128&offset=0.05
    POST /api/deck/2/audio/clear
    POST /api/upload?name=break.wav          (the body is the file: the answer has the path to give ?audio=)
    GET  /api/uploads                        (the folder, and how many files and bytes it holds)
    POST /api/uploads/clear                  (removes them, but not one a deck has loaded)

A file that will not do is answered with 400 and `{"error": ...}`, and nothing changes. The state has each deck's `audio` (its
`file`, `bpm`, `seconds` and `offset`), or null.

## In the page

The **Sound** button of the page plays something like it in the browser, with no stream and no port: for each deck that plays, a kick
on the beats 1 and 3, a snare on 2 and 4 and a hat between, made with Web Audio from the deck's tempo and place in its bar (the
page counts the beats on from the bench's `phase`, as it does for the beat squares). Each deck has its place in the stereo field. With a
mixer on only the decks that are on the air are heard. A browser starts sound only after a click, so it is off when the page opens.
It is for hearing the decks. The stream above is what a device under test is fed.

The deck's strip shows the file's waveform, faintly, behind its beat grid (from `/api/deck/N/waveform`, 100 values a second): the file is laid
out beat by beat from the tempo you gave and the first beat you said, so a BPM or a start that is wrong can be seen at once, as beats that
do not fall on the hits. A loop shows the jump back in it.

A deck that has a sound file of its own (see above) is not heard as drums in the page: the page fetches the file from the bench
(`/api/deck/N/audio.wav`) and plays it at the deck's tempo, from where the deck is, round its loop, and stops with it. What the Sound
button plays and what the stream carries are then the same file. A deck with no file keeps its voice.

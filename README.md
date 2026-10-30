# deckbench

[![release](https://img.shields.io/github/v/release/commit-collective/deckbench?display_name=tag)](https://github.com/commit-collective/deckbench/releases)
[![tests](https://github.com/commit-collective/deckbench/actions/workflows/test.yml/badge.svg)](https://github.com/commit-collective/deckbench/actions/workflows/test.yml)

Simulated DJ decks and mixers for testing software, hardware and emulators
that speak Pro DJ Link. Drive them from a browser, HTTP API or scenario.

<img src="https://commitcollective.cc/deckbench/hero.png" alt="Four simulated decks with transport controls, beat strips and a network event log" width="1000">

[Try the browser demo](https://commitcollective.cc/deckbench/app/?demo) ·
[Real hardware setup](docs/real-network.md) · [API and options](docs/reference.md)

## Start a local bench

Python 3.8 or later. From a cloned repository or extracted release:

```sh
python -m deckbench --numbers 2,3,4 --on
```

Open <http://127.0.0.1:8750/>. No runtime dependencies to install.
You can also install the checkout with `python -m pip install .`.

The page controls play, cue, sync, master, tempo, loops and track loading.
Its side panel shows events, scenarios, the mixer and network settings.
The optional browser sound is the bench's, not the device under test's.

Local decks use `127.0.0.N`. Run the device under test in the same network
namespace. If an emulator runs in WSL, run deckbench there too.
Linux and Windows are covered by CI. Native macOS loopback does not provide
the broadcast behaviour this mode needs. Use a Linux VM for the loopback
bench. Real-network interface support is currently Windows and Linux.

## Choose a workflow

| Goal | Start here |
|---|---|
| Explore the interface without a network | [Browser demo](https://commitcollective.cc/deckbench/app/?demo), simulated in the browser |
| Test an app or emulator locally | The command above, then [scenarios](docs/scenarios.md) |
| Put simulated decks beside real hardware | [Network aliases, broadcast and ports](docs/real-network.md) |
| Use a phone as the screen of a running bench | [Phone pairing and connection choices](docs/phone.md) |

The bench provides discovery, statuses, beats, sync/master handover, track
metadata and a simulated DJM. Model profiles vary packet shape and advertised
capabilities. They are not complete emulations of those players.
StagelinQ is planned.

## Automate it

`deckbench.testing.Bench` starts an isolated process, waits for readiness
and stops it when the context closes:

```python
from deckbench.testing import Bench

with Bench(numbers=[2, 3], on=True) as bench:
    bench.post("api/deck/2/tempo/126")
    print(bench.output())
```

Use JSON [scenarios](docs/scenarios.md) for timed actions and expectations,
[adapters](docs/adapters.md) for a device's controls and lamps, and the
[HTTP reference](docs/reference.md) from any language.

## Documentation

- [Protocol and verification limits](docs/prolink.md)
- [Audio streaming and tracks](docs/audio.md)
- [Mixer and startup](docs/mixer.md)
- [Network monitor and journal](docs/link.md)
- [Hosting the browser app](docs/hosting.md)
- [Development and reliable checks](docs/developing.md)

## Verification and support

The implementation follows public protocol analyses and is exercised against
the DJS-1000 application in an emulator. Packet-layout checks do not establish
compatibility with every physical player. See [protocol notes](docs/prolink.md).

[Report an issue](https://github.com/commit-collective/deckbench/issues)
with the version, OS, command, expected result and log. Redact tokens and
private addresses. Follow releases on GitHub or [Commit Collective](https://commitcollective.cc).

## Licence

MIT OR Apache-2.0, at your option.
[LICENSE-MIT](LICENSE-MIT) · [LICENSE-APACHE](LICENSE-APACHE)

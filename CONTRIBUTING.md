# Contributing

Thanks for helping improve Deckbench. Bug reports, compatibility testing,
documentation and code contributions are all welcome. You do not need DJ
hardware to contribute.

Deckbench is a general-purpose protocol test bench. Keep core features and
setup guidance useful across hardware, applications and platforms.

## Report a bug or test a setup

[Open an issue](https://github.com/commit-collective/deckbench/issues) with:

- The version or commit, OS and Python version
- The launch command, with tokens removed
- Expected behavior, what happened and steps to reproduce it
- Relevant logs and whether you used loopback, Ethernet or a VM bridge
- For hardware tests, the device model and firmware version

Say what you actually tested. A parser check, a passing CI job and a successful
hardware session establish different things. Report failures and untested
behavior too. See [platform and protocol limits](docs/prolink.md) and
[macOS networking](docs/macos.md).

## Make a change

Small fixes can go straight to a pull request. For larger features, new
dependencies or protocol backends, open an issue first to discuss the scope.

Keep changes focused, add regression checks for behavior changes and update
the relevant docs. For protocol work, link public references and distinguish
documented fields from assumptions. Model profiles must not imply full device
compatibility. Preserve existing API and adapter contracts, or explain any
intentional compatibility change.

From the checkout root, run the full suite on Linux or Windows:

```sh
python -m unittest discover -s tests -v
```

On native macOS, run the supported subset instead:

```sh
python3 -m unittest discover -s tests -p test_macos.py -v
python3 -m unittest discover -s tests -p test_demo.py -v
```

The browser checks need Node.js. Report skipped checks and environment limits
rather than calling an incomplete run fully tested. Packaging changes also
need the installed-package check in [docs/developing.md](docs/developing.md),
preferably in a disposable virtual environment. That guide covers network
fixtures, port isolation and CI failures.

In the pull request, summarize the change, why it helps and the checks run.
Mention anything that still needs hardware validation. Test control commands
at safe monitoring levels, never during a performance.

## Keep submissions shareable

Do not submit vendor firmware, extracted firmware assets, encryption keys,
passwords or private packet captures. Keep real captures local. Redact tokens,
device identities, private addresses and track information from shared logs.
Use minimal synthetic fixtures for regression tests.

Only submit material you have the right to share. Contributions use the
repository's existing [MIT](LICENSE-MIT) OR [Apache-2.0](LICENSE-APACHE)
licensing. Check compatibility before reusing third-party code and retain
required notices.

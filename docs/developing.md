# Development checks

From the repository root:

```sh
python -m unittest discover -s tests -v
python -m pip install --no-deps .
python -I tools/check_installed.py
```

The installed-package check must not import the source checkout. It checks
the CLI, adapters and bundled browser assets.

## Network checks

The suite requires UDP broadcasts across 127.0.0.0/8, available on Linux and
Windows. A sandbox or firewall may prevent reception even when socket binding
works. That is not a clean regression result. Native macOS loopback is not a
supported integration-test environment.

Tests use shifted ports instead of the real Pro DJ Link ports. Do not run two
suites at once with the same DECKBENCH_PORT_SHIFT.

Prefer pure model/parser checks for exact values. Use integration checks for
delivery and wiring. Wait for an observable condition with a bounded deadline
instead of guessing a sleep. UDP ordering is per socket, not across ports.
When a beat depends on a new status, confirm that status was processed before
sending the beat. A final flush on both ports does not establish their order.

Tests currently leave some protocol daemon threads alive until the process
ends. Each fixture needs its own port range. A future lifecycle change should
add explicit stop/join ownership before sharing ports between fixtures.

## CI failures

CI uses fixed OS images, a bounded runtime and verbose output. Its annotations
summarise failed cases, and a per-job artifact retains the complete output.
Do not hide flaky assertions behind job retries or allowed failures.

Read the first traceback, reproduce the named case and run the complete suite
after the fix. Report the first failure even if a later run passes.

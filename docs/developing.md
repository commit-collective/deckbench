# Development checks

An in-process Pro DJ Link instance owns its network workers. Call `Prolink.stop()` in a cleanup or `finally` block.
It closes sockets, cancels handoff timers and joins workers. Restarting that instance reuses its configured ports.
Mock the CLI's `idle_sleep`, not `time.sleep` on the shared Python module, to avoid interrupting other workers.

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

The dedicated `macos-15` CI job runs `test_macos.py`, browser checks and the installed-package check. It does not run
the broadcast suite or claim physical DJ hardware validation. The native socket check uses only 127.0.0.1, with
broadcast output mocked explicitly. Adapter fixtures cover Ethernet aliases, masks, inactive interfaces and missing
MACs. Listener receive/accept waits are bounded so shutdown does not depend only on closing a socket from another thread.

Tests use shifted ports instead of the real Pro DJ Link ports. Do not run two
suites at once with the same DECKBENCH_PORT_SHIFT.

Prefer pure model/parser checks for exact values. Use integration checks for
delivery and wiring. Wait for an observable condition with a bounded deadline
instead of guessing a sleep. UDP ordering is per socket, not across ports.
When a beat depends on a new status, confirm that status was processed before
sending the beat. A final flush on both ports does not establish their order.

Fixtures should register `Prolink.stop()` as cleanup, including when setup fails. Some older fixtures still depend on
process exit, so keep separate port ranges until their cleanup has been migrated and verified.

## CI failures

CI uses fixed OS images, a bounded runtime and verbose output. Its annotations
summarise failed cases, and a per-job artifact retains the complete output.
Do not hide flaky assertions behind job retries or allowed failures.

Read the first traceback, reproduce the named case and run the complete suite
after the fix. Report the first failure even if a later run passes.

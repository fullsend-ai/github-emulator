# Bug: `ci-stack.sh start` gives up after about 30 s while the emulator is still starting

Status: fixed 2026-11-21 (issue #107).

## Summary

- The readiness loop in `scripts/ci-stack.sh` made 60 attempts with
  `sleep 0.5`. While uvicorn is still starting, `curl` is refused at once, so
  `-m 2` never applied and the loop lasted about 30 s.
- On a busy CI VM (fullsend's `behaviour-github-emulator` shards, which build
  and pull images alongside), imports and migrations sometimes took longer.
  `emulator.log` stopped at `Waiting for application startup.`, and nothing
  showed which startup phase was slow.

## Fix

- The loop waits until a deadline, `CI_STACK_START_TIMEOUT` seconds (default
  120), measured to the millisecond (`EPOCHREALTIME`, else `date +%s`). It
  still stops as soon as the emulator process exits.
- `start` prints `emulator ready after N.Ns`. On failure, `the emulator did not start:` is followed by either
  `no answer after N.Ns (CI_STACK_START_TIMEOUT=...)` or `it exited after N.Ns`.
- `lifespan` in `src/app/main.py` logs a timestamped `Startup: <phase>...`
  line, then `Startup: <phase> done in N.NNs`, for each phase: database init
  (migrations), the admin user seed and the SSH server. Before those, it
  logs `Startup: app import done in N.NNs`, the time to import the app. On a
  busy CI VM that import was most of a slow start.
- The script header and `docs/guides/ci.md` describe the new variable.

## Evidence

- `tests/test_ci_stack_start.py` runs the real script with a stub
  `CI_STACK_PYTHON`. A stub that answers after 2 s, with a 15 s deadline,
  starts. One that never answers, with a 3 s deadline, fails after 3 s or more
  with the elapsed time. One that exits after 1 s, with a 60 s deadline, fails
  well before the deadline. A deadline of 0 is refused.
- `tests/test_startup_logging.py::test_startup_logs_how_long_each_phase_took`
  checks the phase lines.

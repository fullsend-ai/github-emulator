"""scripts/ci-stack.sh start: how long it waits for the emulator (#107).

These run the real script with CI_STACK_PYTHON pointing at a stub, so no
emulator starts. The stub stands in for `python -m uvicorn ...`: it answers
on /api/v3 after a delay, never answers, or exits. Any other call, a
runner, just sleeps until `stop` kills it.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci-stack.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not all(shutil.which(tool) for tool in ("bash", "curl", "openssl")),
    reason="ci-stack.sh needs bash, curl and openssl",
)

STUB = """#!/usr/bin/env bash
if [ "$1" = -m ] && [ "$2" = uvicorn ]; then
  port=
  while [ $# -gt 0 ]; do
    if [ "$1" = --port ]; then port="$2"; fi
    shift
  done
  sleep "$STUB_DELAY"
  case "$STUB_MODE" in
    serve) exec "$STUB_PYTHON" -m http.server --bind 127.0.0.1 --directory "$STUB_SITE" "$port" ;;
    hang) exec sleep 600 ;;
    exit) echo "stub emulator exiting" >&2; exit 1 ;;
  esac
fi
exec sleep 600
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def stack(tmp_path):
    """Run `ci-stack.sh start` with a stub emulator; always `stop` afterwards."""
    stub = tmp_path / "python"
    stub.write_text(STUB)
    stub.chmod(0o755)
    site = tmp_path / "site"
    (site / "api").mkdir(parents=True)
    (site / "api" / "v3").write_text("{}")
    state = tmp_path / "stack"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CI_STACK_", "GITHUB_EMULATOR_"))}
    env.update(
        CI_STACK_DIR=str(state),
        CI_STACK_PORT=str(_free_port()),
        CI_STACK_PYTHON=str(stub),
        STUB_PYTHON=sys.executable,
        STUB_SITE=str(site),
    )

    def start(*, mode: str, delay: float, timeout: int):
        run_env = dict(env, STUB_MODE=mode, STUB_DELAY=str(delay), CI_STACK_START_TIMEOUT=str(timeout))
        began = time.monotonic()
        result = subprocess.run(
            ["bash", str(SCRIPT), "start"], env=run_env, capture_output=True, text=True, timeout=120
        )
        return result, time.monotonic() - began

    yield start
    subprocess.run(["bash", str(SCRIPT), "stop"], env=env, capture_output=True, timeout=60)


def test_a_start_slower_than_the_old_attempt_count_but_within_the_deadline_succeeds(stack):
    result, _ = stack(mode="serve", delay=2, timeout=15)

    assert result.returncode == 0, result.stderr
    assert "emulator ready after" in result.stdout


def test_a_start_past_the_deadline_fails_with_the_elapsed_time(stack):
    result, took = stack(mode="hang", delay=0, timeout=3)

    assert result.returncode == 1
    assert "the emulator did not start: no answer after" in result.stderr
    assert "(CI_STACK_START_TIMEOUT=3)" in result.stderr
    assert "start failed; stopping what it launched" in result.stderr
    assert 3 <= took < 30


def test_an_emulator_that_exits_ends_the_wait_before_the_deadline(stack):
    result, took = stack(mode="exit", delay=1, timeout=60)

    assert result.returncode == 1
    assert "the emulator did not start: it exited after" in result.stderr
    assert "stub emulator exiting" in result.stderr
    assert took < 30


def test_a_start_timeout_of_zero_is_refused(stack):
    result, _ = stack(mode="serve", delay=0, timeout=0)

    assert result.returncode == 2
    assert "CI_STACK_START_TIMEOUT must be a whole number" in result.stderr

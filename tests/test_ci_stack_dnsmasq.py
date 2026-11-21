"""scripts/ci-stack.sh installs dnsmasq, updating apt's lists only if it must."""

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci-stack.sh"

# apt-get stand-in: records each call, fails an install while the lists are
# not "updated" (FAIL_INSTALLS=first) or always (FAIL_INSTALLS=all).
APT_GET = """#!/bin/sh
echo "$*" >>"$CALLS"
case "$*" in
  *update*) : >"$CALLS.updated" ;;
  *install*)
    if [ "$FAIL_INSTALLS" = all ] || { [ "$FAIL_INSTALLS" = first ] && [ ! -e "$CALLS.updated" ]; }; then
      echo "E: Unable to locate package dnsmasq-base" >&2
      exit 100
    fi ;;
esac
"""


def _install_dnsmasq(tmp_path: Path, *, installed=False, fail_installs="none"):
    """Run install_dnsmasq(), cut from the script, with stubs as the only PATH."""
    text = SCRIPT.read_text()
    function = re.search(r"^install_dnsmasq\(\) \{\n.*?^\}\n", text, re.M | re.S)
    assert function
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {"apt-get": APT_GET, "sudo": '#!/bin/sh\nexec "$@"\n'}
    if installed:
        stubs["dnsmasq"] = "#!/bin/sh\n"
    for name, body in stubs.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    calls = tmp_path / "calls"
    result = subprocess.run(
        ["/bin/bash", "-c", f"set -euo pipefail\n{function.group(0)}install_dnsmasq\necho continued"],
        capture_output=True, text=True,
        env={"PATH": str(bin_dir), "CALLS": str(calls), "FAIL_INSTALLS": fail_installs},
    )
    lines = calls.read_text().splitlines() if calls.exists() else []
    return result, ["update" if "update" in line else "install" for line in lines]


def test_already_installed_calls_no_apt(tmp_path):
    result, calls = _install_dnsmasq(tmp_path, installed=True)
    assert result.returncode == 0
    assert calls == []


def test_install_that_works_first_time_does_not_update(tmp_path):
    result, calls = _install_dnsmasq(tmp_path)
    assert result.returncode == 0
    assert calls == ["install"]
    assert result.stdout.strip() == "continued"


def test_failed_install_updates_and_retries(tmp_path):
    result, calls = _install_dnsmasq(tmp_path, fail_installs="first")
    assert result.returncode == 0, result.stderr
    assert calls == ["install", "update", "install"]
    assert result.stdout.strip() == "continued"
    # The first, failed attempt stays quiet.
    assert "Unable to locate package" not in result.stderr


def test_install_failing_twice_stops_with_apts_error(tmp_path):
    result, calls = _install_dnsmasq(tmp_path, fail_installs="all")
    assert result.returncode != 0
    assert calls == ["install", "update", "install"]
    assert "continued" not in result.stdout
    assert "E: Unable to locate package dnsmasq-base" in result.stderr

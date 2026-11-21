"""scripts/ci-stack.sh's TLS certificates pass Python's strict X.509 checks.

Python 3.13+ sets VERIFY_X509_STRICT in ssl.create_default_context(), which
rejects a CA certificate without the key usage extension. Setting the flag
here makes the test meaningful on any Python version.
"""

import os
import re
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci-stack.sh"


def _make_tls_code() -> str:
    """make_tls(), cut from the script so the test uses its own commands."""
    text = SCRIPT.read_text()
    function = re.search(r"^make_tls\(\) \{\n.*?^\}\n", text, re.M | re.S)
    assert function
    return function.group(0)


def _make_tls(directory: Path, host: str) -> Path:
    env = {
        **os.environ,
        "DIR": str(directory),
        "HOST": host,
        "CA": str(directory / "tls" / "ca.pem"),
        "RAW_HOST": "0",
        "RAW_NAME": "raw.githubusercontent.com",
        "PY": sys.executable,
        "CI_STACK_SYSTEM_TRUST": "0",
    }
    subprocess.run(
        ["bash", "-c", f"set -euo pipefail\n{_make_tls_code()}make_tls"],
        capture_output=True, text=True, check=True, env=env,
    )
    return directory / "tls"


@pytest.mark.parametrize("host", ["127.0.0.1", "emulator.localhost"])
def test_strict_python_client_accepts_ci_stack_certificate(tmp_path, host):
    tls = _make_tls(tmp_path, host)

    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(tls / "server.pem", tls / "server-key.pem")
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def serve():
        conn, _ = listener.accept()
        try:
            with server_ctx.wrap_socket(conn, server_side=True) as tls_conn:
                tls_conn.sendall(b"ok")
        except (ssl.SSLError, OSError):
            pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        client_ctx = ssl.create_default_context(cafile=str(tls / "ca.pem"))
        client_ctx.verify_flags |= ssl.VERIFY_X509_STRICT
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            with client_ctx.wrap_socket(sock, server_hostname=host) as tls_sock:
                assert tls_sock.recv(2) == b"ok"
    finally:
        thread.join(timeout=10)
        listener.close()

# Bug: Python 3.13+ rejects the ci-stack.sh TLS CA

Status: fixed 2026-11-21 (issue #114).

## Summary

- With `CI_STACK_TLS=1`, `make_tls()` in `scripts/ci-stack.sh` made its CA
  with a bare `openssl req -x509`, so the CA had no key usage extension.
- Since Python 3.13, `ssl.create_default_context()` sets
  `VERIFY_X509_STRICT`, which requires a CA certificate to carry key usage.
  Python clients failed with `CA cert does not include key usage extension`.
- Ubuntu 26.04 ships Python 3.14, so Fullsend's emulator job on an
  `ubuntu-26.04` VM failed as soon as `scripts/ci-seed-mint-apps.py` called
  the emulator. `self-contained-smoke.yml` did not catch it: its TLS clients
  are `curl`, Node, .NET and Go, which do not apply that check.

## Fix

- The CA's `openssl req -x509` now adds
  `basicConstraints=critical,CA:TRUE`,
  `keyUsage=critical,keyCertSign,cRLSign` and `subjectKeyIdentifier=hash`.
- The server certificate is unchanged. OpenSSL 3 adds the key identifiers
  to it.

## Evidence

- `tests/test_ci_stack_tls.py` cuts `make_tls()` from the script, runs it
  for an IP host and a DNS host, and handshakes with a local TLS server
  using `ssl.create_default_context(cafile=ca.pem)` with
  `VERIFY_X509_STRICT` set explicitly, so it checks on any Python version.
- Before the fix (Python 3.14.3, OpenSSL 3.5.5): both cases fail with
  `CERTIFICATE_VERIFY_FAILED ... CA cert does not include key usage
  extension`. After the fix: both pass.

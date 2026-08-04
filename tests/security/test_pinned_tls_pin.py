"""Regression tests for the fixed development-auth certificate pin.

Re-run these tests whenever the pin is updated after the current certificate
expires on Aug 11 2026.
"""

from __future__ import annotations

import hashlib
import http.client
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import pinned_tls


ROOT_DIR = Path(__file__).resolve().parents[2]


def _credential(name: str) -> str:
    environment_value = os.getenv(name)
    if environment_value:
        return environment_value

    for raw_line in (ROOT_DIR / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def test_live_request_succeeds_through_current_certificate_pin() -> None:
    """Make a real pinned request to the fixed development auth host."""
    emp_code = _credential("EMP_CODE")
    emp_password = _credential("EMP_PASSWORD")
    assert emp_code and emp_password, "EMP_CODE or EMP_PASSWORD is absent/empty"

    response = pinned_tls.post_json(
        "/auth/token",
        {"empCode": emp_code, "password": emp_password},
    )
    payload = response.json()

    assert response.status_code == 200
    assert isinstance(payload, dict)
    assert isinstance(payload.get("token"), str) and payload["token"]


def test_wrong_certificate_pin_fails_closed_without_network() -> None:
    """Reject a mismatched leaf certificate before any HTTP request is sent."""
    presented_certificate = b"offline-regression-certificate"
    wrong_fingerprint = hashlib.sha256(b"different-certificate").hexdigest()

    class FakeTlsSocket:
        def __init__(self) -> None:
            self.closed = False

        def getpeercert(self, *, binary_form: bool = False) -> bytes:
            assert binary_form is True
            return presented_certificate

        def close(self) -> None:
            self.closed = True

    fake_socket = FakeTlsSocket()

    def expose_fake_socket(connection: http.client.HTTPSConnection) -> None:
        connection.sock = fake_socket

    connection = pinned_tls._PinnedHTTPSConnection(timeout=1.0)
    with (
        patch.object(http.client.HTTPSConnection, "connect", expose_fake_socket),
        patch.object(pinned_tls, "EXPECTED_CERT_SHA256", wrong_fingerprint),
        pytest.raises(pinned_tls.CertificatePinMismatch, match="Certificate pin mismatch"),
    ):
        connection.connect()

    assert fake_socket.closed is True
    assert connection.sock is None

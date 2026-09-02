"""Regression tests for the fixed development-auth certificate pin.

The current leaf certificate is valid from Aug 7 00:00:00 2026 GMT through
Feb 21 23:59:59 2027 GMT. Re-run these tests whenever the pin is updated.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
from pathlib import Path
from unittest.mock import patch

import allure
import pytest

from scripts import pinned_tls


ROOT_DIR = Path(__file__).resolve().parents[2]
CURRENT_CERT_SHA256 = (
    "C139A6EB97F44676BD7A79897211B02FC3DEAFB988E8B08705F6AEFC82D1F569"
)
STALE_CERT_SHA256 = (
    "C3524D47998E616A31634A3A4E75899629FDBE58DAD17318AF51FC2288F375C8"
)


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


def _attach_tls_evidence(name: str, evidence: dict[str, object]) -> None:
    allure.attach(
        json.dumps(evidence, indent=2),
        name=name,
        attachment_type=allure.attachment_type.JSON,
    )


def _pinned_host_resolves() -> bool:
    """Whether the pinned host still exists in DNS.

    It stopped resolving when the estate moved to uat-mcdp-be, which has no
    underscore and so needs no pin at all -- see HANDOVER item 16. Both call
    sites gate on the resolved hostname matching PINNED_HOST, so the pin is
    simply never selected now; nothing is weakened by its absence.
    """
    try:
        socket.getaddrinfo(pinned_tls.PINNED_HOST, 443)
    except OSError:
        return False
    return True


def test_live_request_succeeds_through_current_certificate_pin() -> None:
    """Make a real pinned request to the fixed development auth host."""
    # Checked before the skip below, deliberately. This is the guard against a
    # pin edited quietly in scripts/pinned_tls.py, and that guard has to keep
    # working whether or not the host is reachable -- otherwise a dead host
    # would also switch off the one assertion that notices the pin changing.
    assert pinned_tls.EXPECTED_CERT_SHA256 == CURRENT_CERT_SHA256

    if not _pinned_host_resolves():
        pytest.skip(
            f"{pinned_tls.PINNED_HOST} no longer resolves, so the live half of "
            "this test cannot run. The pin's fingerprint is still asserted "
            "above, and the fail-closed behaviour is proved offline by "
            "test_wrong_certificate_pin_fails_closed_without_network. Whether "
            "to retire the pinning module is HANDOVER item 16."
        )

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
    fingerprints_match = (
        response.certificate_sha256 == pinned_tls.EXPECTED_CERT_SHA256
    )
    assert fingerprints_match

    _attach_tls_evidence(
        "TLS certificate pin match",
        {
            "expected_certificate_sha256": pinned_tls.EXPECTED_CERT_SHA256,
            "received_certificate_sha256": response.certificate_sha256,
            "fingerprints_match": fingerprints_match,
            "result": "PASS: received leaf certificate matches the configured pin",
        },
    )


def test_wrong_certificate_pin_fails_closed_without_network() -> None:
    """Reject the retired leaf fingerprint before any HTTP request is sent."""
    presented_certificate = b"offline-regression-certificate"

    class CurrentCertificateDigest:
        def hexdigest(self) -> str:
            return CURRENT_CERT_SHA256

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
        patch.object(
            pinned_tls.hashlib,
            "sha256",
            return_value=CurrentCertificateDigest(),
        ),
        patch.object(pinned_tls, "EXPECTED_CERT_SHA256", STALE_CERT_SHA256),
        pytest.raises(
            pinned_tls.CertificatePinMismatch,
            match="Certificate pin mismatch",
        ) as exception_info,
    ):
        connection.connect()

    assert fake_socket.closed is True
    assert connection.sock is None
    assert connection.peer_certificate_sha256 == CURRENT_CERT_SHA256

    exception_message = str(exception_info.value.args[0])
    assert STALE_CERT_SHA256 in exception_message
    assert connection.peer_certificate_sha256 in exception_message

    _attach_tls_evidence(
        "TLS certificate pin rejection",
        {
            "deliberately_wrong_expected_sha256": STALE_CERT_SHA256,
            "rejected_received_certificate_sha256": (
                connection.peer_certificate_sha256
            ),
            "exception_message": exception_message,
            "result": "PASS: mismatched certificate was rejected before HTTP data",
        },
    )

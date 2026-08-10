#!/usr/bin/env python3
"""Narrow certificate-pinned HTTPS helper for the development MCDP login host.

This module is intentionally scoped to ``uat_mcdp_be.omfysgroup.com``. Normal
CA-chain and certificate-validity verification remains enabled. Only automatic
hostname matching is disabled because the underscore hostname is rejected by
standard hostname rules; the exact leaf certificate SHA-256 pin is checked on
the live TLS socket before any HTTP request bytes are sent.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import ssl
from dataclasses import dataclass
from typing import Any, Mapping


PINNED_HOST = "dev_mcdp_be.omfysgroup.com"
PINNED_PORT = 443
EXPECTED_CERT_SHA256 = (
    "C139A6EB97F44676BD7A79897211B02FC3DEAFB988E8B08705F6AEFC82D1F569"
)
DEFAULT_TIMEOUT_SECONDS = 30.0


class CertificatePinMismatch(ssl.SSLError):
    """Raised when the live peer certificate does not match the required pin."""


@dataclass(frozen=True)
class PinnedResponse:
    """Small immutable response value returned after the connection is closed."""

    status_code: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)


def _normalized_fingerprint(value: str) -> str:
    normalized = value.replace(":", "").strip().upper()
    if len(normalized) != 64 or any(character not in "0123456789ABCDEF" for character in normalized):
        raise ValueError("Pinned SHA-256 fingerprint must contain exactly 64 hexadecimal characters")
    return normalized


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # Hostname verification alone is disabled for this fixed underscore host.
    # CA trust-chain and validity checks remain mandatory via CERT_REQUIRED.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that checks the leaf pin before request transmission."""

    def __init__(self, *, timeout: float) -> None:
        super().__init__(
            PINNED_HOST,
            PINNED_PORT,
            timeout=timeout,
            context=_tls_context(),
        )

    def connect(self) -> None:
        super().connect()
        if self.sock is None:
            self.close()
            raise CertificatePinMismatch("TLS connection did not expose a peer socket")

        der_certificate = self.sock.getpeercert(binary_form=True)
        if not der_certificate:
            self.close()
            raise CertificatePinMismatch("TLS peer did not present a leaf certificate")

        actual = hashlib.sha256(der_certificate).hexdigest().upper()
        expected = _normalized_fingerprint(EXPECTED_CERT_SHA256)
        if not hmac.compare_digest(actual, expected):
            self.close()
            raise CertificatePinMismatch(
                f"Certificate pin mismatch for {PINNED_HOST}: "
                f"expected {expected}, received {actual}; connection refused"
            )


def _validate_path(path: str) -> None:
    if not path.startswith("/") or "://" in path:
        raise ValueError("Only origin-relative paths for the pinned host are allowed")


def _validate_headers(headers: Mapping[str, str]) -> None:
    supplied_host = next(
        (value for name, value in headers.items() if name.lower() == "host"),
        None,
    )
    if supplied_host is not None and supplied_host.lower() != PINNED_HOST:
        raise ValueError(f"Host header must remain scoped to {PINNED_HOST}")


def request(
    method: str,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    content: bytes | str | None = None,
    json_body: Any | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> PinnedResponse:
    """Send one pinned HTTPS request to the fixed development host.

    The pin is checked during ``connect()`` on the exact socket used by
    ``HTTPSConnection.request()``. A mismatch closes the socket and raises
    ``CertificatePinMismatch`` before the method/path/headers/body are sent.
    """
    _validate_path(path)
    request_headers = dict(headers or {})
    _validate_headers(request_headers)

    if content is not None and json_body is not None:
        raise ValueError("Provide either content or json_body, not both")

    request_body: bytes | str | None = content
    if json_body is not None:
        request_body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        if not any(name.lower() == "content-type" for name in request_headers):
            request_headers["Content-Type"] = "application/json"

    connection = _PinnedHTTPSConnection(timeout=timeout)
    try:
        connection.request(
            method.upper(),
            path,
            body=request_body,
            headers=request_headers,
        )
        response = connection.getresponse()
        response_content = response.read()
        return PinnedResponse(
            status_code=response.status,
            reason=response.reason,
            headers=tuple(response.getheaders()),
            content=response_content,
        )
    finally:
        connection.close()


def post_json(
    path: str,
    payload: Any,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> PinnedResponse:
    """Convenience wrapper for a JSON POST to the single pinned host."""
    return request(
        "POST",
        path,
        headers=headers,
        json_body=payload,
        timeout=timeout,
    )


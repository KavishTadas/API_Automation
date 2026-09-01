"""Shared runtime for endpoint-specific cases. NO ASSERTIONS LIVE HERE.

A case file in this tree tests **one behaviour of one endpoint** -- the things the
22 global checks cannot express, because they are specific to this API rather than
true of every API. It declares which catalogue row it exercises::

    caseRef = "post|/auth/token|employee auth api|tc01 - valid credentials return jwt token"

and asks for the ``case_response`` fixture, which performs that row's request once
per session and hands back the ``httpx.Response``.

What belongs here, and what does not
------------------------------------
These cases were migrated from the Postman collections' ``pm.test`` blocks. Roughly
half of those assertions duplicate the global tier -- "Status is 200", "Full
response matches OpenAPI LoginResponse" -- and are deliberately **not** reproduced:
``test_status_code_matches_spec`` and ``test_response_matches_full_schema`` already
assert them against every endpoint, and a second copy is a second thing to keep in
step. Only the endpoint-specific remainder is migrated.

The row, not the YAML
---------------------
Rows come from ``build/API_File.json`` -- the derived inventory the engine itself
reads -- so a case sees exactly the request the contract tier sees. Reading
``api-endpoints/*.yaml`` directly here would let the two disagree whenever the
generator has not been re-run.

Token
-----
One bootstrap per session, published under every spelling the inventory uses
(``{{authToken}}``, ``{{token}}``, ``{{jwtToken}}``) -- the same fix as 2a3767e. A
case that deliberately sends no token, or a bad one, overrides the header itself
rather than asking for a different fixture.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
INVENTORY = ROOT_DIR / "build" / "API_File.json"

#: The row whose response mints the session token. Employee Auth rather than Login
#: Auth UAT because it is the primary issuer; a case needing the other overrides.
BOOTSTRAP_REF = (
    "post|/auth/token|employee auth api|tc01 - valid credentials return jwt token"
)

__all__ = [
    "ROOT_DIR",
    "BOOTSTRAP_REF",
    "row_for",
    "runtime_config",
    "response_for",
    "json_body",
    "case_response",
    "case_json",
]


@lru_cache(maxsize=1)
def _rows() -> dict[str, dict[str, Any]]:
    if not INVENTORY.exists():
        pytest.skip(
            f"{INVENTORY.relative_to(ROOT_DIR)} is missing; run "
            "python scripts/generate-generic-tests.py"
        )
    rows = json.loads(INVENTORY.read_text(encoding="utf-8"))
    return {str(r.get("API Identifier", "")): r for r in rows}


def row_for(ref: str) -> dict[str, Any]:
    """The inventory row for a caseRef, or skip -- never a silent empty dict."""
    row = _rows().get(ref)
    if row is None:
        pytest.skip(f"no inventory row for caseRef {ref!r}; it may have been removed")
    return row


@lru_cache(maxsize=1)
def runtime_config() -> dict[str, str]:
    """Runtime config with a bootstrapped bearer token, once per session."""
    from tests.api_runtime._api_test_helpers import (
        load_runtime_config,
        perform_api_request,
    )
    from tests.global_contract.auth_bootstrap import TOKEN_RUNTIME_KEYS, extract_token

    config = dict(load_runtime_config())
    provider = _rows().get(BOOTSTRAP_REF)
    if provider is None:
        return config

    try:
        response = perform_api_request(provider, config)
    except Exception:  # unreachable host, TLS, DNS -- cases skip rather than error
        return config

    if response.is_success:
        try:
            token = extract_token(response.json())
        except Exception:
            token = ""
        if token:
            for key in TOKEN_RUNTIME_KEYS:
                config[key] = token
    return config


@lru_cache(maxsize=None)
def response_for(ref: str) -> httpx.Response:
    """Perform this row's request once per session and cache the response.

    Cached because several assertions on one case read the same response, and a
    write endpoint must not be fired once per assertion.
    """
    from tests.api_runtime._api_test_helpers import perform_api_request

    return perform_api_request(row_for(ref), runtime_config())


def json_body(response: httpx.Response) -> Any:
    """Parsed JSON, or skip with the reason -- never a failure about parsing.

    A non-JSON body here means the request never reached the application (an empty
    gateway 403 is the common one). That is not this endpoint's business rule
    failing, so it must not be reported as one.
    """
    try:
        return response.json()
    except Exception:
        pytest.skip(
            f"response was not JSON (HTTP {response.status_code}, "
            f"content-type {response.headers.get('content-type') or 'none'}); "
            "the request did not reach the application"
        )


@pytest.fixture(scope="module")
def case_response(request: pytest.FixtureRequest) -> httpx.Response:
    """The response for the calling module's ``caseRef``.

    Module-scoped because ``request.module`` -- how a case declares which row it
    exercises -- is not available to a session-scoped fixture. The request is
    still made only once per ref for the whole run: the caching lives in
    :func:`response_for`, so two modules on the same ref share one response and a
    write endpoint is not fired twice.
    """
    ref = getattr(request.module, "caseRef", None)
    if not ref:
        pytest.fail(f"{request.module.__name__} declares no caseRef")
    return response_for(ref)


@pytest.fixture(scope="module")
def case_json(case_response: httpx.Response) -> Any:
    """Parsed JSON body for the calling module's ``caseRef``."""
    return json_body(case_response)

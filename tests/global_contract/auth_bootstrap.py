"""Auth provider bootstrap.

An API named as an ``authProviderApiId`` is a **token provider, not a test
subject**. It is called directly, once, and its collection is never run. That
distinction matters: running the provider's own collection would fire its own
assertions, and a failing auth assertion would then surface as a failure of the
API the user actually selected — which is not what happened.

One login per pair
------------------
Exactly one login per distinct ``(authProviderApiId, credentialAlias)`` pair per
run — not one per API. Eight APIs sharing a provider and an alias perform one
login between them. Two APIs naming different providers each get their own
token, routed to the right API.

Failure is SKIPPED_NO_TOKEN, never FAIL
---------------------------------------
A bootstrap that does not produce a token means the dependent APIs were never
executed. Reporting them as FAIL would claim they were tested and found broken.
They report ``SKIPPED_NO_TOKEN`` with a reason naming the provider — the shape
the existing tooling already uses for ``Leave_API (BLOCKED: Employee_Auth_API
failed)``.

Token extraction follows ``tests/auto_generated/conftest.py``: ``token`` /
``access_token`` / ``authToken``, at the top level and under ``data``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.auto_generated._api_test_helpers import perform_api_request
from tests.global_contract.credentials import (
    CredentialResolutionError,
    resolve_credential,
)


__all__ = [
    "AuthBootstrap",
    "BootstrapResult",
    "TOKEN_RUNTIME_KEYS",
    "extract_token",
]

#: The keys a bootstrapped token is written to. The request helper reads these,
#: and a value present here deliberately WINS over any ambient environment
#: variable — a stale CI secret previously defeated the bootstrap and surfaced
#: as unexplained 401s.
TOKEN_RUNTIME_KEYS = ("AUTH_TOKEN", "API_AUTH_TOKEN", "authToken")

_TOKEN_FIELDS = ("token", "access_token", "authToken")


def extract_token(payload: Any) -> str:
    """Pull a bearer token out of a login response body.

    Checks ``token`` / ``access_token`` / ``authToken`` at the top level and
    again under ``data``, matching what the generated suite's conftest already
    does. Returns ``""`` when none is present — never raises on a shape it does
    not recognise.
    """
    if not isinstance(payload, dict):
        return ""

    for name in _TOKEN_FIELDS:
        value = payload.get(name)
        if isinstance(value, str) and value:
            return value

    nested = payload.get("data")
    if isinstance(nested, dict):
        for name in _TOKEN_FIELDS:
            value = nested.get(name)
            if isinstance(value, str) and value:
                return value

    return ""


@dataclass(frozen=True)
class BootstrapResult:
    """The outcome of one login attempt.

    ``token`` is excluded from ``repr`` so a fixture dump or assertion rewrite
    cannot spill it.
    """

    provider_id: str
    credential_alias: str
    token: str = field(default="", repr=False)
    reason: str = ""

    @property
    def succeeded(self) -> bool:
        return bool(self.token)

    def runtime_overrides(self) -> dict[str, str]:
        return {key: self.token for key in TOKEN_RUNTIME_KEYS} if self.token else {}


class AuthBootstrap:
    """Mints and caches bearer tokens, one per provider/alias pair per run."""

    def __init__(
        self,
        runtime_config: dict[str, str],
        provider_row_for: Any,
    ) -> None:
        """
        ``provider_row_for`` is a callable taking an ``authProviderApiId`` and
        returning the request row to log in with, or ``None`` when the provider
        cannot be resolved.
        """
        self._runtime_config = runtime_config
        self._provider_row_for = provider_row_for
        self._results: dict[tuple[str, str], BootstrapResult] = {}
        self._login_count = 0

    @property
    def login_count(self) -> int:
        """How many live logins were performed. One per distinct pair."""
        return self._login_count

    @property
    def results(self) -> dict[tuple[str, str], BootstrapResult]:
        return dict(self._results)

    def token_for(
        self,
        provider_id: str | None,
        credential_alias: str | None,
    ) -> BootstrapResult | None:
        """Return the token for this pair, logging in at most once per pair.

        ``None`` means no auth was requested — an unsecured API attempts no
        login at all.
        """
        if not provider_id:
            return None

        key = (str(provider_id), str(credential_alias or ""))
        if key in self._results:
            return self._results[key]

        result = self._login(str(provider_id), str(credential_alias or ""))
        self._results[key] = result
        return result

    def _login(self, provider_id: str, credential_alias: str) -> BootstrapResult:
        provider_row = self._provider_row_for(provider_id)
        if provider_row is None:
            return BootstrapResult(
                provider_id=provider_id,
                credential_alias=credential_alias,
                reason=(
                    f"did not get token: auth provider {provider_id!r} could not be "
                    "resolved to a request"
                ),
            )

        login_config = dict(self._runtime_config)
        try:
            credential = resolve_credential(credential_alias, self._runtime_config)
        except CredentialResolutionError as error:
            # Names the alias and the keys it looked for; never the value.
            return BootstrapResult(
                provider_id=provider_id,
                credential_alias=credential_alias,
                reason=f"did not get token: {error}",
            )

        if credential is not None:
            login_config.update(credential.as_runtime_overrides())

        self._login_count += 1
        try:
            response = perform_api_request(provider_row, login_config)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as error:
            # BaseException, not Exception: perform_api_request signals an
            # unusable provider row with pytest.skip, whose Skipped derives from
            # BaseException and would otherwise abort the whole run.
            #
            # The helper already redacts its own attachments; only the exception
            # type is repeated here, never its message, which could embed a URL
            # carrying query-string credentials.
            return BootstrapResult(
                provider_id=provider_id,
                credential_alias=credential_alias,
                reason=(
                    f"did not get token: auth provider {provider_id!r} raised "
                    f"{type(error).__name__}"
                ),
            )

        if not response.is_success:
            return BootstrapResult(
                provider_id=provider_id,
                credential_alias=credential_alias,
                reason=(
                    f"did not get token: auth provider {provider_id!r} returned "
                    f"HTTP {response.status_code} (body withheld)"
                ),
            )

        try:
            payload = response.json()
        except ValueError:
            return BootstrapResult(
                provider_id=provider_id,
                credential_alias=credential_alias,
                reason=(
                    f"did not get token: auth provider {provider_id!r} returned "
                    "non-JSON content"
                ),
            )

        token = extract_token(payload)
        if not token:
            return BootstrapResult(
                provider_id=provider_id,
                credential_alias=credential_alias,
                reason=(
                    f"did not get token: auth provider {provider_id!r} response "
                    "contained no token field"
                ),
            )

        return BootstrapResult(
            provider_id=provider_id,
            credential_alias=credential_alias,
            token=token,
        )

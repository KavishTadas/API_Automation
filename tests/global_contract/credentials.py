"""Credential alias resolution.

A manifest names a ``credentialAlias`` — a label, never a value. The raw
employee code and password are resolved at run time from the environment or CI
secrets, the same way ``{{authToken}}`` is already resolved by token-chaining
rather than being hardcoded anywhere.

Key convention
--------------
``CRED_<ALIAS>_EMP_CODE`` and ``CRED_<ALIAS>_EMP_PASSWORD``, with the alias
uppercased and every non-alphanumeric run collapsed to a single underscore::

    attendance-svc-uat-01 -> CRED_ATTENDANCE_SVC_UAT_01_EMP_CODE
                             CRED_ATTENDANCE_SVC_UAT_01_EMP_PASSWORD

Failure names the alias, never the value
----------------------------------------
:class:`CredentialResolutionError` reports the alias and the environment keys it
looked for. It never carries the resolved value, and neither does any log,
report, or Allure attachment this engine produces.

Scope boundary: these guarantees cover engine-side reports and logs. What the
platform does with a raw value after entry — masking, storage, access control,
platform-side logging — is the dev team's question, not this engine's.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


__all__ = [
    "CredentialResolutionError",
    "ResolvedCredential",
    "credential_env_keys",
    "lookup_registered_value",
    "normalize_alias",
    "resolve_credential",
]


class CredentialResolutionError(RuntimeError):
    """An alias could not be resolved. Names the alias and keys, never a value."""


def normalize_alias(alias: str) -> str:
    """Uppercase an alias and collapse non-alphanumeric runs to underscores."""
    return re.sub(r"[^A-Za-z0-9]+", "_", str(alias or "")).strip("_").upper()


def credential_env_keys(alias: str) -> tuple[str, str]:
    """Return ``(emp_code_key, emp_password_key)`` for ``alias``."""
    normalized = normalize_alias(alias)
    return (
        f"CRED_{normalized}_EMP_CODE",
        f"CRED_{normalized}_EMP_PASSWORD",
    )


@dataclass(frozen=True)
class ResolvedCredential:
    """A resolved credential pair.

    ``repr`` is overridden so a pytest fixture dump, an assertion rewrite, or an
    exception traceback can never spill the value — the most common way a
    secret reaches a report is by accident, not by design.
    """

    alias: str
    emp_code: str
    emp_password: str

    def __repr__(self) -> str:
        return f"ResolvedCredential(alias={self.alias!r}, emp_code=<redacted>, emp_password=<redacted>)"

    __str__ = __repr__

    def as_runtime_overrides(self) -> dict[str, str]:
        """The runtime-config keys the request helper reads for login."""
        return {
            "EMP_CODE": self.emp_code,
            "empCode": self.emp_code,
            "EMP_PASSWORD": self.emp_password,
            "empPassword": self.emp_password,
        }


def lookup_registered_value(key: str, runtime_config: dict[str, str] | None) -> str:
    """Read a registered key from the runtime config, falling back to the environment.

    ``load_runtime_config()`` reads ``.env`` and the Postman environment file
    only — it never consults ``os.environ``. That is fine for local runs but
    would make every CI-supplied secret and every platform-supplied base URL
    invisible, since CI hands those over as process environment variables. That
    helper is a generated artifact and must not be edited, so the fallback lives
    here instead.

    The explicit config wins, matching how ``_auth_token()`` already prefers a
    bootstrapped value over an ambient one.
    """
    value = str((runtime_config or {}).get(key, "") or "").strip()
    if value:
        return value
    return str(os.environ.get(key, "") or "").strip()


def resolve_credential(
    alias: str | None,
    runtime_config: dict[str, str],
) -> ResolvedCredential | None:
    """Resolve ``alias`` against the runtime config.

    Returns ``None`` when no alias was requested — an unsecured API needs no
    credential and must not be forced to carry one. Raises
    :class:`CredentialResolutionError` when an alias *was* requested but no
    value is registered for it.
    """
    if not alias or not str(alias).strip():
        return None

    code_key, password_key = credential_env_keys(alias)
    emp_code = lookup_registered_value(code_key, runtime_config)
    emp_password = lookup_registered_value(password_key, runtime_config)

    missing = [
        key
        for key, value in ((code_key, emp_code), (password_key, emp_password))
        if not value
    ]
    if missing:
        raise CredentialResolutionError(
            f"credentialAlias {alias!r} is not registered: no value for "
            f"{', '.join(missing)}. Register it in the environment or CI secrets; "
            "manifests never carry raw values."
        )

    return ResolvedCredential(alias=str(alias), emp_code=emp_code, emp_password=emp_password)

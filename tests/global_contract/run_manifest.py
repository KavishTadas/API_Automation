"""The run manifest: the engine's input contract.

The QA platform drives this engine by handing it a manifest naming which APIs to
test. An API arrives either **by reference** (``ref`` — already in the repo's
generated inventory) or **by value** (``definition`` — an uploaded Excel row or
cURL command, parsed into the shape ``metadata_resolver.ApiDefinition`` expects).

Statelessness (DR-2)
--------------------
Nothing here persists. No store, no repo writes, no ``openapi.yaml``
modification. Every run is reproducible from its manifest alone — preserve that
property. Collections stay the source of truth and stay git-tracked; the
platform has no repo write access, and travelling by value sidesteps that
entirely rather than working around it.

Credentials never travel in a manifest
--------------------------------------
``credentialAlias`` is a *label*. The raw employee code and password are
resolved at run time from environment or CI secrets — see
:mod:`~tests.global_contract.credentials`. Any key anywhere in the manifest that
looks like it carries a secret is rejected outright, and the rejection names the
JSON path without ever echoing the value.

Because that scan walks *keys*, sample payloads should be supplied the way the
template writes them — as JSON **strings** in ``Sample JSON`` — which keeps a
response sample's own field names (``token`` and friends) out of the manifest's
key space.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.global_contract.metadata_resolver import ApiDefinition


__all__ = [
    "ManifestApiEntry",
    "ManifestValidationError",
    "RunManifest",
    "CREDENTIAL_KEY_PATTERN",
    "RUN_MANIFEST_ENV_VAR",
    "load_manifest",
    "definition_to_manifest_block",
    "load_manifest_from_env",
    "validate_manifest",
]


#: Points the tier at a manifest file. Unset means "no manifest" and the tier
#: falls back to enumerating ``openapi.yaml`` exactly as it did before Sprint 2.
RUN_MANIFEST_ENV_VAR = "GLOBAL_CONTRACT_RUN_MANIFEST"

#: A key matching this anywhere in the manifest is rejected. ``credentialAlias``
#: is deliberately exempted by the negative lookahead — it is a label, not a
#: value.
CREDENTIAL_KEY_PATTERN = re.compile(
    r"password|secret|token|passwd|credential(?!Alias)",
    re.IGNORECASE,
)

#: Tiers this engine knows how to run. Sprint 2 drives the Python global tier
#: only; per-API Newman execution is out of scope.
KNOWN_TIERS = frozenset({"global_contract"})

#: The 15 `API_Overview` columns, plus the two child-sheet collections.
_DEFINITION_FIELDS = frozenset(
    {
        "API ID",
        "API / Feature Name",
        "Module",
        "Purpose",
        "Owner / Dev Contact",
        "HTTP Method",
        "Base URL",
        "Endpoint Path",
        "Auth Type",
        "Idempotent (Y/N)",
        "Environment(s)",
        "API Version",
        "Last Updated",
        "cURL",
        "Postman Collection Link",
        "payloads",
        "rules",
    }
)

_ENTRY_FIELDS = frozenset({"ref", "definition", "credentialAlias", "authProviderApiId"})
_MANIFEST_FIELDS = frozenset({"runId", "environment", "requestedTiers", "apis"})

_PAYLOAD_FIELDS = frozenset({"API ID", "Payload Type", "Response status", "Sample JSON"})
_RULE_FIELDS = frozenset({"API ID", "Category", "Description"})


class ManifestValidationError(ValueError):
    """A manifest was rejected. The message names paths, never values."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__(
            "Run manifest rejected:\n" + "\n".join(f"  - {e}" for e in self.errors)
        )


@dataclass(frozen=True)
class ManifestApiEntry:
    """One selected API. Carries either ``ref`` or ``definition``, never both."""

    ref: str | None = None
    definition: ApiDefinition | None = None
    credential_alias: str | None = None
    auth_provider_api_id: str | None = None
    #: Position in the manifest's ``apis`` list, for stable reporting.
    index: int = 0

    @property
    def identifier(self) -> str:
        """A stable human-facing name for this entry."""
        if self.ref:
            return self.ref
        if self.definition is not None:
            return (
                self.definition.api_id
                or f"{self.definition.method} {self.definition.path}"
            )
        return f"apis[{self.index}]"

    @property
    def auth_key(self) -> tuple[str, str] | None:
        """The ``(authProviderApiId, credentialAlias)`` pair, if this API needs auth.

        One login is performed per distinct pair per run — not one per API.
        """
        if not self.auth_provider_api_id:
            return None
        return (self.auth_provider_api_id, self.credential_alias or "")


@dataclass(frozen=True)
class RunManifest:
    """A validated manifest. Construct only via :func:`validate_manifest`."""

    run_id: str
    environment: str
    requested_tiers: tuple[str, ...]
    apis: tuple[ManifestApiEntry, ...] = ()
    #: Non-fatal notes raised while validating (e.g. a stripped Authorization
    #: header). Diagnostic; never contains a credential value.
    warnings: tuple[str, ...] = field(default=(), repr=False)

    def entries_for_tier(self, tier: str) -> tuple[ManifestApiEntry, ...]:
        if tier not in self.requested_tiers:
            return ()
        return self.apis


def _scan_for_credential_keys(node: Any, path: str, errors: list[str]) -> None:
    """Reject any key that looks like it carries a secret.

    Names the JSON path and **never** echoes the value — that is the whole point
    of the check, and an error message that quoted the offending value would
    reintroduce the leak it exists to prevent.
    """
    if isinstance(node, dict):
        for key, child in node.items():
            child_path = f"{path}.{key}"
            if CREDENTIAL_KEY_PATTERN.search(str(key)):
                errors.append(
                    f"{child_path}: key looks like a raw credential; manifests carry "
                    "a credentialAlias label instead (value withheld)"
                )
                continue
            _scan_for_credential_keys(child, child_path, errors)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _scan_for_credential_keys(child, f"{path}[{index}]", errors)


def _reject_unknown(
    node: dict[str, Any],
    allowed: frozenset[str],
    path: str,
    errors: list[str],
) -> None:
    """Unknown fields are rejected, never silently ignored.

    Silently ignoring one means a typo'd ``authProviderApiID`` produces a run
    that looks fine and quietly skipped its auth bootstrap.
    """
    for key in node:
        if key not in allowed:
            errors.append(
                f"{path}.{key}: unknown field (allowed: {', '.join(sorted(allowed))})"
            )


def _validate_definition(
    raw: Any,
    path: str,
    errors: list[str],
) -> ApiDefinition | None:
    if not isinstance(raw, dict):
        errors.append(f"{path}: definition must be an object")
        return None

    _reject_unknown(raw, _DEFINITION_FIELDS, path, errors)

    for required in ("HTTP Method", "Endpoint Path"):
        if not str(raw.get(required, "") or "").strip():
            errors.append(f"{path}.{required}: required for an inline definition")

    for collection, allowed in (("payloads", _PAYLOAD_FIELDS), ("rules", _RULE_FIELDS)):
        rows = raw.get(collection)
        if rows is None:
            continue
        if not isinstance(rows, list):
            errors.append(f"{path}.{collection}: must be an array")
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{path}.{collection}[{index}]: must be an object")
                continue
            _reject_unknown(row, allowed, f"{path}.{collection}[{index}]", errors)

    if errors:
        return None

    try:
        return ApiDefinition.from_mapping(raw)
    except (TypeError, ValueError) as error:
        errors.append(f"{path}: could not be read as a definition ({type(error).__name__})")
        return None


def _validate_entry(raw: Any, index: int, errors: list[str]) -> ManifestApiEntry | None:
    path = f"$.apis[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{path}: must be an object")
        return None

    _reject_unknown(raw, _ENTRY_FIELDS, path, errors)

    has_ref = bool(str(raw.get("ref", "") or "").strip())
    has_definition = raw.get("definition") is not None

    if has_ref and has_definition:
        errors.append(
            f"{path}: carries both 'ref' and 'definition'; an API arrives either by "
            "reference or by value, never both"
        )
        return None
    if not has_ref and not has_definition:
        errors.append(f"{path}: must carry either 'ref' or 'definition'")
        return None

    definition = None
    if has_definition:
        before = len(errors)
        definition = _validate_definition(raw["definition"], f"{path}.definition", errors)
        if len(errors) != before:
            return None

    for optional in ("credentialAlias", "authProviderApiId"):
        value = raw.get(optional)
        if value is not None and not isinstance(value, str):
            errors.append(f"{path}.{optional}: must be a string")

    return ManifestApiEntry(
        ref=str(raw["ref"]).strip() if has_ref else None,
        definition=definition,
        credential_alias=raw.get("credentialAlias") or None,
        auth_provider_api_id=raw.get("authProviderApiId") or None,
        index=index,
    )


def validate_manifest(data: Any) -> RunManifest:
    """Validate a manifest document. Raises :class:`ManifestValidationError`.

    Every problem found is reported at once rather than one per run, so a
    malformed manifest takes one round trip to fix instead of five.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        raise ManifestValidationError(["$: manifest must be a JSON object"])

    # Run this first: a manifest carrying a raw credential is rejected on that
    # ground alone, before any of its structure is reported on.
    _scan_for_credential_keys(data, "$", errors)
    if errors:
        raise ManifestValidationError(errors)

    _reject_unknown(data, _MANIFEST_FIELDS, "$", errors)

    run_id = str(data.get("runId", "") or "").strip()
    if not run_id:
        errors.append("$.runId: required")

    environment = str(data.get("environment", "") or "").strip()
    if not environment:
        errors.append("$.environment: required")

    raw_tiers = data.get("requestedTiers")
    tiers: tuple[str, ...] = ()
    if not isinstance(raw_tiers, list) or not raw_tiers:
        errors.append("$.requestedTiers: required, must be a non-empty array")
    else:
        unknown = [t for t in raw_tiers if t not in KNOWN_TIERS]
        if unknown:
            errors.append(
                f"$.requestedTiers: unknown tier(s) {sorted(map(str, unknown))}; "
                f"known tiers are {sorted(KNOWN_TIERS)}"
            )
        tiers = tuple(str(t) for t in raw_tiers)

    raw_apis = data.get("apis")
    entries: list[ManifestApiEntry] = []
    if not isinstance(raw_apis, list) or not raw_apis:
        errors.append("$.apis: required, must be a non-empty array")
    else:
        for index, raw_entry in enumerate(raw_apis):
            entry = _validate_entry(raw_entry, index, errors)
            if entry is not None:
                entries.append(entry)

    if errors:
        raise ManifestValidationError(errors)

    return RunManifest(
        run_id=run_id,
        environment=environment,
        requested_tiers=tiers,
        apis=tuple(entries),
    )


def definition_to_manifest_block(definition: ApiDefinition) -> dict[str, Any]:
    """Serialize a parsed definition into a manifest ``definition`` block.

    This is how an upload travels by value (DR-2): the platform parses the Excel
    row or cURL command with the adapters, calls this, and drops the result
    straight into ``apis[].definition``. Sample payloads are emitted as JSON
    **strings**, matching the template, which also keeps their internal field
    names out of the manifest's key space so the credential-key scan does not
    trip over a response sample that legitimately contains a ``token`` field.
    """

    def _sample(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    return {
        "API ID": definition.api_id,
        "API / Feature Name": definition.name,
        "Module": definition.module,
        "Purpose": definition.purpose,
        "Owner / Dev Contact": definition.owner,
        "HTTP Method": definition.method,
        "Base URL": definition.base_url,
        "Endpoint Path": definition.path,
        "Auth Type": definition.auth_type,
        "Idempotent (Y/N)": definition.idempotent,
        "Environment(s)": definition.environments,
        "API Version": definition.api_version,
        "Last Updated": definition.last_updated,
        "cURL": definition.curl,
        "Postman Collection Link": definition.collection_link,
        "payloads": [
            {
                "API ID": definition.api_id,
                "Payload Type": payload.payload_type,
                "Response status": (
                    str(payload.response_status)
                    if payload.response_status is not None
                    else "na"
                ),
                "Sample JSON": _sample(payload.sample_json),
            }
            for payload in definition.payloads
        ],
        "rules": [
            {
                "API ID": definition.api_id,
                "Category": rule.category,
                "Description": rule.description,
            }
            for rule in definition.rules
        ],
    }


def load_manifest(path: str | Path) -> RunManifest:
    """Read and validate a manifest file."""
    manifest_path = Path(path)
    try:
        with manifest_path.open(encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except OSError as error:
        raise ManifestValidationError(
            [f"$: manifest file could not be read ({type(error).__name__}): {manifest_path}"]
        ) from error
    except ValueError as error:
        raise ManifestValidationError(
            [f"$: manifest file is not valid JSON ({error.__class__.__name__})"]
        ) from error

    return validate_manifest(data)


def load_manifest_from_env() -> RunManifest | None:
    """Load the manifest named by the environment, or ``None`` if none is set.

    ``None`` means the tier enumerates ``openapi.yaml`` exactly as it did before
    Sprint 2 — the no-manifest path must stay a no-op regression-wise.
    """
    location = os.environ.get(RUN_MANIFEST_ENV_VAR, "").strip()
    if not location:
        return None
    return load_manifest(location)

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

That scan is scoped to the manifest's **control** region — ``runId``,
``environment``, ``credentialAlias``, ``authProviderApiId``, ``ref``, and a
definition's metadata columns. Sample-payload content is explicitly excluded,
because an auth API's ``Success Response`` legitimately documents a ``token``
field and that is a description of the API, not a credential for it. Control
*values* are checked too: a ``credentialAlias`` holding a JWT or a
``password=...`` string is rejected the same way a bad key is.
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
    "normalize_environment",
    "registered_environments_from",
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

#: Sample-payload and prose content. Explicitly excluded from the credential
#: key scan: an auth API's `Success Response` legitimately documents a `token`
#: field, and a `Rules_Dependencies_EdgeCases` note may legitimately discuss
#: passwords. Both are data about the API, not credentials for it.
_PAYLOAD_CONTENT_FIELDS = frozenset({"Sample JSON", "Description", "payloads", "rules"})

#: A JWT-shaped string: the `eyJ` base64url header marker followed by two more
#: dot-separated segments. Deliberately loose on segment length — a real token is
#: far longer than this, and an alias that genuinely begins `eyJ` and carries two
#: dots is not a label anyone meant to write.
_JWT_SHAPED = re.compile(r"eyJ[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]*")

#: `password=...`, `secret: ...`, `token=...` and friends embedded in a value.
_SECRET_ASSIGNMENT = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S", re.IGNORECASE
)

#: What a credentialAlias may look like: a short, boring label.
_ALIAS_LABEL = re.compile(r"[A-Za-z0-9._-]{1,64}")

#: Control fields whose *values* are checked for credential-shaped content.
_SCANNED_CONTROL_VALUES = frozenset(
    {"runId", "environment", "credentialAlias", "authProviderApiId", "ref"}
)


def normalize_environment(environment: Any) -> str:
    """Normalize an environment name to its canonical form.

    Uppercased, with every non-alphanumeric run collapsed to one underscore, so
    ``uat``, ``UAT`` and ``Uat`` are the same environment. This lives in the
    contract rather than in a resolver's private helper: which spellings mean
    the same environment is a question about the input format, and the platform
    needs the same answer the engine uses.
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", str(environment or "")).strip("_").upper()


def registered_environments_from(config: dict[str, str] | None) -> frozenset[str]:
    """Derive the valid environment set from registered ``<MODULE>_BASE_URL_<ENV>`` keys.

    Never a hardcoded list. Registering ``ATTENDANCE_BASE_URL_QA`` is all it
    takes to make ``QA`` selectable.
    """
    found: set[str] = set()
    for key in (config or {}):
        match = re.fullmatch(r"(?P<module>.+)_BASE_URL_(?P<env>[A-Za-z0-9]+)", str(key))
        if match:
            found.add(match.group("env").upper())
    return frozenset(found)


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


def _scan_control_keys(node: Any, path: str, errors: list[str]) -> None:
    """Reject secret-looking keys, but only within a manifest's *control* region.

    Scoped deliberately. Scanning every key in the document rejected a perfectly
    correct definition whose ``Success Response`` sample contains a ``token``
    field — that is documentation of the response shape, not a credential. The
    engine could dodge that by always emitting samples as strings, but the
    platform's own code has no way to know that constraint, so the rule moves
    here instead: **payload content is data and is never scanned**.

    Names the JSON path and **never** echoes the value — an error message that
    quoted the offending value would reintroduce the leak it exists to prevent.
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
            if key in _PAYLOAD_CONTENT_FIELDS:
                continue  # data, not control — see above
            _scan_control_keys(child, child_path, errors)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _scan_control_keys(child, f"{path}[{index}]", errors)


def _scan_control_value(key: str, value: Any, path: str, errors: list[str]) -> None:
    """Reject a control *value* that carries a credential rather than a label.

    ``credentialAlias`` is the one a caller is most likely to get wrong — pasting
    the password in where the label belongs is an easy mistake, and it would put
    a live secret into a manifest that gets stored and replayed.
    """
    if not isinstance(value, str) or not value.strip():
        return

    text = value.strip()
    if _JWT_SHAPED.search(text) or _SECRET_ASSIGNMENT.search(text):
        errors.append(
            f"{path}: {key} must be a label, but its value looks like a raw "
            "credential (value withheld)"
        )
        return

    if key == "credentialAlias" and not _ALIAS_LABEL.fullmatch(text):
        errors.append(
            f"{path}: credentialAlias must be a short label matching "
            "[A-Za-z0-9._-]{1,64}; register the real value as "
            "CRED_<ALIAS>_EMP_CODE / _EMP_PASSWORD (value withheld)"
        )


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

    for control in _SCANNED_CONTROL_VALUES:
        if control in raw:
            _scan_control_value(control, raw[control], f"{path}.{control}", errors)

    return ManifestApiEntry(
        ref=str(raw["ref"]).strip() if has_ref else None,
        definition=definition,
        credential_alias=raw.get("credentialAlias") or None,
        auth_provider_api_id=raw.get("authProviderApiId") or None,
        index=index,
    )


def validate_manifest(
    data: Any,
    registered_environments: frozenset[str] | None = None,
) -> RunManifest:
    """Validate a manifest document. Raises :class:`ManifestValidationError`.

    Every problem found is reported at once rather than one per run, so a
    malformed manifest takes one round trip to fix instead of five.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        raise ManifestValidationError(["$: manifest must be a JSON object"])

    # Run this first: a manifest carrying a raw credential is rejected on that
    # ground alone, before any of its structure is reported on.
    _scan_control_keys(data, "$", errors)
    for control in _SCANNED_CONTROL_VALUES:
        if control in data:
            _scan_control_value(control, data[control], f"$.{control}", errors)
    if errors:
        raise ManifestValidationError(errors)

    _reject_unknown(data, _MANIFEST_FIELDS, "$", errors)

    run_id = str(data.get("runId", "") or "").strip()
    if not run_id:
        errors.append("$.runId: required")

    environment = normalize_environment(data.get("environment"))
    if not environment:
        errors.append("$.environment: required")
    elif registered_environments is not None and registered_environments:
        # The valid set is whatever `<MODULE>_BASE_URL_<ENV>` keys are actually
        # registered — never a hardcoded list, so registering a new key makes
        # that environment selectable with no code change. An empty set means no
        # environment-scoped hosts are configured at all, and the unsuffixed
        # `<MODULE>_BASE_URL` keys serve every environment; nothing to check.
        if environment not in registered_environments:
            errors.append(
                f"$.environment: {environment!r} is not registered; known "
                f"environments are {sorted(registered_environments)} "
                "(derived from the registered <MODULE>_BASE_URL_<ENV> keys)"
            )

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


def load_manifest(
    path: str | Path,
    registered_environments: frozenset[str] | None = None,
) -> RunManifest:
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

    return validate_manifest(data, registered_environments)


def load_manifest_from_env(
    registered_environments: frozenset[str] | None = None,
) -> RunManifest | None:
    """Load the manifest named by the environment, or ``None`` if none is set.

    ``None`` means the tier enumerates ``openapi.yaml`` exactly as it did before
    Sprint 2 — the no-manifest path must stay a no-op regression-wise.
    """
    location = os.environ.get(RUN_MANIFEST_ENV_VAR, "").strip()
    if not location:
        return None
    return load_manifest(location, registered_environments)

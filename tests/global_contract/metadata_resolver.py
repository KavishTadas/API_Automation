"""Source-agnostic metadata resolution for the global contract tier.

Why this module exists
----------------------
``tests/global_contract/`` used to read ``openapi/openapi.yaml`` directly, which
documents exactly two operations. Every other API in the repo got zero coverage,
and feeding the tier an API the spec has never heard of raised during pytest
*collection* — so one unknown API took the whole tier down for every API in the
batch.

This module is the seam. Each ``OperationCase`` field is resolved through a
precedence chain rather than a single dict index, and **nothing here raises**:
absent metadata yields ``None``.

Precedence chain (per field, first hit wins)
--------------------------------------------
1. ``openapi/openapi.yaml`` — authoritative wherever an entry exists
2. A supplied :class:`ApiDefinition` — Excel/cURL, per the template contract
3. ``api-docs/API_File.json`` — inventory-inferred
4. ``None`` (a global default may then apply; see :data:`DEFAULT_SLA_MS`)

A field merely *missing* from a higher source is a miss, not a hit — an
operation present in ``openapi.yaml`` but without ``x-sla-ms`` still lets a
definition or the inventory supply the SLA.

Recorded trade-off
------------------
This ends ``openapi.yaml``'s status as the *sole* source of truth for this tier;
it becomes the highest-precedence source among several. That is a real drift
risk, and it contradicts the repo's standing constraint that adding coverage
means adding to the contract first. The alternative — having uploads generate
OpenAPI stubs so one source remains — requires the platform to write into a
git-tracked file, which it cannot do. This is deliberate and recorded; do not
silently "fix" it later.

Sprint 2 plugs its Excel and cURL parsers in by building :class:`ApiDefinition`
objects and calling :func:`register_api_definitions`. The parsers themselves are
out of scope here — only the shape they must produce is defined.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


__all__ = [
    "ApiDefinition",
    "ContractSources",
    "MetadataResolver",
    "PayloadType",
    "ResolvedMetadata",
    "SamplePayload",
    "DEFAULT_CONTENT_TYPE",
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "DEFAULT_SLA_MS",
    "get_resolver",
    "infer_json_schema",
    "load_contract_sources",
    "register_api_definitions",
]


ROOT_DIR = Path(__file__).resolve().parents[2]
API_FILE_PATH = ROOT_DIR / "api-docs" / "API_File.json"
OPENAPI_PATH = ROOT_DIR / "openapi" / "openapi.yaml"

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})

#: Methods that are safe to replay. Used only for inventory-inferred idempotency:
#: replaying a PUT or DELETE against UAT would be a state change, so those are
#: never *inferred* idempotent. An explicit declaration still wins.
REPLAY_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Global default where no source declares an SLA. Advisory only — exceeding it
#: emits WARN, never FAIL. See T6.
DEFAULT_SLA_MS = 700

#: Global default where no source declares a payload ceiling. 1 MiB is nginx's
#: ``client_max_body_size`` default and the de-facto floor; AWS API Gateway is
#: 10 MB and GCP is 32 MB, so no single industry standard exists. Consumed only
#: by an INFORMATIONAL check, so this has no pass/fail impact.
DEFAULT_MAX_PAYLOAD_BYTES = 1_048_576

#: The template carries no content-type column, so every declared status on a
#: non-OpenAPI source defaults to JSON.
DEFAULT_CONTENT_TYPE = "application/json"

#: Values that mean "no value" in the template. ``na`` in particular appears in
#: ``Sample_Payloads.Response status`` for request-body rows; calling int() on it
#: unguarded is the crash this guards against.
NULL_TOKENS = frozenset({"", "na", "n/a", "-", "none", "null", "tbd"})

#: Environment-variable name fragments that carry no module identity.
GENERIC_MODULE_TOKENS = frozenset(
    {"HCM", "API", "APIS", "MODULE", "SERVICE", "SERVICES", "MANAGEMENT", "MGMT"}
)

_DEFINITIONS_ENV_VAR = "GLOBAL_CONTRACT_API_DEFINITIONS"

#: A `{var}` path template, raw or percent-encoded as the inventory records it.
_PATH_VARIABLE_MARKER = re.compile(r"\{[^/}]+\}|%7B[^/]*?%7D", re.IGNORECASE)

#: A path segment that looks like a *value* rather than a sub-resource name:
#: a number, a uuid, or an explicit template. `/foo/1` is an id beneath `/foo`;
#: `/foo/status` is a different endpoint.
_VALUE_SHAPED_SEGMENT = re.compile(
    r"\d+|\{[^/}]+\}|%7B[^/]*?%7D|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _is_null_token(value: Any) -> bool:
    """Return whether ``value`` is one of the template's "no value" spellings."""
    return str(value if value is not None else "").strip().lower() in NULL_TOKENS


def _coerce_status(value: Any) -> int | None:
    """Parse a ``Response status`` cell into an int, or ``None``. Never raises."""
    if _is_null_token(value):
        return None
    match = re.search(r"\d{3}", str(value))
    return int(match.group()) if match else None


def _coerce_bool(value: Any) -> bool | None:
    """Parse a ``Y``/``N``-style cell. Empty yields ``None``, not ``False``."""
    if isinstance(value, bool):
        return value
    if _is_null_token(value):
        return None
    text = str(value).strip().lower()
    if text in {"y", "yes", "true", "1"}:
        return True
    if text in {"n", "no", "false", "0"}:
        return False
    return None


def _parse_json_or_none(text: Any) -> Any | None:
    """Best-effort JSON parse that tolerates prose wrapped around the payload."""
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text

    raw = str(text).strip()
    if not raw:
        return None

    # Template placeholders such as {{empCode}} are not valid JSON. Substitute a
    # neutral string so the surrounding structure still parses — this mirrors
    # inferSchemaFromRawBody() in scripts/generate-api-file.js.
    candidates = [raw, re.sub(r"\{\{\s*[^}]+?\s*}}", "__variable__", raw)]
    for candidate in list(candidates):
        for opener, closer in (("{", "}"), ("[", "]")):
            start = candidate.find(opener)
            end = candidate.rfind(closer)
            if start != -1 and end > start:
                candidates.append(candidate[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (TypeError, ValueError):
            continue
    return None


def infer_json_schema(value: Any) -> dict[str, Any]:
    """Infer a Draft 2020-12 schema from a sample payload.

    Mirrors ``inferJsonSchema()`` in ``scripts/generate-api-file.js`` so the repo
    has one inference behaviour rather than two: arrays are typed from their
    first element, objects require every observed key, and unobserved extra keys
    are permitted (no ``additionalProperties: false``) because a sample proves
    presence, never absence.
    """
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {
                str(key): infer_json_schema(child) for key, child in value.items()
            },
            "required": [str(key) for key in value],
        }
    if isinstance(value, list):
        if not value:
            return {"type": "array"}
        return {"type": "array", "items": infer_json_schema(value[0])}
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    return {"type": "string"}


class PayloadType:
    """The four ``Sample_Payloads.Payload Type`` values, as they appear in the sheet."""

    REQUEST_BODY = "Request Body"
    SUCCESS_RESPONSE = "Success Response"
    ERROR_REQUEST_BODY = "Error Request Body"
    ERROR_RESPONSE = "Error Response"

    @staticmethod
    def normalize(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip().lower()


@dataclass(frozen=True)
class SamplePayload:
    """One ``Sample_Payloads`` row."""

    payload_type: str
    response_status: int | None = None
    sample_json: Any = None

    @property
    def kind(self) -> str:
        return PayloadType.normalize(self.payload_type)


@dataclass(frozen=True)
class ApiRule:
    """One ``Rules_Dependencies_EdgeCases`` row.

    Free prose, deliberately unparsed. In particular no SLA is extracted from
    text like "Expected response time < 500ms" — that reads as structured data
    but is a human note, and mining it would invent a contract nobody agreed to.
    """

    category: str = ""
    description: str = ""


@dataclass(frozen=True)
class ApiDefinition:
    """A single API as supplied by an out-of-band source.

    This is the Sprint 2 seam: the Excel and cURL adapters populate this shape
    and nothing downstream needs to know which one produced it. Field names
    follow the ``API_Overview`` sheet.
    """

    api_id: str = ""
    name: str = ""
    module: str = ""
    purpose: str = ""
    owner: str = ""
    method: str = ""
    path: str = ""
    base_url: str = ""
    auth_type: str = ""
    idempotent: str = ""
    environments: str = ""
    api_version: str = ""
    last_updated: str = ""
    curl: str = ""
    collection_link: str = ""
    #: Query parameters, kept apart from `path`. The template has no query
    #: column, so a definition writes them into `Endpoint Path` as
    #: `/leaves/report?month=4`; they are split off at construction so `path`
    #: is always a bare path. A path carrying a query string would never match
    #: an OpenAPI entry and would corrupt any URL built by appending to it.
    query: dict[str, str] = field(default_factory=dict)
    payloads: tuple[SamplePayload, ...] = ()
    rules: tuple[ApiRule, ...] = ()
    #: No ``Auth Provider API ID`` column exists in the template. The run
    #: manifest supplies this per-API in Sprint 2; it stays None here.
    auth_provider_api_id: str | None = None

    @property
    def operation_key(self) -> tuple[str, str]:
        return (str(self.method).upper(), str(self.path))

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ApiDefinition":
        """Build a definition from a plain mapping, tolerating template headers.

        Accepts both snake_case field names and the literal ``API_Overview``
        column headers, so a hand-written JSON definition and a Sprint 2 Excel
        adapter can feed the same constructor.
        """
        aliases = {
            "api id": "api_id",
            "api / feature name": "name",
            "module": "module",
            "purpose": "purpose",
            "owner / dev contact": "owner",
            "http method": "method",
            "base url": "base_url",
            "endpoint path": "path",
            "auth type": "auth_type",
            "idempotent (y/n)": "idempotent",
            "environment(s)": "environments",
            "api version": "api_version",
            "last updated": "last_updated",
            "curl": "curl",
            "postman collection link": "collection_link",
        }
        known = {
            f
            for f in cls.__dataclass_fields__
            if f not in {"payloads", "rules", "query"}
        }
        values: dict[str, Any] = {}

        for raw_key, raw_value in (data or {}).items():
            key = str(raw_key).strip()
            name = aliases.get(key.lower(), key.lower().replace(" ", "_"))
            if name in known and raw_value is not None:
                values[name] = raw_value

        payloads = tuple(
            SamplePayload(
                payload_type=str(row.get("Payload Type", row.get("payload_type", ""))),
                response_status=_coerce_status(
                    row.get("Response status", row.get("response_status"))
                ),
                sample_json=_parse_json_or_none(
                    row.get("Sample JSON", row.get("sample_json"))
                ),
            )
            for row in (data.get("payloads") or data.get("Sample_Payloads") or [])
            if isinstance(row, dict)
        )
        rules = tuple(
            ApiRule(
                category=str(row.get("Category", row.get("category", ""))),
                description=str(row.get("Description", row.get("description", ""))),
            )
            for row in (data.get("rules") or data.get("Rules_Dependencies_EdgeCases") or [])
            if isinstance(row, dict)
        )
        path, query = _split_query(values.get("path", ""))
        values["path"] = path
        return cls(**values, query=query, payloads=payloads, rules=rules)


@dataclass(frozen=True)
class BaseUrlResolution:
    """The outcome of resolving one module's base URL.

    ``url`` is ``None`` both when nothing matched and when *too much* matched —
    :attr:`ambiguous_keys` tells the two apart. Never raises, so a caller turns
    either into a NOT_APPLICABLE naming what it looked for.
    """

    url: str | None
    key: str
    searched_keys: tuple[str, ...] = ()
    ambiguous_keys: tuple[str, ...] = ()

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous_keys)

    def describe_failure(self) -> str:
        if self.is_ambiguous:
            return (
                f"module matches more than one registered base URL key "
                f"({', '.join(self.ambiguous_keys)}); rename the module or "
                "unregister one so exactly one matches"
            )
        return (
            f"no base URL registered for {self.key} "
            f"(looked for: {', '.join(self.searched_keys) or self.key})"
        )


@dataclass(frozen=True)
class ContractSources:
    """The two git-tracked contract sources, loaded once per session."""

    api_rows: tuple[dict[str, Any], ...]
    openapi: dict[str, Any]


@dataclass(frozen=True)
class ResolvedMetadata:
    """Everything the tier needs about one operation, with provenance."""

    method: str
    path: str
    api_row: dict[str, Any] | None
    definition: ApiDefinition | None
    documented_status_codes: frozenset[int]
    documented_content_types: dict[int, frozenset[str]]
    requires_bearer_auth: bool
    sla_ms: int | None
    required_role: str | None
    idempotent: bool | None
    max_payload_bytes: int | None
    paginated: bool | None
    auth_provider_api_id: str | None = None
    #: Field name -> which source supplied it. Purely diagnostic.
    provenance: dict[str, str] = field(default_factory=dict, repr=False)


@lru_cache(maxsize=1)
def load_contract_sources() -> ContractSources:
    """Load both git-tracked contract sources. Raises only on a corrupt repo file."""
    with API_FILE_PATH.open(encoding="utf-8-sig") as handle:
        api_rows = json.load(handle)

    with OPENAPI_PATH.open(encoding="utf-8") as handle:
        openapi = yaml.safe_load(handle)

    if not isinstance(api_rows, list):
        raise TypeError(f"{API_FILE_PATH} must contain a JSON array")
    if not isinstance(openapi, dict):
        raise TypeError(f"{OPENAPI_PATH} must contain an OpenAPI object")

    return ContractSources(api_rows=tuple(api_rows), openapi=openapi)


def _load_definitions_from_env() -> tuple[ApiDefinition, ...]:
    """Load hand-written or platform-supplied definitions named by an env var.

    Sprint 1 seam only: it lets a definition be exercised end to end before the
    Excel and cURL parsers exist. Never raises — an unreadable or malformed file
    yields no definitions and the tier falls back to the git-tracked sources.
    """
    location = os.environ.get(_DEFINITIONS_ENV_VAR, "").strip()
    if not location:
        return ()

    path = Path(location)
    if not path.is_absolute():
        path = ROOT_DIR / path

    try:
        with path.open(encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return ()

    if isinstance(payload, dict):
        payload = payload.get("apis") or payload.get("definitions") or [payload]
    if not isinstance(payload, list):
        return ()

    definitions: list[ApiDefinition] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        try:
            definition = ApiDefinition.from_mapping(entry)
        except (TypeError, ValueError):
            continue
        if definition.method and definition.path:
            definitions.append(definition)
    return tuple(definitions)


class MetadataResolver:
    """Resolves operation metadata across every source. Never raises."""

    def __init__(
        self,
        sources: ContractSources,
        definitions: tuple[ApiDefinition, ...] = (),
    ) -> None:
        self._sources = sources
        self._definitions = {d.operation_key: d for d in definitions}
        self._warnings: list[str] = []

    # ---------------------------------------------------------------- sources

    @property
    def sources(self) -> ContractSources:
        return self._sources

    @property
    def warnings(self) -> tuple[str, ...]:
        """Structured warnings raised while resolving. Diagnostic, never fatal."""
        return tuple(self._warnings)

    def _warn(self, message: str) -> None:
        if message not in self._warnings:
            self._warnings.append(message)

    def operation_keys(self) -> tuple[tuple[str, str], ...]:
        """Every method/path this resolver knows about, OpenAPI first."""
        keys: list[tuple[str, str]] = []
        for path, path_item in self._openapi_paths().items():
            if not isinstance(path_item, dict):
                continue
            for method_name in path_item:
                if str(method_name).lower() in HTTP_METHODS:
                    key = (str(method_name).upper(), str(path))
                    if key not in keys:
                        keys.append(key)

        for key in self._definitions:
            if key not in keys:
                keys.append(key)
        return tuple(keys)

    # ------------------------------------------------------- source accessors
    # Every direct subscript into the OpenAPI document lives below this line and
    # nowhere else in tests/global_contract/.

    def _openapi_paths(self) -> dict[str, Any]:
        paths = self._sources.openapi.get("paths")
        return paths if isinstance(paths, dict) else {}

    def openapi_operation(self, method: str, path: str) -> dict[str, Any] | None:
        """Return the OpenAPI operation object, or ``None`` if absent."""
        path_item = self._openapi_paths().get(path)
        if not isinstance(path_item, dict):
            return None
        operation = path_item.get(str(method).lower())
        return operation if isinstance(operation, dict) else None

    def openapi_components(self) -> dict[str, Any]:
        components = self._sources.openapi.get("components")
        return components if isinstance(components, dict) else {}

    def definition(self, method: str, path: str) -> ApiDefinition | None:
        return self._definitions.get((str(method).upper(), str(path)))

    def register_definition(self, definition: ApiDefinition) -> None:
        """Add a definition supplied by value, e.g. from a run manifest.

        Definitions travel inside the manifest and live only for this run (DR-2).
        Nothing is written to disk and ``openapi.yaml`` is not modified.
        """
        if definition is not None and definition.method and definition.path:
            self._definitions[definition.operation_key] = definition

    def inventory_rows(self, method: str, path: str) -> tuple[dict[str, Any], ...]:
        """Every inventory row matching this method and path."""
        wanted_method = str(method).upper()
        return tuple(
            row
            for row in self._sources.api_rows
            if str(row.get("HTTP Method", "")).upper() == wanted_method
            and str(row.get("Endpoint / Path", "")) == path
        )

    @staticmethod
    def inventory_status_codes(api_row: dict[str, Any]) -> frozenset[int]:
        """Scrape ``Expected status(es): NNN`` out of a generated inventory row."""
        response_spec = str((api_row or {}).get("Response (example/200)", ""))
        match = re.search(r"Expected status\(es\):\s*([0-9,\s]+)", response_spec)
        if not match:
            return frozenset()
        return frozenset(int(code) for code in re.findall(r"\d{3}", match.group(1)))

    def declares_path_variables(self, method: str, path: str) -> bool:
        """Whether this endpoint routes a path variable beneath it.

        Matters because ``test_404_for_unknown_route`` probes for an unknown
        route by appending a segment. Where the endpoint accepts a path variable
        the appended segment is a *valid route with a malformed id*, so a 400 is
        correct and the mutation cannot tell the two cases apart. Asserting 404
        there produces a failure that is neither an API defect nor a tier defect.

        Four signals, any one sufficient:

        1. the OpenAPI path template contains ``{...}``
        2. the declared path contains ``{...}`` — raw or percent-encoded, which
           is how the inventory records it
        3. an inventory row declares a ``path variables:`` section
        4. a sibling row extends this exact path by one *value-shaped* segment

        The fourth carries the weight in practice. ``/api/attendancepolicy``
        declares no variable of its own, but ``/api/attendancepolicy/1`` and
        ``/2`` exist alongside it, which is what proves the family routes an id
        beneath it. A sub-resource name like ``/status`` is deliberately not
        value-shaped, so ``/foo`` plus ``/foo/status`` is not treated as
        parameterized.
        """
        method = str(method).upper()

        for path_key in self._openapi_paths():
            if "{" in str(path_key) and str(path_key) != path:
                if str(path_key).split("{", 1)[0].rstrip("/") == str(path).rstrip("/"):
                    return True

        if _PATH_VARIABLE_MARKER.search(str(path or "")):
            return True

        for row in self.inventory_rows(method, path):
            if "path variables" in str(row.get("Request Parameters", "")).lower():
                return True

        base = str(path or "").rstrip("/")
        if not base:
            return False
        for row in self._sources.api_rows:
            candidate = str(row.get("Endpoint / Path", "") or "").rstrip("/")
            if not candidate.startswith(f"{base}/"):
                continue
            remainder = candidate[len(base) + 1 :]
            if "/" in remainder:
                continue  # two or more segments deeper; not this endpoint's id
            if _VALUE_SHAPED_SEGMENT.fullmatch(remainder):
                return True
        return False

    def resolve_ref(self, ref: str) -> dict[str, Any] | None:
        """Resolve a manifest ``ref`` to an inventory row, or ``None``.

        A ``ref`` points at exactly one thing: the inventory's
        ``API Identifier``. There is deliberately **no fallback chain**.

        Sprint 2 matched ``Sr. No``, ``METHOD /path`` and
        ``Module / Sub-Module`` as well, because nothing said what a ref pointed
        at. Every one of those was a chance to resolve to something the caller
        did not mean, and a ref is never needed for an uploaded API anyway:
        under DR-2 an upload always travels by value, so re-running one re-sends
        its ``definition``.

        The template's ``API-001`` style IDs are **platform display labels**.
        They are scoped to whoever filled in the sheet, will collide across
        uploads, and must never be used for resolution.

        Returns ``None`` rather than raising: an unresolvable ref must degrade
        that one API to NOT_APPLICABLE, never fail collection for the batch.
        """
        wanted = str(ref or "").strip()
        if not wanted:
            return None
        folded = wanted.casefold()

        candidates = [
            row
            for row in self._sources.api_rows
            if str(row.get("API Identifier", "")).casefold() == folded
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # Several rows share one identifier — typically a Bruno row and a
        # collections row for the same operation, and they can point at
        # *different hosts*. This is disambiguation within a single identifier,
        # not a fallback to a different one, so it stays: deferring to
        # select_api_row() keeps a ref and the tier's own row selection from
        # disagreeing. Picking the wrong row here mints a token against the
        # wrong host, and every request that uses it comes back 401 for no
        # visible reason.
        preferred = self.select_api_row(
            str(candidates[0].get("HTTP Method", "")),
            str(candidates[0].get("Endpoint / Path", "")),
        )
        return preferred if preferred is not None else candidates[0]

    def select_api_row(self, method: str, path: str) -> dict[str, Any] | None:
        """Pick the best inventory row for this operation.

        Returns ``None`` rather than raising when nothing matches — an API with
        no inventory row must not take down collection for every other API in
        the batch.
        """
        matching_rows = self.inventory_rows(method, path)
        if not matching_rows:
            return None

        successful_rows = [
            row
            for row in matching_rows
            if any(200 <= code < 300 for code in self.inventory_status_codes(row))
        ]
        preferred_rows = successful_rows or list(matching_rows)
        collection_rows = [
            row
            for row in preferred_rows
            if str(row.get("Comments", "")).startswith("Source: collections/")
        ]
        return (collection_rows or preferred_rows)[0]

    def error_inventory_rows(self, method: str, path: str) -> tuple[dict[str, Any], ...]:
        """Inventory rows whose documented expected status is 4xx or worse.

        These are the rows the session fires to obtain an error sample. See the
        guardrail comment at the pairing site in the test module.
        """
        return tuple(
            row
            for row in self.inventory_rows(method, path)
            if any(code >= 400 for code in self.inventory_status_codes(row))
        )

    # -------------------------------------------------------- payload helpers

    def _definition_payloads(self, method: str, path: str, kind: str) -> tuple[SamplePayload, ...]:
        definition = self.definition(method, path)
        if definition is None:
            return ()
        wanted = PayloadType.normalize(kind)
        return tuple(p for p in definition.payloads if p.kind == wanted)

    def error_payload_pairs(
        self, method: str, path: str
    ) -> tuple[tuple[SamplePayload, SamplePayload], ...]:
        """Pair the Nth ``Error Request Body`` with the Nth ``Error Response``.

        Pairing is by sheet row order for a single API ID. When the counts
        differ, pair what is available and record a structured warning naming
        the API ID rather than raising — a lopsided sheet must not take the
        tier down.

        GUARDRAIL — error-triggering requests must provoke *validation or auth*
        errors, never state changes. These fire against UAT on every run. A
        DELETE with a malformed ID is a valid trigger; a DELETE with a real ID
        that actually deletes something is not. Whoever authors an
        ``Error Request Body`` row owns that distinction.
        """
        requests = self._definition_payloads(method, path, PayloadType.ERROR_REQUEST_BODY)
        responses = self._definition_payloads(method, path, PayloadType.ERROR_RESPONSE)

        if len(requests) != len(responses):
            definition = self.definition(method, path)
            api_id = (definition.api_id if definition else "") or f"{method} {path}"
            self._warn(
                f"error-sample-pairing-mismatch api_id={api_id!r} "
                f"error_request_bodies={len(requests)} error_responses={len(responses)}; "
                "paired the overlapping rows and ignored the remainder"
            )

        return tuple(zip(requests, responses))

    def request_body_sample(self, method: str, path: str) -> Any | None:
        """The happy-path request body for this operation, as parsed JSON.

        Precedence: OpenAPI request-body example, then the definition's
        ``Request Body`` payload row, then the inventory ``Request Body`` column.
        Returns ``None`` when the operation takes no body.
        """
        operation = self.openapi_operation(method, path)
        if isinstance(operation, dict):
            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content")
                if isinstance(content, dict):
                    media = content.get(DEFAULT_CONTENT_TYPE) or next(
                        (v for v in content.values() if isinstance(v, dict)), None
                    )
                    if isinstance(media, dict):
                        example = media.get("example")
                        if isinstance(example, (dict, list)):
                            return example
                        schema = media.get("schema")
                        if isinstance(schema, dict) and isinstance(
                            schema.get("example"), (dict, list)
                        ):
                            return schema["example"]

        for payload in self._definition_payloads(method, path, PayloadType.REQUEST_BODY):
            if payload.sample_json is not None:
                return payload.sample_json

        api_row = self.select_api_row(method, path)
        if api_row is not None:
            parsed = _parse_json_or_none(api_row.get("Request Body"))
            if parsed is not None:
                return parsed
        return None

    def raw_request_body_text(self, method: str, path: str) -> str:
        """The inventory's literal ``Request Body`` text, templates intact."""
        api_row = self.select_api_row(method, path)
        return str((api_row or {}).get("Request Body", "") or "")

    def has_request_body(self, method: str, path: str) -> bool:
        """Whether this operation accepts a request body, per any source.

        Replaces the collection-time expression
        ``openapi["paths"][path][method].get("requestBody")``, which KeyErrors
        for any API the spec has never seen — i.e. every uploaded API.
        """
        operation = self.openapi_operation(method, path)
        if isinstance(operation, dict) and isinstance(operation.get("requestBody"), dict):
            return True
        if self._definition_payloads(method, path, PayloadType.REQUEST_BODY):
            return True
        return bool(self.raw_request_body_text(method, path).strip())

    # ------------------------------------------------------- schema resolution

    def response_schema_document(
        self, method: str, path: str, status_code: int
    ) -> dict[str, Any] | None:
        """Return a Draft 2020-12 schema for this status, or ``None``.

        OpenAPI wins where it defines the status. Otherwise the schema is
        *inferred* from the definition's ``Success Response`` / ``Error Response``
        sample matched by ``Response status``, and failing that from the
        inventory row's recorded example payload.
        """
        document = self._openapi_response_schema(method, path, status_code)
        if document is not None:
            return document

        document = self._definition_response_schema(method, path, status_code)
        if document is not None:
            return document

        return self._inventory_response_schema(method, path, status_code)

    def _openapi_response_schema(
        self, method: str, path: str, status_code: int
    ) -> dict[str, Any] | None:
        operation = self.openapi_operation(method, path)
        if not isinstance(operation, dict):
            return None

        responses = operation.get("responses")
        if not isinstance(responses, dict):
            return None

        response_definition = responses.get(str(status_code))
        if not isinstance(response_definition, dict):
            response_definition = responses.get(f"{status_code // 100}XX")
        if not isinstance(response_definition, dict):
            return None

        content = response_definition.get("content")
        if not isinstance(content, dict):
            return None
        json_content = content.get(DEFAULT_CONTENT_TYPE)
        if not isinstance(json_content, dict):
            return None
        response_schema = json_content.get("schema")
        if not isinstance(response_schema, dict):
            return None

        document: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "components": self.openapi_components(),
        }
        document.update(response_schema)
        return document

    def _definition_response_schema(
        self, method: str, path: str, status_code: int
    ) -> dict[str, Any] | None:
        definition = self.definition(method, path)
        if definition is None:
            return None

        response_kinds = {
            PayloadType.normalize(PayloadType.SUCCESS_RESPONSE),
            PayloadType.normalize(PayloadType.ERROR_RESPONSE),
        }
        candidates = [
            payload
            for payload in definition.payloads
            if payload.kind in response_kinds and payload.sample_json is not None
        ]

        exact = [p for p in candidates if p.response_status == status_code]
        if not exact:
            # Fall back to the same status class, so a documented 400 sample
            # still describes an observed 422 rather than nothing at all.
            exact = [
                p
                for p in candidates
                if p.response_status is not None
                and p.response_status // 100 == status_code // 100
            ]
        if not exact:
            return None

        document = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
        document.update(infer_json_schema(exact[0].sample_json))
        return document

    def _inventory_response_schema(
        self, method: str, path: str, status_code: int
    ) -> dict[str, Any] | None:
        rows = [
            row
            for row in self.inventory_rows(method, path)
            if status_code in self.inventory_status_codes(row)
        ]
        for row in rows:
            sample = _parse_json_or_none(row.get("Example Response Payload")) or (
                _parse_json_or_none(row.get("Response (example/200)"))
            )
            if sample is not None:
                document = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
                document.update(infer_json_schema(sample))
                return document
        return None

    # ------------------------------------------------------------ base URL (T8)

    @staticmethod
    def module_key_candidates(module: str) -> tuple[str, ...]:
        """Turn a Module value into environment-key stems, most specific first.

        ``"HCM - Attendance Management"`` -> ``("ATTENDANCE_MANAGEMENT", "ATTENDANCE")``
        ``"Employee Auth API"``           -> ``("EMPLOYEE_AUTH", "EMPLOYEE", "AUTH")``

        Every stem is tried, so the existing ``AUTH_BASE_URL`` /
        ``LEAVE_BASE_URL`` / ``ATTENDANCE_BASE_URL`` keys keep resolving without
        a lookup table of module names.
        """
        tokens = [
            token.upper()
            for token in re.split(r"[^A-Za-z0-9]+", str(module or ""))
            if token
        ]
        meaningful = [t for t in tokens if t not in GENERIC_MODULE_TOKENS]
        if not meaningful:
            meaningful = tokens

        candidates: list[str] = []
        if len(meaningful) > 1:
            candidates.append("_".join(meaningful))
        candidates.extend(meaningful)

        deduped: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        return tuple(deduped)

    @staticmethod
    def base_url_keys(module: str, environment: str | None = None) -> tuple[str, ...]:
        """Every environment-variable name that could supply this module's host.

        Ordered ``<MODULE>_BASE_URL_<ENV>`` before ``<MODULE>_BASE_URL``, and
        within each tier the full normalized module name before its individual
        tokens. Diagnostic — :meth:`resolve_base_url` is what actually picks.
        """
        stems = MetadataResolver.module_key_candidates(module)
        env = MetadataResolver._normalize_environment(environment)

        keys: list[str] = []
        if env:
            keys.extend(f"{stem}_BASE_URL_{env}" for stem in stems)
        keys.extend(f"{stem}_BASE_URL" for stem in stems)
        return tuple(keys)

    @staticmethod
    def _normalize_environment(environment: str | None) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", str(environment or "")).strip("_").upper()

    def resolve_base_url(
        self,
        module: str,
        runtime_config: dict[str, str],
        environment: str | None = None,
        literal_base_url: str = "",
    ) -> "BaseUrlResolution":
        """Resolve a base URL to exactly one registered key, or to nothing.

        Order, per T0.3:

        1. ``<MODULE>_BASE_URL_<ENV>`` — full normalized module name, then each
           individual token
        2. ``<MODULE>_BASE_URL`` — same two steps without the env suffix
        3. the literal ``Base URL`` column on the definition
        4. nothing — the caller reports NOT_APPLICABLE naming the key it wanted

        Within a tier the match must be **unique**. If two tokens both name
        registered keys the result is an explicit ambiguity, never a pick: a
        silently misrouted host is exactly the failure CI's hardcoded URLs exist
        to prevent, and it fails as a wrong-host pass rather than as an error.
        """
        config = runtime_config or {}
        env = self._normalize_environment(environment)
        stems = self.module_key_candidates(module)
        suffixes = ([f"_BASE_URL_{env}"] if env else []) + ["_BASE_URL"]

        for suffix in suffixes:
            # Step 1 — the full normalized module name. A single candidate, so
            # it can never be ambiguous; an exact module match always wins.
            full_key = f"{stems[0]}{suffix}" if stems else ""
            if full_key and str(config.get(full_key, "") or "").strip():
                return BaseUrlResolution(
                    url=str(config[full_key]).strip(),
                    key=full_key,
                    searched_keys=self.base_url_keys(module, environment),
                )

            # Step 2 — individual tokens, requiring exactly one registered hit.
            token_keys = [
                f"{stem}{suffix}"
                for stem in stems[1:]
                if str(config.get(f"{stem}{suffix}", "") or "").strip()
            ]
            if len(token_keys) > 1:
                return BaseUrlResolution(
                    url=None,
                    key=token_keys[0],
                    searched_keys=self.base_url_keys(module, environment),
                    ambiguous_keys=tuple(token_keys),
                )
            if len(token_keys) == 1:
                return BaseUrlResolution(
                    url=str(config[token_keys[0]]).strip(),
                    key=token_keys[0],
                    searched_keys=self.base_url_keys(module, environment),
                )

        literal = str(literal_base_url or "").strip()
        if literal:
            return BaseUrlResolution(
                url=literal,
                key="Base URL",
                searched_keys=self.base_url_keys(module, environment),
            )

        keys = self.base_url_keys(module, environment)
        return BaseUrlResolution(
            url=None,
            key=keys[0] if keys else "BASE_URL",
            searched_keys=keys,
        )

    # -------------------------------------------------------- field resolution

    def resolve(
        self,
        method: str,
        path: str,
        environment: str | None = None,
    ) -> ResolvedMetadata:
        """Resolve every ``OperationCase`` field for one operation. Never raises."""
        method = str(method).upper()
        operation = self.openapi_operation(method, path) or {}
        definition = self.definition(method, path)
        api_row = self.select_api_row(method, path)
        inventory_rows = self.inventory_rows(method, path)
        provenance: dict[str, str] = {}

        def record(name: str, source: str, value: Any) -> Any:
            provenance[name] = source
            return value

        # -- statuses ------------------------------------------------------
        openapi_responses = operation.get("responses")
        openapi_statuses = frozenset(
            int(code)
            for code in (openapi_responses if isinstance(openapi_responses, dict) else {})
            if str(code).isdigit()
        )
        definition_statuses = frozenset(
            payload.response_status
            for payload in (definition.payloads if definition else ())
            if payload.response_status is not None
        )
        inventory_statuses: frozenset[int] = frozenset().union(
            *(self.inventory_status_codes(row) for row in inventory_rows)
        ) if inventory_rows else frozenset()

        if openapi_statuses:
            statuses = record("documented_status_codes", "openapi", openapi_statuses)
        elif definition_statuses:
            statuses = record("documented_status_codes", "definition", definition_statuses)
        elif inventory_statuses:
            statuses = record("documented_status_codes", "inventory", inventory_statuses)
        else:
            # No source declares a status. Report NOT_APPLICABLE downstream —
            # never default to 200. tests/auto_generated/ hard-codes
            # `status_code == 200` regardless of method, so a DELETE returning
            # 204 fails there for no reason. Do not repeat that here.
            statuses = record("documented_status_codes", "none", frozenset())

        # -- content types --------------------------------------------------
        if openapi_statuses:
            content_types = record(
                "documented_content_types",
                "openapi",
                {
                    int(code): frozenset(
                        response.get("content", {}).keys()
                        if isinstance(response, dict)
                        else ()
                    )
                    for code, response in openapi_responses.items()
                    if str(code).isdigit()
                },
            )
        else:
            # Neither the template nor the inventory carries a content-type
            # column, so every declared status defaults to JSON.
            content_types = record(
                "documented_content_types",
                "definition" if definition_statuses else "inventory",
                {status: frozenset({DEFAULT_CONTENT_TYPE}) for status in statuses},
            )

        # -- bearer auth ----------------------------------------------------
        openapi_security = operation.get("security")
        if isinstance(openapi_security, list):
            requires_bearer = record(
                "requires_bearer_auth",
                "openapi",
                any(
                    isinstance(requirement, dict) and "bearerAuth" in requirement
                    for requirement in openapi_security
                ),
            )
        elif definition is not None and str(definition.auth_type or "").strip():
            requires_bearer = record(
                "requires_bearer_auth",
                "definition",
                "bearer" in str(definition.auth_type).lower(),
            )
        elif api_row is not None:
            requires_bearer = record(
                "requires_bearer_auth",
                "inventory",
                bool(
                    re.search(
                        r"authorization\s*=\s*bearer",
                        str(api_row.get("Request Parameters", "")),
                        re.IGNORECASE,
                    )
                ),
            )
        else:
            requires_bearer = record("requires_bearer_auth", "none", False)

        # -- scalar x-* fields ----------------------------------------------
        sla_ms = self._first_hit(
            "sla_ms",
            provenance,
            (("openapi", operation.get("x-sla-ms")),),
            default=DEFAULT_SLA_MS,
        )
        # Only openapi's x-required-role supplies this. `Auth Type` is not a
        # role — "Bearer Token" says how you authenticate, not who you must be —
        # and the template has no role column, so everything else yields None.
        required_role = self._first_hit(
            "required_role",
            provenance,
            (("openapi", operation.get("x-required-role")),),
        )
        max_payload_bytes = self._first_hit(
            "max_payload_bytes",
            provenance,
            (("openapi", operation.get("x-max-payload-bytes")),),
            default=DEFAULT_MAX_PAYLOAD_BYTES,
        )
        paginated = self._first_hit(
            "paginated",
            provenance,
            (("openapi", operation.get("x-paginated")),),
        )

        # -- idempotency ----------------------------------------------------
        openapi_idempotent = operation.get("x-idempotent")
        definition_idempotent = (
            _coerce_bool(definition.idempotent) if definition is not None else None
        )
        if isinstance(openapi_idempotent, bool):
            idempotent = record("idempotent", "openapi", openapi_idempotent)
        elif definition_idempotent is not None:
            idempotent = record("idempotent", "definition", definition_idempotent)
        elif api_row is not None:
            # Inferred, and deliberately conservative: the idempotency check
            # replays the request, so only replay-safe methods are inferred
            # idempotent. Replaying a PUT or DELETE against UAT would be a
            # state change. An explicit declaration above still wins.
            idempotent = record(
                "idempotent", "inventory", method in REPLAY_SAFE_METHODS
            )
        else:
            idempotent = record("idempotent", "none", None)

        return ResolvedMetadata(
            method=method,
            path=path,
            api_row=api_row,
            definition=definition,
            documented_status_codes=statuses,
            documented_content_types=content_types,
            requires_bearer_auth=requires_bearer,
            sla_ms=sla_ms,
            required_role=required_role,
            idempotent=idempotent,
            max_payload_bytes=max_payload_bytes,
            # No `Auth Provider API ID` column exists. The run manifest supplies
            # this per-API in Sprint 2.
            auth_provider_api_id=(
                definition.auth_provider_api_id if definition is not None else None
            ),
            paginated=paginated,
            provenance=provenance,
        )

    @staticmethod
    def _first_hit(
        name: str,
        provenance: dict[str, str],
        candidates: tuple[tuple[str, Any], ...],
        default: Any = None,
    ) -> Any:
        """Walk a precedence chain; ``None`` is a miss, not a value."""
        for source, value in candidates:
            if value is not None:
                provenance[name] = source
                return value
        provenance[name] = "default" if default is not None else "none"
        return default


_REGISTERED_DEFINITIONS: tuple[ApiDefinition, ...] = ()


def register_api_definitions(definitions: tuple[ApiDefinition, ...]) -> None:
    """Install out-of-band API definitions and invalidate the cached resolver.

    Sprint 2's Excel and cURL adapters call this before collection. Definitions
    registered after collection has begun will not affect already-parameterized
    tests.
    """
    global _REGISTERED_DEFINITIONS
    _REGISTERED_DEFINITIONS = tuple(definitions)
    get_resolver.cache_clear()


@lru_cache(maxsize=1)
def get_resolver() -> MetadataResolver:
    """The shared resolver. Cached because parametrization calls it repeatedly."""
    definitions = _REGISTERED_DEFINITIONS or _load_definitions_from_env()
    return MetadataResolver(load_contract_sources(), definitions)


# ---------------------------------------------------------------------------
# Definition -> inventory row
# ---------------------------------------------------------------------------
# Both upload adapters (Excel, cURL) emit two things: an ApiDefinition for the
# resolver, and a dict shaped like an api-docs/API_File.json row so
# perform_api_request() works unchanged. The row projection lives here, next to
# ApiDefinition, so there is exactly one of it rather than one per adapter.


#: Methods that carry no request body. For these, a `Request Body` or
#: `Error Request Body` sample is applied as query-parameter overrides.
BODYLESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _split_query(path: str) -> tuple[str, dict[str, str]]:
    """Split `/leaves/report?month=4` into its path and its query parameters."""
    raw = str(path or "")
    if "?" not in raw:
        return raw, {}

    endpoint, _, query_text = raw.partition("?")
    query: dict[str, str] = {}
    for pair in query_text.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        if key:
            query[key] = value
    return endpoint, query


def _flat_query_overrides(sample_text: str) -> dict[str, str]:
    """Read a flat JSON object as query parameters. Nested values are ignored."""
    parsed = _parse_json_or_none(sample_text)
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): ("" if value is None else str(value))
        for key, value in parsed.items()
        if not isinstance(value, (dict, list))
    }


def _payloads_of(definition: ApiDefinition, kind: str) -> tuple[SamplePayload, ...]:
    wanted = PayloadType.normalize(kind)
    return tuple(p for p in definition.payloads if p.kind == wanted)


def _sample_text(payload: SamplePayload | None) -> str:
    """Render a sample back to JSON text for an inventory row."""
    if payload is None or payload.sample_json is None:
        return ""
    if isinstance(payload.sample_json, str):
        return payload.sample_json
    return json.dumps(payload.sample_json, ensure_ascii=False)


def build_request_parameters(
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    path_variables: dict[str, str] | None = None,
) -> str:
    """Render the pipe-delimited `Request Parameters` string the helper parses.

    Shape: ``headers: k=v; k2=v2 | query: k=v | path variables: id=1``
    """
    sections: list[str] = []
    for label, values in (
        ("headers", headers),
        ("query", query),
        ("path variables", path_variables),
    ):
        if not values:
            continue
        rendered = "; ".join(f"{k}={v}" for k, v in values.items() if k)
        if rendered:
            sections.append(f"{label}: {rendered}")
    return " | ".join(sections)


def definition_to_inventory_row(
    definition: ApiDefinition,
    *,
    source: str = "uploaded",
    base_url: str | None = None,
) -> dict[str, Any]:
    """Project an ApiDefinition into an `API_File.json`-shaped request row.

    The key names below are not decorative — ``perform_api_request()`` and the
    global tests read these exact strings. `Response (example/200)` in
    particular must carry the ``Expected status(es): NNN`` prefix, because
    ``_inventory_status_codes()`` scrapes the status back out of it with a regex.

    Nothing is written to ``api-docs/API_File.json``; this row exists only for
    the duration of the run (DR-2).
    """
    headers: dict[str, str] = {}
    method = str(definition.method or "GET").upper()

    # Query parameters were split off `Endpoint Path` when the definition was
    # built, so `path` here is always bare.
    endpoint_path, inline_query = _split_query(definition.path)
    query = {**dict(definition.query or {}), **inline_query}

    request_body = _payloads_of(definition, PayloadType.REQUEST_BODY)
    body_text = _sample_text(request_body[0] if request_body else None)

    if method in BODYLESS_METHODS:
        # A GET has no body to carry a sample in, so a flat `Request Body`
        # object is read as query overrides instead. This is what lets a GET API
        # have a happy path and an error trigger at all — see error_trigger_rows.
        query.update(_flat_query_overrides(body_text))
        body_text = ""

    if body_text.strip():
        headers["Content-Type"] = DEFAULT_CONTENT_TYPE

    requires_bearer = "bearer" in str(definition.auth_type or "").lower()
    if requires_bearer:
        # Written as a template so _build_headers() resolves it from the
        # bootstrapped token rather than from anything baked into the row.
        headers["Authorization"] = "Bearer {{authToken}}"

    success = _payloads_of(definition, PayloadType.SUCCESS_RESPONSE)
    success_payload = success[0] if success else None
    success_status = (
        success_payload.response_status
        if success_payload is not None and success_payload.response_status is not None
        else 200
    )
    response_spec = f"Expected status(es): {success_status}"
    success_text = _sample_text(success_payload)
    if success_text.strip():
        response_spec = f"{response_spec}\n{success_text}"

    return {
        "Sr. No": "",
        "Module Name": definition.module or "",
        "Sub-Module Name": definition.name or "",
        "Access": "public" if not requires_bearer else "authenticated",
        "Functional Purpose": definition.purpose or "",
        "Base URL": base_url if base_url is not None else (definition.base_url or ""),
        "Endpoint / Path": endpoint_path,
        "HTTP Method": method,
        "Request Parameters": build_request_parameters(headers=headers, query=query),
        "Request Body": body_text,
        "Example Request Payload": body_text,
        "Request Body Schema": (
            json.dumps(infer_json_schema(_parse_json_or_none(body_text)))
            if body_text.strip()
            else ""
        ),
        "Response (example/200)": response_spec,
        "Example Response Payload": success_text,
        # Left empty deliberately: auth is supplied by the manifest's
        # authProviderApiId bootstrap, not by an inventory dependency string.
        "Dependent APIs / Services": "",
        "Owner / Developer": definition.owner or "",
        "API Identifier": "|".join(
            [
                str(definition.method or "").lower(),
                str(definition.base_url or "").lower(),
                str(definition.path or ""),
                str(definition.module or "").lower(),
                str(definition.api_id or "").lower(),
            ]
        ),
        "Comments": f"Source: {source}",
    }


def error_trigger_rows(
    definition: ApiDefinition,
    base_row: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Build one request row per `Error Request Body` / `Error Response` pair.

    GUARDRAIL — these fire against UAT on every run. An `Error Request Body`
    must provoke a *validation or auth* error, never a state change. A DELETE
    with a malformed ID is a valid trigger; a DELETE with a real ID that
    actually deletes something is not. Whoever authors the row owns that
    distinction, and no amount of downstream care can undo a row that deletes.

    Pairing is Nth-to-Nth in sheet order. Mismatched counts pair what they can;
    the caller warns rather than raising.
    """
    requests = _payloads_of(definition, PayloadType.ERROR_REQUEST_BODY)
    responses = _payloads_of(definition, PayloadType.ERROR_RESPONSE)

    method = str(base_row.get("HTTP Method", "")).upper()
    rows: list[dict[str, Any]] = []

    for error_request, error_response in zip(requests, responses):
        status = error_response.response_status
        spec = f"Expected status(es): {status}" if status is not None else ""
        sample = _sample_text(error_response)
        if spec and sample.strip():
            spec = f"{spec}\n{sample}"

        trigger_row = {
            **base_row,
            "Response (example/200)": spec,
            "Example Response Payload": sample,
            "Comments": f"{base_row.get('Comments', '')}; error-trigger pair",
        }

        request_text = _sample_text(error_request)
        if method in BODYLESS_METHODS:
            # A GET's invalid request is an invalid *query*, not an invalid body.
            # Overriding the happy-path parameters is what makes a validation
            # trigger expressible for a read-only endpoint — and read-only is the
            # only kind that can be triggered safely in the first place.
            trigger_row["Request Parameters"] = _with_query_overrides(
                str(base_row.get("Request Parameters", "")),
                _flat_query_overrides(request_text),
            )
        else:
            trigger_row["Request Body"] = request_text

        rows.append(trigger_row)
    return tuple(rows)


def _with_query_overrides(
    request_parameters: str,
    overrides: dict[str, str],
) -> str:
    """Return ``request_parameters`` with its query section overridden."""
    if not overrides:
        return request_parameters

    sections: list[str] = []
    query: dict[str, str] = {}
    for raw_section in str(request_parameters or "").split("|"):
        section = raw_section.strip()
        if not section or ":" not in section:
            continue
        label, value = section.split(":", 1)
        if label.strip().lower() == "query":
            for pair in value.split(";"):
                key, _, item = pair.partition("=")
                if key.strip():
                    query[key.strip()] = item.strip()
        else:
            sections.append(section)

    query.update(overrides)
    rendered = "; ".join(f"{k}={v}" for k, v in query.items())
    if rendered:
        sections.append(f"query: {rendered}")
    return " | ".join(sections)

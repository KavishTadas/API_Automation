"""Global contract checks for active HCM endpoints.

These checks are metadata-driven, not endpoint-coupled: every operation the
:mod:`~tests.global_contract.metadata_resolver` knows about is parameterized
through the same twelve tests. Metadata comes from ``openapi/openapi.yaml``
first, then a supplied API definition, then the generated inventory — see the
resolver for the full precedence chain.

Result states
-------------
Pytest reports pass/fail/skip; the QA platform needs the seven states in
:mod:`~tests.global_contract.result_states`. States that are neither PASS nor
FAIL travel as a structured prefix on the skip reason
(``"NOT_APPLICABLE: no inventory row"``), which keeps them machine-readable
downstream and keeps them out of the pass-rate denominator. In particular a
check that could not apply, or that only observed and recorded, must never
render as a pass.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import allure
import httpx
import pytest
from jsonschema import Draft202012Validator

from tests.api_runtime._api_test_helpers import (
    _resolve_templates,
    load_runtime_config,
    perform_api_request,
)
from tests.global_contract.auth_bootstrap import (
    TOKEN_RUNTIME_KEYS,
    AuthBootstrap,
    BootstrapResult,
)
from tests.global_contract.metadata_resolver import (
    ContractSources,
    MetadataResolver,
    definition_to_inventory_row,
    error_trigger_rows,
    get_resolver,
    load_contract_sources,
)
from tests.global_contract.result_emitter import classify_gateway_failure
from tests.global_contract.result_states import ResultState, format_reason
from tests.global_contract.run_manifest import (
    ManifestValidationError,
    load_manifest_from_env,
    registered_environments_from,
)


#: T7 — CORS preflight is opt-in. These are internal server-to-server APIs
#: behind a WAF; requiring Access-Control-* headers they were never meant to
#: emit would go red across the board and mean nothing. Sprint 2's run manifest
#: can set this alongside the environment variable.
CORS_PREFLIGHT_FLAG = "GLOBAL_CONTRACT_ENABLE_CORS_PREFLIGHT"

#: Names the target environment for base-URL resolution (T8).
ENVIRONMENT_FLAG = "API_TEST_ENV"

#: Substituted into string fields of an API's own request-body sample by
#: test_special_characters_in_input.
SPECIAL_CHARACTER_SAMPLE = "ÉMP-测试-😀-🔒"

#: The tier this module implements. A manifest must request it by name.
GLOBAL_CONTRACT_TIER = "global_contract"

#: The operation the session bootstraps a bearer token from.
#:
#: This is the one place the tier is still deliberately endpoint-coupled. The
#: template has no `Auth Provider API ID` column, so nothing yet says which API
#: mints a token for which other API — Sprint 2's run manifest supplies that
#: per-API, and MetadataResolver exposes `auth_provider_api_id` as the seam it
#: lands on. Until then the suite's single known token provider stands in.
BOOTSTRAP_AUTH_OPERATION = ("POST", "/auth/token")


@dataclass(frozen=True)
class OperationCase:
    method: str
    path: str
    #: ``None`` when no inventory row matches. Tests that need a request row
    #: report NOT_APPLICABLE rather than failing on absence.
    api_row: dict[str, Any] | None
    documented_status_codes: frozenset[int]
    documented_content_types: dict[int, frozenset[str]]
    requires_bearer_auth: bool
    sla_ms: int | None
    required_role: str | None
    idempotent: bool | None
    max_payload_bytes: int | None
    paginated: bool | None
    #: Manifest identity. Empty when running without a manifest.
    entry_id: str = ""
    auth_provider_api_id: str | None = None
    credential_alias: str | None = None
    #: Scheme+host this case targets, used to deduplicate host-level probes.
    host: str = ""
    #: Set when a manifest ref could not be resolved. The case still collects,
    #: so the API reports NOT_APPLICABLE for all 12 tests rather than vanishing.
    unresolved_reason: str | None = None
    #: Which source supplied ``idempotent``: "openapi" or "definition" mean a
    #: human declared it, "inventory" means it was inferred from the method.
    #: Only a declared value carries RFC semantics -- see
    #: test_declared_idempotency_matches_method.
    idempotent_source: str = ""

    @property
    def label(self) -> str:
        return self.entry_id or f"{self.method} {self.path}"

    @property
    def api_ref(self) -> str:
        """The key a result joins to the catalogue on.

        The inventory's ``API Identifier`` wherever there is one — that is what
        the catalogue emits. An uploaded API has no inventory row (DR-2), so it
        falls back to its manifest identity.
        """
        identifier = str((self.api_row or {}).get("API Identifier", "") or "")
        return identifier or self.label

    @property
    def provenance(self) -> dict[str, Any]:
        """Where this API came from. Mirrors the existing report tagging."""
        row = self.api_row or {}
        comments = str(row.get("Comments", ""))
        match = re.search(r"Source:\s*([^;]+)", comments)
        source = match.group(1).strip() if match else ""
        if source.startswith("collections/"):
            source_type = "newman"
        elif source.startswith("bruno/"):
            source_type = "bruno"
        elif source.startswith("uploaded/"):
            source_type = source.split("/", 1)[1]
        else:
            source_type = "unknown"
        return {
            "sourceType": source_type,
            "sourceCollection": source or None,
            "sourceModule": str(row.get("Module Name", "")) or None,
            "owner": str(row.get("Owner / Developer", "")) or None,
        }


@dataclass
class GlobalContractContext:
    sources: ContractSources
    runtime_config: dict[str, str] = field(repr=False)
    bootstrap_responses: dict[tuple[str, str], httpx.Response] = field(repr=False)
    response_samples: dict[tuple[str, str], tuple[httpx.Response, ...]] = field(
        repr=False
    )
    #: Wall-clock duration of each bootstrap request, in milliseconds. Recorded
    #: here so the SLA check can report timing without issuing its own request.
    bootstrap_durations_ms: dict[tuple[str, str], float] = field(
        default_factory=dict, repr=False
    )
    #: One entry per distinct (authProviderApiId, credentialAlias) pair.
    auth_results: dict[tuple[str, str], BootstrapResult] = field(
        default_factory=dict, repr=False
    )

    def auth_result_for(self, operation_case: OperationCase) -> BootstrapResult | None:
        """The bootstrap outcome for this API, or ``None`` if it needs no auth."""
        if not operation_case.auth_provider_api_id:
            return None
        key = (
            operation_case.auth_provider_api_id,
            operation_case.credential_alias or "",
        )
        return self.auth_results.get(key)

    def config_for(self, operation_case: OperationCase) -> dict[str, str]:
        """Runtime config carrying this API's own token.

        Two APIs naming different providers get different tokens, and each one's
        token is routed only to it. The bootstrapped value deliberately wins over
        any ambient AUTH_TOKEN — a stale CI secret previously defeated the
        bootstrap and surfaced as unexplained 401s.
        """
        result = self.auth_result_for(operation_case)
        if result is None or not result.succeeded:
            return self.runtime_config
        return {**self.runtime_config, **result.runtime_overrides()}


def _resolver() -> MetadataResolver:
    return get_resolver()


def _target_environment() -> str:
    return os.environ.get(ENVIRONMENT_FLAG, "").strip()


def _cors_preflight_enabled() -> bool:
    return os.environ.get(CORS_PREFLIGHT_FLAG, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _record_state(
    state: ResultState, detail: str, field: str = "", provider: str = ""
) -> str:
    """Record a non-PASS/FAIL outcome so downstream tooling can read it back.

    Returns the formatted reason so callers can hand it straight to
    ``pytest.skip``.
    """
    reason = format_reason(state, detail, field, provider)
    print(reason)
    allure.attach(
        reason,
        name=f"Result state: {state.name}",
        attachment_type=allure.attachment_type.TEXT,
    )
    return reason


def _skip_with_state(
    state: ResultState, detail: str, field: str = "", provider: str = ""
) -> None:
    """End the current test in ``state``, carrying a machine-readable reason.

    ``field`` names the metadata that was missing, so a consumer can tell the
    user what to fill in rather than making them read prose and guess.

    ``provider`` names the auth provider whose bootstrap blocked the API, which
    the emitter surfaces as ``blockedBy``. Same motivation: a blocked row is
    only actionable once the consumer knows which credential to fix.
    """
    pytest.skip(_record_state(state, detail, field, provider))


def _require_runnable(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext | None = None,
) -> dict[str, Any]:
    """Return the request row, or end the test in the state that explains why not.

    Three ways an API can be unrunnable, and they are not the same thing:

    * the manifest entry never resolved      -> NOT_APPLICABLE
    * no request row could be built          -> NOT_APPLICABLE
    * its auth provider did not give a token -> SKIPPED_NO_TOKEN

    The last one is why this is not just a null check. An API whose token
    bootstrap failed was never executed; reporting it as FAIL would claim it was
    tested and found broken.
    """
    if operation_case.unresolved_reason:
        _skip_with_state(ResultState.NOT_APPLICABLE, operation_case.unresolved_reason)

    if operation_case.api_row is None:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"no inventory row for {operation_case.method} {operation_case.path}",
            field="api_row",
        )

    if global_contract_context is not None:
        result = global_contract_context.auth_result_for(operation_case)
        if result is not None and not result.succeeded:
            _skip_with_state(
                ResultState.SKIPPED_NO_TOKEN,
                f"{operation_case.label} (BLOCKED: {result.provider_id} failed) — "
                f"{result.reason}",
                provider=result.provider_id,
            )

    return operation_case.api_row


def _require_api_row(operation_case: OperationCase) -> dict[str, Any]:
    """Backwards-compatible alias for :func:`_require_runnable`."""
    return _require_runnable(operation_case)


def _load_contract_sources() -> ContractSources:
    """Backwards-compatible alias; the loader now lives in the resolver."""
    return load_contract_sources()


def _inventory_status_codes(api_row: dict[str, Any]) -> frozenset[int]:
    return MetadataResolver.inventory_status_codes(api_row)


@lru_cache(maxsize=1)
def _load_manifest() -> Any:
    """Load the run manifest, or ``None`` when none was supplied.

    ``None`` is the pre-Sprint-2 path: the tier enumerates ``openapi.yaml``
    exactly as before, which is what keeps the no-manifest run a regression-free
    no-op.
    """
    try:
        return load_manifest_from_env(
            registered_environments_from(_runtime_config_snapshot())
        )
    except ManifestValidationError as error:
        # A malformed manifest is a caller error, not a test failure, and it is
        # worth stopping for — running "some" of a batch the caller did not ask
        # for is worse than refusing. The message names JSON paths, never values.
        raise pytest.UsageError(str(error)) from error


@lru_cache(maxsize=1)
def _runtime_config_snapshot() -> dict[str, str]:
    """Runtime config read at collection time, for host and base-URL resolution.

    Layered environment-last so a CI-supplied ``<MODULE>_BASE_URL_<ENV>`` is
    visible: ``load_runtime_config()`` reads ``.env`` and the Postman
    environment file only, and it is a generated artifact this sprint must not
    edit. An explicit local ``.env`` value still wins over the ambient one.
    """
    try:
        config = load_runtime_config()
    except Exception:  # pragma: no cover - config loading is defensive
        config = {}
    return {**os.environ, **config}


def _derive_host(api_row: dict[str, Any] | None) -> str:
    """Resolve a row's Base URL to ``scheme://host``, or ``""``.

    Host-level probes are deduplicated on this, so a templated ``{{baseUrl}}``
    has to be resolved before it can be compared.
    """
    if not api_row:
        return ""
    raw = str(api_row.get("Base URL", "") or "")
    if not raw:
        return ""
    resolved = _resolve_templates(raw, _runtime_config_snapshot())
    if "{{" in resolved:
        return ""
    split = urlsplit(resolved if "://" in resolved else f"https://{resolved}")
    return f"{split.scheme}://{split.netloc}" if split.netloc else ""


def _case_from_metadata(
    metadata: Any,
    *,
    entry_id: str = "",
    api_row: dict[str, Any] | None = None,
    auth_provider_api_id: str | None = None,
    credential_alias: str | None = None,
    unresolved_reason: str | None = None,
) -> OperationCase:
    row = api_row if api_row is not None else metadata.api_row
    return OperationCase(
        method=metadata.method,
        path=metadata.path,
        api_row=row,
        documented_status_codes=metadata.documented_status_codes,
        documented_content_types=metadata.documented_content_types,
        requires_bearer_auth=metadata.requires_bearer_auth,
        sla_ms=metadata.sla_ms,
        required_role=metadata.required_role,
        idempotent=metadata.idempotent,
        idempotent_source=str(metadata.provenance.get("idempotent", "") or ""),
        max_payload_bytes=metadata.max_payload_bytes,
        paginated=metadata.paginated,
        entry_id=entry_id,
        auth_provider_api_id=auth_provider_api_id,
        credential_alias=credential_alias,
        host=_derive_host(row),
        unresolved_reason=unresolved_reason,
    )


def _unresolved_case(entry: Any, reason: str) -> OperationCase:
    """A placeholder case for an entry that could not be resolved.

    The API still appears in the run and still produces a result for all twelve
    tests — as NOT_APPLICABLE. Dropping it instead would leave the platform
    showing an API that simply is not there, with nothing to join against.
    """
    return OperationCase(
        method="",
        path="",
        api_row=None,
        documented_status_codes=frozenset(),
        documented_content_types={},
        requires_bearer_auth=False,
        sla_ms=None,
        required_role=None,
        idempotent=None,
        max_payload_bytes=None,
        paginated=None,
        entry_id=entry.identifier,
        auth_provider_api_id=entry.auth_provider_api_id,
        credential_alias=entry.credential_alias,
        unresolved_reason=reason,
    )


def _cases_from_manifest(manifest: Any) -> tuple[OperationCase, ...]:
    """Enumerate from the manifest's ``apis[]`` instead of the OpenAPI paths.

    Metadata still resolves through the Sprint 1 precedence chain (DR-1) — the
    manifest chooses *which* APIs run, not where their metadata comes from.
    """
    resolver = _resolver()
    environment = manifest.environment or _target_environment()
    cases: list[OperationCase] = []

    for entry in manifest.entries_for_tier(GLOBAL_CONTRACT_TIER):
        try:
            if entry.definition is not None:
                definition = entry.definition
                resolver.register_definition(definition)
                base_url = _definition_base_url(resolver, definition, environment)
                if base_url is None:
                    cases.append(
                        _unresolved_case(
                            entry,
                            resolver.resolve_base_url(
                                definition.module,
                                _runtime_config_snapshot(),
                                environment,
                                definition.base_url,
                            ).describe_failure(),
                        )
                    )
                    continue
                api_row = definition_to_inventory_row(
                    definition,
                    source=f"uploaded/{_definition_source(definition)}",
                    base_url=base_url,
                )
                metadata = resolver.resolve(
                    definition.method, definition.path, environment=environment
                )
            else:
                api_row = resolver.resolve_ref(entry.ref)
                if api_row is None:
                    cases.append(
                        _unresolved_case(
                            entry,
                            f"manifest ref {entry.ref!r} matched no inventory row",
                        )
                    )
                    continue
                api_row = _with_registered_base_url(resolver, api_row, environment)
                metadata = resolver.resolve(
                    str(api_row.get("HTTP Method", "")).upper(),
                    str(api_row.get("Endpoint / Path", "")),
                    environment=environment,
                )

            cases.append(
                _case_from_metadata(
                    metadata,
                    entry_id=entry.identifier,
                    api_row=api_row,
                    auth_provider_api_id=entry.auth_provider_api_id,
                    credential_alias=entry.credential_alias,
                )
            )
        except Exception as error:  # pragma: no cover - nothing escapes collection
            cases.append(
                _unresolved_case(
                    entry,
                    f"could not be prepared ({type(error).__name__})",
                )
            )

    return tuple(cases)


def _with_registered_base_url(
    resolver: Any,
    api_row: dict[str, Any],
    environment: str,
) -> dict[str, Any]:
    """Apply module-based base-URL precedence to an inventory row.

    A `ref` entry previously took the inventory's ``Base URL`` verbatim, while an
    inline definition resolved its host from the registered
    ``<MODULE>_BASE_URL_<ENV>`` keys. That split meant the same API reached two
    different hosts depending on how it was named — and since the platform uses
    `ref` for every repo-defined API, the referenced form was the one getting the
    stale host. The 13 Attendance rows carry ``{{baseURL}}``, which resolves to
    ``BASE_URL`` rather than ``ATTENDANCE_BASE_URL``.

    Precedence matches the inline path exactly: registered env-scoped key,
    registered unscoped key, then the row's own ``Base URL``. Where a module's
    registered key holds the same value the row already had — Auth and Leave —
    this is a no-op.

    The row is copied, never mutated: ``api-docs/API_File.json`` is a generated
    artifact and the fix that belongs in it is a regeneration, not an edit.
    """
    module = str(api_row.get("Module Name", "") or "")
    declared = str(api_row.get("Base URL", "") or "")
    if not module or not declared:
        return api_row

    config = _runtime_config_snapshot()

    # Only rows that name no host of their own are re-pointed. A row written as
    # `{{authBaseUrl}}` or as a literal URL has already chosen; overriding that
    # would silently move traffic somebody deliberately aimed. Only the generic
    # `{{baseURL}}` fallback — which is what all 13 Attendance rows carry — is
    # treated as "unspecified".
    if _resolve_templates(declared, config).strip() != str(
        config.get("BASE_URL", "") or ""
    ).strip():
        return api_row

    # The registered key must match the module's *leading* token, not any token.
    # Matching any token lets a generic word hijack a specific module: "Login
    # Auth UAT API" contains AUTH, and AUTH_BASE_URL points at the dev host —
    # which would have moved the one provider that mints tokens the UAT
    # Attendance platform accepts. "Attendance Policy Master" leads with
    # ATTENDANCE and is re-pointed correctly.
    stems = resolver.module_key_candidates(module)
    leading = stems[-1] if len(stems) == 1 else (stems[1] if len(stems) > 1 else "")
    if not leading:
        return api_row

    resolution = resolver.resolve_base_url(leading, config, environment, "")
    if resolution.url is None or resolution.is_ambiguous:
        # Nothing registered for this module, or more than one candidate matched.
        # Either way, leave the row as authored rather than guessing at a host.
        return api_row

    return {**api_row, "Base URL": resolution.url}


def _definition_source(definition: Any) -> str:
    return "curl" if str(definition.curl or "").strip() else "excel"


def _definition_base_url(resolver: Any, definition: Any, environment: str) -> str | None:
    resolution = resolver.resolve_base_url(
        definition.module,
        _runtime_config_snapshot(),
        environment,
        definition.base_url,
    )
    return resolution.url


@lru_cache(maxsize=1)
def _build_operation_cases() -> tuple[OperationCase, ...]:
    """Build one case per selected operation. Never raises.

    With a manifest, the manifest's ``apis[]`` is the enumeration source. Without
    one, this falls back to iterating ``openapi.yaml`` exactly as before.

    Both former ``ValueError`` sites remain gone. An operation with no inventory
    row gets ``api_row=None``; an operation with no declared statuses gets an
    empty ``documented_status_codes``. Each is reported as NOT_APPLICABLE by the
    tests that need it, so one unusable API can no longer take collection down
    for every other API in the batch.
    """
    manifest = _load_manifest()
    if manifest is not None:
        return _cases_from_manifest(manifest)

    resolver = _resolver()
    environment = _target_environment()
    cases: list[OperationCase] = []

    for method, path in resolver.operation_keys():
        try:
            metadata = resolver.resolve(method, path, environment=environment)
        except Exception as error:  # pragma: no cover - resolver is non-raising
            # Belt and braces: nothing may escape collection, including a
            # deliberately malformed definition that reaches an unforeseen path.
            print(
                format_reason(
                    ResultState.NOT_APPLICABLE,
                    f"{method} {path} metadata could not be resolved: "
                    f"{type(error).__name__}",
                )
            )
            continue

        cases.append(_case_from_metadata(metadata))

    return tuple(cases)


@lru_cache(maxsize=1)
def _host_representatives() -> dict[str, str]:
    """The one case label that actually probes each distinct host.

    The burst and oversized-payload checks measure **gateway** behaviour, not
    endpoint behaviour. Running them per API meant a 45-API batch across three
    hosts issued 450 burst requests and ~45 MB of uploads to test three hosts
    forty-five times — against infrastructure this project does not own, and
    against the repo's standing position that these probes stay bounded.

    So the *probe* is deduplicated by host while the *result* stays per API:
    every API still reports for all twelve tests, but only the representative
    for its host sends traffic. The rest reference it. Three hosts costs 30
    burst requests and 3 oversized payloads whether the batch holds 5 APIs or
    500, and a 46th API on an existing host adds nothing.
    """
    return {
        host: case.label for host, case in _host_representative_cases().items()
    }


@lru_cache(maxsize=1)
def _host_representative_cases() -> dict[str, OperationCase]:
    """The single case that probes each host. One source of truth.

    Both the label used in the skip message and the ``apiRef`` published as
    ``measuredBy`` are derived from this, so the two can never name different
    cases for the same host.
    """
    representatives: dict[str, OperationCase] = {}
    for case in _build_operation_cases():
        if case.host and case.host not in representatives:
            representatives[case.host] = case
    return representatives


@lru_cache(maxsize=1)
def host_measured_by() -> dict[str, str]:
    """Map each host to the ``apiRef`` that actually carries its measurement.

    Public because ``conftest.py`` reads it when building result records. This
    is what the result document publishes as ``measuredBy``, and it is present
    on *every* host-level result — including the representative's own, where it
    equals the result's ``apiRef``. Emitting it unconditionally is the point:
    a consumer renders "measured by X" from one field without having to know
    whether this row is the one that did the measuring.

    It replaces inferring that relationship from the skip reason's prose, which
    only ever worked for rows that reached the dedup check.
    """
    return {
        host: case.api_ref for host, case in _host_representative_cases().items()
    }


def _require_host_representative(operation_case: OperationCase) -> None:
    """End the test unless this case is the one that probes its host."""
    if not operation_case.host:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.label} has no resolvable host to probe",
        )

    representative = _host_representatives().get(operation_case.host)
    if representative != operation_case.label:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"host-level probe for {operation_case.host} is reported against "
            f"{representative!r}; this is a gateway property, not an endpoint "
            "property, so it is measured once per host rather than once per API",
        )


def build_contract_params(*, xfail_auth_waf: bool = False) -> list[Any]:
    """Build one pytest parameter per active OpenAPI method/path operation."""
    return [
        pytest.param(
            case,
            id=f"{case.method} {case.path}",
            marks=(
                pytest.mark.xfail(
                    reason=(
                        "Org-wide WAF/gateway appears to enforce strict route+header "
                        "allowlisting on *.omfysgroup.com hosts, independent of app "
                        "logic — see SECURITY.md / escalation history"
                    ),
                    strict=False,
                )
                if xfail_auth_waf
                and (case.method, case.path) == ("POST", "/auth/token")
                else ()
            ),
        )
        for case in _build_operation_cases()
    ]


def build_bearer_auth_negative_params() -> list[Any]:
    """Build missing/invalid-token parameters for every operation.

    Unsecured operations are filtered inside the test body, not here: a case
    filtered out at collection time produces no result at all, leaving the
    platform with an unexplained gap and Sprint 3's catalogue nothing to join
    against.
    """
    params: list[Any] = []
    for case in _build_operation_cases():
        params.extend(
            [
                pytest.param(
                    case,
                    None,
                    id=f"{case.method} {case.path}-missing-token",
                ),
                pytest.param(
                    case,
                    "Bearer invalid-token-value",
                    id=f"{case.method} {case.path}-invalid-token",
                ),
            ]
        )
    return params


def _api_row_with_authorization(
    api_row: dict[str, Any],
    authorization: str | None,
) -> dict[str, Any]:
    """Return a request row with exactly the requested Authorization state."""
    request_sections: list[str] = []
    headers: list[str] = []

    for raw_section in str(api_row.get("Request Parameters", "")).split("|"):
        section = raw_section.strip()
        if not section or ":" not in section:
            continue

        label, value = section.split(":", 1)
        normalized_label = label.strip().lower()
        if normalized_label == "headers":
            headers.extend(
                header.strip()
                for header in value.split(";")
                if header.strip()
                and header.split("=", 1)[0].strip().lower() != "authorization"
            )
        elif normalized_label != "auth":
            request_sections.append(section)

    if authorization is not None:
        headers.append(f"Authorization={authorization}")
    if headers:
        request_sections.insert(0, f"headers: {'; '.join(headers)}")

    return {
        **api_row,
        "Request Parameters": " | ".join(request_sections),
        "Dependent APIs / Services": "",
    }


def _is_recoverable(error: BaseException) -> bool:
    """Whether one API's failure may be absorbed without ending the run.

    ``perform_api_request`` reports an unusable request row by calling
    ``pytest.skip``, and pytest's ``Skipped`` derives from ``BaseException`` —
    not ``Exception``. A plain ``except Exception`` therefore lets it escape the
    session fixture, and one API with, say, an unresolvable ``{{token}}``
    placeholder aborts the bootstrap for every other API in the batch. That is
    exactly the fail-soft invariant this tier exists to hold.

    Interrupts still propagate: the operator asked for those.
    """
    return not isinstance(error, (KeyboardInterrupt, SystemExit))


def _timed_request(
    api_row: dict[str, Any],
    runtime_config: dict[str, str],
) -> tuple[httpx.Response, float]:
    """Perform a request and return it alongside its wall-clock duration in ms."""
    started_at = time.perf_counter()
    response = perform_api_request(api_row, runtime_config)
    return response, (time.perf_counter() - started_at) * 1000


@pytest.fixture(scope="session")
def global_contract_context(request: pytest.FixtureRequest) -> GlobalContractContext:
    """Load both contracts and shared runtime credentials for the suite."""
    resolver = _resolver()
    sources = resolver.sources
    runtime_config = load_runtime_config()
    bootstrap_responses: dict[tuple[str, str], httpx.Response] = {}
    bootstrap_durations_ms: dict[tuple[str, str], float] = {}
    operation_cases = _build_operation_cases()

    # -- Auth provider bootstrap (T5) -----------------------------------------
    # Providers named by the manifest are called directly as token providers.
    # Their own collections are never run: doing so would fire their assertions,
    # and a failing auth assertion would then look like a failure of the API the
    # user actually selected.
    auth_bootstrap = AuthBootstrap(
        runtime_config,
        provider_row_for=lambda provider_id: _resolver().resolve_ref(provider_id),
    )
    for operation_case in operation_cases:
        auth_bootstrap.token_for(
            operation_case.auth_provider_api_id,
            operation_case.credential_alias,
        )
    auth_results = auth_bootstrap.results

    def _config_for(case: OperationCase) -> dict[str, str]:
        key = (case.auth_provider_api_id or "", case.credential_alias or "")
        result = auth_results.get(key)
        if result is None or not result.succeeded:
            return runtime_config
        return {**runtime_config, **result.runtime_overrides()}

    # Without a manifest there is no declared provider, so the suite's single
    # known token provider still bootstraps the session exactly as before.
    if not any(case.auth_provider_api_id for case in operation_cases):
        auth_case = next(
            (
                case
                for case in operation_cases
                if (case.method, case.path) == BOOTSTRAP_AUTH_OPERATION
                and case.api_row is not None
            ),
            None,
        )
        if auth_case is not None:
            auth_key = (auth_case.method, auth_case.path)
            auth_response, auth_duration = _timed_request(
                auth_case.api_row, runtime_config
            )
            bootstrap_responses[auth_key] = auth_response
            bootstrap_durations_ms[auth_key] = auth_duration
            if auth_response.is_success:
                token = auth_response.json().get("token")
                if token:
                    # Driven off the one list, so this site cannot drift from
                    # the names auth_bootstrap declares.
                    runtime_config.update(
                        {key: token for key in TOKEN_RUNTIME_KEYS}
                    )

    for operation_case in operation_cases:
        operation_key = (operation_case.method, operation_case.path)
        if operation_key in bootstrap_responses or operation_case.api_row is None:
            continue

        # An API whose token bootstrap failed is not executed at all — firing it
        # anyway would produce a 401 that looks like the API's own fault.
        auth_key = (
            operation_case.auth_provider_api_id or "",
            operation_case.credential_alias or "",
        )
        blocked = auth_results.get(auth_key)
        if operation_case.auth_provider_api_id and (
            blocked is None or not blocked.succeeded
        ):
            continue

        case_config = _config_for(operation_case)
        if operation_case.requires_bearer_auth and not any(
            case_config.get(key) for key in TOKEN_RUNTIME_KEYS
        ):
            # Secured, but nothing minted a token for it — most often a manifest
            # entry that omitted authProviderApiId. Record it as a bootstrap
            # miss so dependents report SKIPPED_NO_TOKEN, rather than letting the
            # request helper assert its way out of the session fixture and take
            # every other API in the batch down with it.
            auth_results.setdefault(
                auth_key,
                BootstrapResult(
                    provider_id=operation_case.auth_provider_api_id or "<none declared>",
                    credential_alias=operation_case.credential_alias or "",
                    reason=(
                        "did not get token: the operation requires a bearer token and "
                        "no authProviderApiId was declared for it"
                    ),
                ),
            )
            continue

        try:
            response, duration_ms = _timed_request(operation_case.api_row, case_config)
        except BaseException as error:
            if not _is_recoverable(error):
                raise
            # Nothing an individual API does may abort the shared session
            # fixture; that would turn one API's problem into the whole batch's.
            print(
                format_reason(
                    ResultState.NOT_APPLICABLE,
                    f"{operation_case.label} bootstrap request raised "
                    f"{type(error).__name__}; no response sample recorded",
                )
            )
            continue

        bootstrap_responses[operation_key] = response
        bootstrap_durations_ms[operation_key] = duration_ms

    response_samples: dict[tuple[str, str], tuple[httpx.Response, ...]] = {}
    for operation_case in operation_cases:
        operation_key = (operation_case.method, operation_case.path)
        bootstrap_response = bootstrap_responses.get(operation_key)
        samples = [bootstrap_response] if bootstrap_response is not None else []

        # Error samples come from inventory rows whose documented expected status
        # is 4xx. GUARDRAIL: an error-triggering request must provoke a
        # *validation or auth* error, never a state change — these fire against
        # UAT on every run. A DELETE with a malformed ID is a valid trigger; a
        # DELETE with a real ID that actually deletes something is not. The same
        # rule governs the template's `Error Request Body` rows, which
        # MetadataResolver.error_payload_pairs() pairs with their responses.
        if bootstrap_response is not None:
            case_config = _config_for(operation_case)
            for api_row in resolver.error_inventory_rows(
                operation_case.method, operation_case.path
            ):
                try:
                    samples.append(perform_api_request(api_row, case_config))
                except BaseException as error:
                    if not _is_recoverable(error):
                        raise
                    continue

            # An uploaded definition brings its own error triggers, paired
            # Nth-to-Nth from its `Error Request Body` / `Error Response` rows.
            definition = resolver.definition(operation_case.method, operation_case.path)
            if definition is not None and operation_case.api_row is not None:
                for trigger_row in error_trigger_rows(definition, operation_case.api_row):
                    try:
                        samples.append(perform_api_request(trigger_row, case_config))
                    except BaseException as error:
                        if not _is_recoverable(error):
                            raise
                        continue

        response_samples[operation_key] = tuple(samples)

    _register_gateway_classifications(request, operation_cases, bootstrap_responses)

    return GlobalContractContext(
        sources=sources,
        runtime_config=runtime_config,
        bootstrap_responses=bootstrap_responses,
        response_samples=response_samples,
        bootstrap_durations_ms=bootstrap_durations_ms,
        auth_results=auth_results,
    )


def _register_gateway_classifications(
    request: pytest.FixtureRequest,
    operation_cases: tuple[OperationCase, ...],
    bootstrap_responses: dict[tuple[str, str], httpx.Response],
) -> None:
    """Tell the result collector which failures were gateway blocks.

    An empty-bodied 403 means the request never reached the application, so
    nothing about the application was demonstrated. Without this the platform
    renders "blocked by the gateway" as "your API failed" — currently for the
    whole Attendance module.
    """
    collector = getattr(request.config, "_global_contract_collector", None)
    if collector is None:
        return

    request.config._global_contract_manifest = _load_manifest()
    for case in operation_cases:
        response = bootstrap_responses.get((case.method, case.path))
        if response is None:
            continue
        collector.record_gateway(
            case.api_ref,
            classify_gateway_failure(
                response.status_code, dict(response.headers), response.text
            ),
        )


@allure.title("Response status matches the OpenAPI contract — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_status_code_matches_spec(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    # Checked before the status metadata: an entry that never resolved has no
    # statuses *because* it never resolved, and "expected status not declared"
    # would name the symptom instead of the cause.
    api_row = _require_runnable(operation_case, global_contract_context)

    if not operation_case.documented_status_codes:
        # Never default to 200. tests/auto_generated/ hard-codes
        # `status_code == 200` regardless of method, so a DELETE returning 204
        # fails there on a contract nobody wrote. An undeclared status is
        # missing metadata, not a passing or failing assertion.
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "expected status not declared",
            field="documented_status_codes",
        )
    response = global_contract_context.bootstrap_responses.get(
        (operation_case.method, operation_case.path)
    )
    if response is None:
        response = perform_api_request(
            api_row,
            global_contract_context.config_for(operation_case),
        )

    assert response.status_code in operation_case.documented_status_codes, (
        f"{operation_case.method} {operation_case.path} returned "
        f"{response.status_code}; documented statuses are "
        f"{sorted(operation_case.documented_status_codes)}"
    )


@allure.title("Response body matches the full OpenAPI schema — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_response_matches_full_schema(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    responses = global_contract_context.response_samples.get(
        (operation_case.method, operation_case.path),
        (),
    )
    if not responses:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "no response sample available to validate",
        )

    observed_statuses: list[int] = []
    unschematized_statuses: list[int] = []

    for response in responses:
        observed_statuses.append(response.status_code)
        schema_document = _response_schema_document(
            operation_case,
            response.status_code,
        )
        if schema_document is None:
            # No source describes this status. test_status_code_matches_spec
            # already fails an undocumented status, so reporting it here too
            # would double-count one defect.
            unschematized_statuses.append(response.status_code)
            continue

        payload = _response_json(operation_case, response)
        errors = sorted(
            Draft202012Validator(schema_document).iter_errors(payload),
            key=lambda error: [str(part) for part in error.absolute_path],
        )

        assert not errors, (
            f"{operation_case.method} {operation_case.path} HTTP "
            f"{response.status_code} failed its complete response schema: "
            + "; ".join(_format_schema_error(error) for error in errors)
        )

    if unschematized_statuses:
        _record_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} has no response schema "
            f"for observed status(es) {sorted(set(unschematized_statuses))}",
        )

    # Without a success sample this test asserted nothing about the success
    # schema. That is an absence, not a defect -- and for a destructive verb it
    # is deliberate: the suite refuses to fire a real DELETE with a real id at
    # UAT, so no 2xx can ever be observed. Failing here punished the endpoint
    # for a guardrail the engine imposed on itself, and D7's mirror forbids it:
    # a request we chose not to make cannot be scored as a failure. The error
    # half below already reports its own absence the same way.
    if not any(200 <= status < 300 for status in observed_statuses):
        _skip_with_state(
            ResultState.NOT_ASSERTED,
            f"{operation_case.method} {operation_case.path} success-schema half not "
            f"validated: no success response was observed "
            f"(observed {observed_statuses or 'nothing'})",
        )

    # The error half is validated only when an error sample exists. It used to
    # be mandatory, which hard-failed every API that simply had no 4xx sample
    # row — a failure on absence rather than on merit.
    if not any(status >= 400 for status in observed_statuses):
        _record_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} error-schema half not "
            f"validated: no error sample available (observed {observed_statuses})",
        )


@allure.title("Response exposes no credentials or tokens — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_no_credential_leakage_in_response(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    responses = global_contract_context.response_samples.get(
        (operation_case.method, operation_case.path),
        (),
    )
    if not responses:
        # Nothing was executed, so nothing was inspected. Falling through the
        # loop would report a pass for a check that never ran — exactly the
        # accounting this tier must not produce.
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"no response sample to inspect for {operation_case.method} "
            f"{operation_case.path}",
        )

    for sample_index, response in enumerate(responses):
        payload = _response_json(operation_case, response)
        fields = _field_paths(payload)
        credential_paths = [
            path
            for field_name, path in fields
            if re.search(r"password|secret", field_name, re.IGNORECASE)
        ]
        assert not credential_paths, (
            f"{operation_case.method} {operation_case.path} HTTP "
            f"{response.status_code} exposed credential field(s): "
            f"{credential_paths}"
        )

        token_paths = [
            path
            for field_name, path in fields
            if re.sub(r"[^a-z0-9]", "", field_name.lower())
            in {"token", "authtoken"}
        ]
        is_expected_auth_success = (
            sample_index == 0
            and operation_case.method == "POST"
            and operation_case.path == "/auth/token"
            and response.status_code == 200
        )
        if is_expected_auth_success:
            assert token_paths == ["$.token"], (
                "POST /auth/token HTTP 200 must contain exactly one root token field; "
                f"observed token field paths: {token_paths}"
            )
        else:
            assert not token_paths, (
                f"{operation_case.method} {operation_case.path} HTTP "
                f"{response.status_code} unexpectedly exposed token field(s): "
                f"{token_paths}"
            )


@allure.title("Response completes within the documented SLA — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_response_time_within_sla(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    # Advisory, not blocking: exceeding the target emits WARN and leaves the
    # run's exit code alone. The old 20% buffer existed to prevent false
    # failures; with no failure to prevent it only delayed the signal, so the
    # flag fires at the target itself.
    threshold_ms = operation_case.sla_ms
    if threshold_ms is None:
        _skip_with_state(
            ResultState.NOT_APPLICABLE, "no SLA target resolved", field="sla_ms"
        )

    operation_key = (operation_case.method, operation_case.path)
    elapsed_ms = global_contract_context.bootstrap_durations_ms.get(operation_key)
    if elapsed_ms is None:
        # Measured during session bootstrap; this test issues no request of its
        # own. Advisory timing does not justify doubling SLA traffic across a
        # batch of APIs.
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"no bootstrap timing recorded for {operation_case.method} "
            f"{operation_case.path}",
        )

    measurement = (
        f"observed={elapsed_ms:.1f}ms threshold={threshold_ms}ms "
        f"operation={operation_case.method} {operation_case.path}"
    )
    print(f"SLA measurement {measurement}")

    if elapsed_ms > threshold_ms:
        _skip_with_state(
            ResultState.WARN,
            f"response time exceeded its advisory target: {measurement} "
            f"(over by {elapsed_ms - threshold_ms:.1f}ms)",
        )


@allure.title("Repeated GET requests return a stable result — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_idempotent_get_returns_stable_result(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    # Filtered here rather than in the parametrize expression: a case filtered
    # out at collection produces no result at all, so the platform sees 11 tests
    # for one API and 12 for another with nothing explaining the difference.
    if operation_case.idempotent is not True:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.label} is not declared idempotent, so a repeated "
            "request is not safe to send",
            field="idempotent",
        )
    first_response = perform_api_request(
        api_row,
        global_contract_context.config_for(operation_case),
    )
    second_response = perform_api_request(
        api_row,
        global_contract_context.config_for(operation_case),
    )

    assert first_response.status_code == second_response.status_code, (
        f"{operation_case.method} {operation_case.path} returned different statuses "
        f"for identical consecutive requests: first={first_response.status_code}, "
        f"second={second_response.status_code}"
    )

    first_payload = _response_json(operation_case, first_response)
    second_payload = _response_json(operation_case, second_response)
    assert isinstance(first_payload, dict) and isinstance(second_payload, dict), (
        f"{operation_case.method} {operation_case.path} must return JSON objects "
        "for structural idempotency comparison"
    )

    first_top_level_fields = frozenset(first_payload)
    second_top_level_fields = frozenset(second_payload)
    assert first_top_level_fields == second_top_level_fields, (
        f"{operation_case.method} {operation_case.path} returned different top-level "
        "fields for identical consecutive requests: "
        f"first={sorted(first_top_level_fields)}, "
        f"second={sorted(second_top_level_fields)}"
    )

    first_data = first_payload.get("data")
    second_data = second_payload.get("data")
    first_data_fields = (
        frozenset(first_data) if isinstance(first_data, dict) else frozenset()
    )
    second_data_fields = (
        frozenset(second_data) if isinstance(second_data, dict) else frozenset()
    )
    assert first_data_fields == second_data_fields, (
        f"{operation_case.method} {operation_case.path} returned different data "
        "structures for identical consecutive requests: "
        f"first={sorted(first_data_fields)}, second={sorted(second_data_fields)}"
    )

    first_records = (
        first_data.get("leaveReport") if isinstance(first_data, dict) else None
    )
    second_records = (
        second_data.get("leaveReport") if isinstance(second_data, dict) else None
    )
    first_record_count = len(first_records) if isinstance(first_records, list) else None
    second_record_count = len(second_records) if isinstance(second_records, list) else None
    assert first_record_count == second_record_count, (
        f"{operation_case.method} {operation_case.path} returned a different record "
        "count for identical consecutive requests: "
        f"first={first_record_count}, second={second_record_count}"
    )

    print(
        f"Idempotency observation {operation_case.method} {operation_case.path}: "
        f"status={first_response.status_code} both times; "
        f"record_count={first_record_count} both times; "
        f"top_level_fields={sorted(first_top_level_fields)}"
    )


#: Deliberate limit on infrastructure this project does not own. Ten sequential
#: requests establish only that a burst this small is not rejected; they do not
#: establish the actual rate-limit threshold. Do not raise this.
BURST_REQUEST_COUNT = 10


@allure.title("A small valid request burst is not immediately blocked — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_small_burst_does_not_trigger_immediate_blocking(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    _require_host_representative(operation_case)
    burst_row = api_row

    if operation_case.requires_bearer_auth:
        token = global_contract_context.config_for(operation_case).get("AUTH_TOKEN")
        if not token:
            _skip_with_state(
                ResultState.SKIPPED_NO_TOKEN,
                f"{operation_case.method} {operation_case.path} requires a bearer "
                "token and the session bootstrap did not provide one",
            )
        burst_row = _api_row_with_authorization(api_row, f"Bearer {token}")

    observed_statuses: list[int] = []

    for request_number in range(1, BURST_REQUEST_COUNT + 1):
        response = perform_api_request(
            burst_row,
            global_contract_context.config_for(operation_case),
        )
        observed_statuses.append(response.status_code)
        # The known WAF fingerprint: HTTP 403 with a completely empty body.
        # An application-level 403 carries a body; this one does not.
        has_waf_fingerprint = (
            response.status_code == 403 and not response.content.strip()
        )
        assert not has_waf_fingerprint, (
            "Small sequential burst was blocked with the known WAF fingerprint "
            f"(HTTP 403 with an empty body) at request {request_number} of "
            f"{operation_case.method} {operation_case.path}; "
            f"statuses observed before stopping: {observed_statuses}"
        )

    print(
        f"Small-burst observation {operation_case.method} {operation_case.path}: "
        f"statuses={observed_statuses}"
    )


@allure.title("Oversized payload exercises the documented size limit — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_request_payload_size_enforcement(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    _require_host_representative(operation_case)

    if operation_case.max_payload_bytes is None:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.label} has no payload ceiling to exercise",
            field="max_payload_bytes",
        )
    # Routed through the resolver, never a direct dict index. The old expression
    # subscripted the raw OpenAPI paths/method dicts inside the parametrize list
    # comprehension, which KeyErrors at *collection* time for any API absent
    # from the spec — i.e. every uploaded API.
    if not _resolver().has_request_body(operation_case.method, operation_case.path):
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.label} takes no request body, so there is no "
            "payload to oversize",
            field="request_body_sample",
        )

    oversized_body = _oversized_request_body(
        operation_case,
        operation_case.max_payload_bytes,
    )
    if oversized_body is None:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} has no request body "
            "sample to build an oversized payload from",
        )

    oversized_row = {**api_row, "Request Body": oversized_body}
    response = perform_api_request(
        oversized_row,
        global_contract_context.config_for(operation_case),
    )
    actual_request_bytes = len(response.request.content)
    assert actual_request_bytes > operation_case.max_payload_bytes, (
        f"Oversized request construction failed: expected more than "
        f"{operation_case.max_payload_bytes} bytes, got {actual_request_bytes}"
    )

    response_body = response.text
    configured_emp_code = (
        global_contract_context.runtime_config.get("EMP_CODE")
        or global_contract_context.runtime_config.get("empCode")
        or ""
    )
    if configured_emp_code:
        response_body = response_body.replace(configured_emp_code, "<redacted-emp-code>")

    try:
        response_payload = response.json()
    except ValueError:
        response_payload = None
    if response_payload is not None:
        sensitive_response_paths = [
            path
            for field_name, path in _field_paths(response_payload)
            if re.search(
                r"password|secret|token|emp[_-]?code",
                field_name,
                re.IGNORECASE,
            )
        ]
        if sensitive_response_paths:
            response_body = (
                "<response body withheld because it contained sensitive field(s): "
                f"{sensitive_response_paths}>"
            )

    observation = (
        f"{operation_case.method} {operation_case.path}: "
        f"request_bytes={actual_request_bytes}; "
        f"documented_limit={operation_case.max_payload_bytes}; "
        f"status={response.status_code}; response_body={response_body}"
    )
    print(f"Oversized payload observation {observation}")

    # This check asserts only that the *constructed request* exceeded the limit.
    # It never asserts anything about the response, so it must not render as a
    # pass — an observation that proved nothing about the API would otherwise
    # inflate the platform's headline number.
    _skip_with_state(
        ResultState.INFORMATIONAL,
        f"oversized payload observed, response not asserted — {observation}",
    )


@allure.title("Missing or invalid Bearer token returns HTTP 401 — {param_id}")
@pytest.mark.parametrize(
    ("operation_case", "authorization"),
    build_bearer_auth_negative_params(),
)
def test_401_without_valid_token(
    operation_case: OperationCase,
    authorization: str | None,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    if not operation_case.requires_bearer_auth:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"operation is not secured, so {operation_case.label} has no token "
            "state to reject",
            field="requires_bearer_auth",
        )
    response = perform_api_request(
        _api_row_with_authorization(api_row, authorization),
        global_contract_context.config_for(operation_case),
    )

    assert response.status_code == 401, (
        f"{operation_case.method} {operation_case.path} returned "
        f"{response.status_code} with "
        f"{'no Authorization header' if authorization is None else 'an invalid token'}"
    )


def _api_row_with_additional_headers(
    api_row: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    header_section = "; ".join(f"{name}={value}" for name, value in headers.items())
    request_parameters = str(api_row.get("Request Parameters", "")).strip()
    return {
        **api_row,
        "Request Parameters": " | ".join(
            section
            for section in (request_parameters, f"headers: {header_section}")
            if section
        ),
    }


def _response_media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _response_schema_document(
    operation_case: OperationCase,
    status_code: int,
) -> dict[str, Any] | None:
    """Return a Draft 2020-12 schema for this status, or ``None`` if none exists.

    Routed through the resolver so an Excel-derived schema — inferred from the
    definition's ``Success Response`` / ``Error Response`` sample, matched by
    ``Response status`` — is usable exactly like an OpenAPI one. Returns ``None``
    rather than raising, so an undocumented status is missing metadata, not a
    hard failure here.
    """
    schema_document = _resolver().response_schema_document(
        operation_case.method,
        operation_case.path,
        status_code,
    )
    if schema_document is None:
        return None

    try:
        Draft202012Validator.check_schema(schema_document)
    except Exception as error:
        _record_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} HTTP {status_code} "
            f"resolved an invalid schema ({type(error).__name__}); not validated",
        )
        return None
    return schema_document


def _response_json(
    operation_case: OperationCase,
    response: httpx.Response,
) -> Any:
    try:
        return response.json()
    except ValueError:
        pytest.fail(
            f"{operation_case.method} {operation_case.path} returned "
            f"non-JSON content for HTTP {response.status_code}; body withheld"
        )


def _format_schema_error(error: Any) -> str:
    instance_path = "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    )
    schema_path = "/".join(str(part) for part in error.absolute_schema_path)
    return f"{instance_path}: {error.validator} failed at schema/{schema_path}"


def _field_paths(value: Any, path: str = "$") -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            fields.append((key_text, child_path))
            fields.extend(_field_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.extend(_field_paths(child, f"{path}[{index}]"))
    return fields


def _string_field_paths(value: Any, path: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], str]]:
    """Every string leaf in a sample payload, as (path, value) pairs."""
    found: list[tuple[tuple[Any, ...], str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_string_field_paths(child, path + (key,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_string_field_paths(child, path + (index,)))
    elif isinstance(value, str):
        found.append((path, value))
    return found


def _set_in(payload: Any, path: tuple[Any, ...], new_value: Any) -> None:
    """Assign ``new_value`` at ``path`` inside a nested payload, in place."""
    target = payload
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = new_value


def _special_character_body(operation_case: OperationCase) -> str | None:
    """Substitute Unicode into every string field of the API's own sample body.

    Built from the target API's *own* request body rather than a fixed
    auth-shaped payload, so a non-auth endpoint is sent fields it actually has.
    """
    sample = _resolver().request_body_sample(operation_case.method, operation_case.path)
    if not isinstance(sample, (dict, list)):
        return None

    payload = json.loads(json.dumps(sample))
    string_fields = _string_field_paths(payload)
    if not string_fields:
        return None

    for field_path, _ in string_fields:
        field_name = str(field_path[-1]) if field_path else "field"
        _set_in(payload, field_path, f"{field_name}-{SPECIAL_CHARACTER_SAMPLE}")
    return json.dumps(payload, ensure_ascii=False)


def _oversized_request_body(
    operation_case: OperationCase,
    max_payload_bytes: int,
) -> str | None:
    """Pad the largest string field of the API's own sample body past the limit.

    Padding a field the target API actually declares matters: the old version
    hard-coded auth's shape, so firing it at an Attendance endpoint sent a giant
    ``password`` field to an API that has no such field. Every other field keeps
    its original value — including ``{{template}}`` placeholders, which the
    request helper still resolves.
    """
    resolver = _resolver()
    raw_body = resolver.raw_request_body_text(operation_case.method, operation_case.path)
    sample = _parse_body_preserving_templates(raw_body)
    if sample is None:
        sample = resolver.request_body_sample(operation_case.method, operation_case.path)
    if not isinstance(sample, (dict, list)):
        return None

    payload = json.loads(json.dumps(sample))
    string_fields = _string_field_paths(payload)
    if not string_fields:
        return None

    largest_path, _ = max(string_fields, key=lambda entry: (len(entry[1]), entry[0]))
    _set_in(payload, largest_path, "X" * (max_payload_bytes + 1))
    return json.dumps(payload, separators=(",", ":"))


def _parse_body_preserving_templates(raw_body: str) -> Any | None:
    """Parse a request body whose values may contain ``{{template}}`` placeholders.

    ``{{empCode}}`` is not valid JSON on its own but is valid *inside* a JSON
    string, which is how the inventory writes it — so a plain ``json.loads``
    already succeeds and the placeholders survive for the request helper to
    resolve. Returns ``None`` when the text is absent or genuinely unparseable.
    """
    text = str(raw_body or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def build_special_character_params() -> list[Any]:
    """One parameter per operation; the payload is built from its own sample."""
    return [
        pytest.param(case, id=f"{case.method} {case.path}")
        for case in _build_operation_cases()
    ]


@allure.title("Unknown route returns HTTP 404 — {param_id}")
@pytest.mark.parametrize(
    "operation_case",
    build_contract_params(xfail_auth_waf=True),
)
def test_404_for_unknown_route(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)

    # This check probes for an unknown route by appending a segment. Where the
    # endpoint routes a path variable beneath it, the appended segment is a
    # *valid route carrying a malformed id* — 400 is the correct answer, and the
    # mutation cannot tell that apart from a genuinely unknown route. Asserting
    # 404 there manufactures a failure that is neither an API defect nor a tier
    # defect, and it would recur across most Attendance write endpoints.
    if _resolver().declares_path_variables(operation_case.method, operation_case.path):
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "endpoint accepts path variables; unknown-route mutation is ambiguous",
            field="path_variables",
        )

    unknown_route_row = {
        **api_row,
        "Endpoint / Path": f"{operation_case.path.rstrip('/')}/nonexistent-xyz",
    }
    response = perform_api_request(
        unknown_route_row,
        global_contract_context.config_for(operation_case),
    )

    # An API that authenticates ahead of routing answers 401/403 for every path,
    # real or invented, so the probe never reaches the routing layer this check
    # is about. Verified against UAT: a route sharing no prefix with anything
    # real returns 401, not 404. Demanding 404 here would ask the API to
    # disclose which routes exist to an unauthenticated caller -- the opposite
    # of what the check is for.
    if response.status_code in (401, 403):
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} authenticates before "
            f"routing (unknown route returned {response.status_code}); "
            "unknown-route behaviour is not observable without a valid token",
        )

    assert response.status_code == 404, (
        f"{operation_case.method} {unknown_route_row['Endpoint / Path']} returned "
        f"{response.status_code} instead of 404"
    )


@allure.title("Response honors documented content negotiation — {param_id}")
@pytest.mark.parametrize(
    "operation_case",
    build_contract_params(xfail_auth_waf=True),
)
def test_content_type_negotiation(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    response = global_contract_context.bootstrap_responses.get(
        (operation_case.method, operation_case.path)
    )
    if response is None:
        response = perform_api_request(
            api_row,
            global_contract_context.config_for(operation_case),
        )

    xml_response = perform_api_request(
        _api_row_with_additional_headers(
            api_row,
            {"Accept": "application/xml"},
        ),
        global_contract_context.config_for(operation_case),
    )

    expected_content_types = operation_case.documented_content_types.get(
        response.status_code,
        frozenset(),
    )
    if not expected_content_types:
        # No source declares a content type for the status this API actually
        # returned. That is missing metadata, and test_status_code_matches_spec
        # already fails an undocumented status — reporting it here too would
        # count one defect twice.
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"no content type declared for {operation_case.method} "
            f"{operation_case.path} HTTP {response.status_code}",
            field="documented_content_types",
        )

    actual_content_type = _response_media_type(response)
    xml_content_type = _response_media_type(xml_response)
    errors: list[str] = []

    if actual_content_type not in expected_content_types:
        errors.append(
            f"normal request returned status {response.status_code} with "
            f"Content-Type {actual_content_type or '<missing>'}; documented types are "
            f"{sorted(expected_content_types)}"
        )
    if xml_response.status_code != 406 and xml_content_type != "application/json":
        errors.append(
            f"Accept: application/xml returned status {xml_response.status_code} with "
            f"Content-Type {xml_content_type or '<missing>'}; expected 406 or ignored "
            "negotiation with application/json"
        )

    assert not errors, f"{operation_case.method} {operation_case.path}: {'; '.join(errors)}"


@allure.title("CORS preflight permits the documented method — {param_id}")
@pytest.mark.skipif(
    not _cors_preflight_enabled(),
    reason=format_reason(
        ResultState.NOT_APPLICABLE,
        f"CORS preflight is opt-in; set {CORS_PREFLIGHT_FLAG}=1 to enable it. "
        "These are internal server-to-server APIs behind a WAF and are not "
        "expected to emit Access-Control-* headers",
    ),
)
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_cors_preflight(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    preflight_row = {
        **api_row,
        "HTTP Method": "OPTIONS",
        "Request Body": "",
        "Request Parameters": (
            "headers: Origin=https://global-contract.example; "
            f"Access-Control-Request-Method={operation_case.method}; "
            "Access-Control-Request-Headers=authorization,content-type"
        ),
        "Dependent APIs / Services": "",
    }
    response = perform_api_request(
        preflight_row,
        global_contract_context.config_for(operation_case),
    )

    allow_origin = response.headers.get("access-control-allow-origin")
    allow_methods = response.headers.get("access-control-allow-methods")
    allowed_methods = {
        method.strip().upper()
        for method in (allow_methods or "").split(",")
        if method.strip()
    }

    assert allow_origin and allow_methods and operation_case.method in allowed_methods, (
        f"OPTIONS {operation_case.path} returned {response.status_code}; "
        f"Access-Control-Allow-Origin={allow_origin!r}, "
        f"Access-Control-Allow-Methods={allow_methods!r}"
    )


@allure.title("Unicode input is handled without a server error — {param_id}")
@pytest.mark.parametrize("operation_case", build_special_character_params())
def test_special_characters_in_input(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    special_body = _special_character_body(operation_case)
    if special_body is None:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} has no request body "
            "to substitute Unicode into",
            field="request_body_sample",
        )

    response = perform_api_request(
        {**api_row, "Request Body": special_body},
        global_contract_context.config_for(operation_case),
    )

    print(
        f"Unicode input observation {operation_case.method} {operation_case.path}: "
        f"status={response.status_code}"
    )

    # Asserting `== 400` is right for auth and wrong everywhere else: an API
    # that legitimately accepts Unicode in its fields would fail on a contract
    # nobody wrote. What every API owes is to not fall over — a 5xx means the
    # input reached something that could not cope with it.
    assert response.status_code < 500, (
        f"{operation_case.method} {operation_case.path} returned "
        f"{response.status_code} for Unicode input; a server error means the "
        "input was not handled"
    )


# ===========================================================================
# Additional cross-cutting checks.
#
# Every one is gated on metadata this repo actually holds — the declared
# method, the inventory's Access column, its Request Parameters, its Request
# Body Schema, or the resolved host. Nothing here assumes a field the
# inventory does not carry: where the data is absent the check reports
# NOT_APPLICABLE naming the field, the same as the original twelve.
#
# None of these sends a method the endpoint did not declare. TRACE is the one
# exception and is safe by construction: it echoes, it mutates nothing, and
# the check exists precisely because it should be refused.
# ===========================================================================

#: Header values that disclose a product version, e.g. "nginx/1.24.0".
_VERSION_IN_HEADER = re.compile(r"\d+\.\d+")

#: Markers of an internal failure leaking into a response body.
_INTERNAL_LEAK_MARKERS = (
    "traceback (most recent call last)",
    "at java.",
    "at org.springframework",
    "org.hibernate",
    "javax.servlet",
    "system.nullreferenceexception",
    ".java:",
    ".py\", line ",
    "stack trace",
    "sqlexception",
    "syntax error at or near",
)


def _headers_with(api_row: dict[str, Any], extra: str) -> dict[str, Any]:
    """Return the row with ``extra`` merged into its Request Parameters headers.

    ``Request Parameters`` is a pipe-delimited string the request helper parses
    (``headers: k=v; k2=v2 | query: ...``). Appending another ``headers:``
    section is how a check overrides one without reaching into the helper,
    which is generated and must not be edited.
    """
    existing = api_row.get("Request Parameters", "") or ""
    joined = f"{existing} | headers: {extra}" if existing else f"headers: {extra}"
    return {**api_row, "Request Parameters": joined}


def _bootstrap_or_request(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
    api_row: dict[str, Any],
) -> httpx.Response:
    """Reuse the bootstrap response for this operation, or issue one."""
    response = global_contract_context.bootstrap_responses.get(
        (operation_case.method, operation_case.path)
    )
    if response is None:
        response = perform_api_request(
            api_row, global_contract_context.config_for(operation_case)
        )
    return response


@allure.title("Transport is HTTPS — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_transport_is_https(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """The resolved host must be TLS. Metadata only — issues no request."""
    api_row = _require_runnable(operation_case, global_contract_context)

    resolved = _resolve_templates(
        api_row.get("Base URL", ""), global_contract_context.config_for(operation_case)
    ).strip()
    if not resolved or "{{" in resolved:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "base URL did not resolve, so its scheme cannot be checked",
            field="Base URL",
        )

    scheme = urlsplit(resolved).scheme.lower()
    assert scheme == "https", (
        f"{operation_case.method} {operation_case.path} resolves to {scheme}://; "
        "credentials and tokens must never cross a plaintext transport"
    )


@allure.title("Private endpoint refuses an anonymous caller — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_private_endpoint_rejects_anonymous_access(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """A private endpoint called with no Authorization header must refuse.

    Distinct from ``test_401_without_valid_token``, which sends a *malformed*
    token. This sends none at all, which is the shape an unauthenticated
    caller actually takes.
    """
    api_row = _require_runnable(operation_case, global_contract_context)

    access = str(api_row.get("Access", "")).strip().lower()
    if access != "private":
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"endpoint is declared '{access or 'undeclared'}', not private",
            field="Access",
        )

    anonymous = {**api_row, "Request Parameters": "", "Auth Type": ""}
    response = perform_api_request(
        anonymous, {"__suppress_auth__": "1", **global_contract_context.config_for(operation_case)}
    )

    assert response.status_code in (401, 403), (
        f"{operation_case.method} {operation_case.path} is declared private but "
        f"returned {response.status_code} to a caller sending no credential; "
        "expected 401 or 403"
    )


@allure.title("Error responses are machine readable — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_error_response_is_machine_readable(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """A 4xx must answer in JSON, not an HTML error page.

    Uses the same unknown-route mutation as the 404 check, and inherits its
    guard: where the endpoint routes a path variable the mutation is ambiguous.
    """
    api_row = _require_runnable(operation_case, global_contract_context)

    if _resolver().declares_path_variables(operation_case.method, operation_case.path):
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "endpoint accepts path variables; unknown-route mutation is ambiguous",
            field="path_variables",
        )

    response = perform_api_request(
        {**api_row, "Endpoint / Path": f"{operation_case.path.rstrip('/')}/nonexistent-xyz"},
        global_contract_context.config_for(operation_case),
    )

    if response.status_code < 400:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"unknown route returned {response.status_code}; no error body to inspect",
            field="error_response",
        )

    content_type = response.headers.get("content-type", "").lower()
    assert "json" in content_type, (
        f"{operation_case.method} {operation_case.path} answered its "
        f"{response.status_code} with content-type '{content_type or 'none'}'; "
        "an API client cannot parse an HTML error page"
    )


@allure.title("Error responses hide internal detail — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_error_response_hides_internals(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """An error body must not carry a stack trace, class path or SQL fragment."""
    api_row = _require_runnable(operation_case, global_contract_context)

    if _resolver().declares_path_variables(operation_case.method, operation_case.path):
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "endpoint accepts path variables; unknown-route mutation is ambiguous",
            field="path_variables",
        )

    response = perform_api_request(
        {**api_row, "Endpoint / Path": f"{operation_case.path.rstrip('/')}/nonexistent-xyz"},
        global_contract_context.config_for(operation_case),
    )

    if response.status_code < 400:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"unknown route returned {response.status_code}; no error body to inspect",
            field="error_response",
        )

    body = (response.text or "").lower()
    leaked = [marker for marker in _INTERNAL_LEAK_MARKERS if marker in body]
    assert not leaked, (
        f"{operation_case.method} {operation_case.path} leaked internal detail in "
        f"its {response.status_code} body: {leaked}"
    )


@allure.title("Write endpoints refuse an unsupported media type — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_unsupported_media_type_rejected(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """A JSON endpoint sent text/plain must refuse it rather than parse it.

    Gated on a documented request body: an endpoint the inventory records no
    body for has no media type to get wrong.
    """
    api_row = _require_runnable(operation_case, global_contract_context)

    if operation_case.method not in {"POST", "PUT", "PATCH"}:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} carries no request body",
            field="HTTP Method",
        )
    if not str(api_row.get("Request Body", "")).strip():
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "inventory records no request body for this endpoint",
            field="Request Body",
        )

    response = perform_api_request(
        _headers_with(api_row, "Content-Type=text/plain"),
        global_contract_context.config_for(operation_case),
    )

    assert response.status_code >= 400, (
        f"{operation_case.method} {operation_case.path} accepted a text/plain body "
        f"with {response.status_code}; a JSON endpoint should answer 415"
    )


@allure.title("Declared idempotency matches the method — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_declared_idempotency_matches_method(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """PUT and DELETE are idempotent by RFC 9110; GET and HEAD are safe.

    Metadata only. Verifying idempotency by repeating a write would mutate a
    real environment twice, so this checks the *declaration* instead — a PUT
    documented as non-idempotent is a contract error worth surfacing.
    """
    _require_runnable(operation_case, global_contract_context)

    if operation_case.idempotent is None:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "idempotency is not declared for this operation",
            field="idempotent",
        )

    # An inventory-sourced value was inferred from REPLAY_SAFE_METHODS, which
    # answers "is this safe to replay against UAT", not "is this idempotent per
    # RFC 9110". PUT and DELETE are deliberately False there. Asserting RFC
    # semantics on it would fail every write method for agreeing with a rule it
    # was never expressing -- and there is no human declaration to contradict.
    if operation_case.idempotent_source not in {"openapi", "definition"}:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "idempotency was inferred from the method, not declared by a source",
            field="idempotent",
        )

    expected = operation_case.method in {"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}
    assert operation_case.idempotent == expected, (
        f"{operation_case.method} {operation_case.path} declares "
        f"idempotent={operation_case.idempotent}; RFC 9110 makes "
        f"{operation_case.method} {'idempotent' if expected else 'non-idempotent'}"
    )


@allure.title("Paginated list declares its page metadata — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_paginated_list_declares_page_metadata(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """A list documented as paginated must return page metadata with the page."""
    api_row = _require_runnable(operation_case, global_contract_context)

    if not operation_case.paginated:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "operation is not declared paginated",
            field="paginated",
        )

    response = _bootstrap_or_request(operation_case, global_contract_context, api_row)
    if response.status_code >= 400:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"list returned {response.status_code}; no page to inspect",
            field="response",
        )

    try:
        payload = response.json()
    except ValueError:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "response is not JSON; page metadata cannot be located",
            field="response",
        )

    candidates = {"page", "pagenumber", "pagesize", "total", "totalelements",
                  "totalpages", "count", "offset", "limit", "hasnext", "next"}
    seen: set[str] = set()
    if isinstance(payload, dict):
        seen = {str(key).lower().replace("_", "") for key in payload}
        for wrapper in ("data", "result", "payload", "meta", "pageable"):
            inner = payload.get(wrapper)
            if isinstance(inner, dict):
                seen |= {str(key).lower().replace("_", "") for key in inner}

    assert seen & candidates, (
        f"{operation_case.method} {operation_case.path} is documented as paginated "
        f"but its response carries no page metadata; saw keys {sorted(seen) or 'none'}"
    )


@allure.title("Host sets the baseline security response headers")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_security_headers_present(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """X-Content-Type-Options, and a framing policy.

    Host-level: these are set by the gateway, not by an endpoint, so this is
    measured once per host and referenced from the other APIs on it.
    """
    api_row = _require_runnable(operation_case, global_contract_context)
    response = _bootstrap_or_request(operation_case, global_contract_context, api_row)

    headers = {key.lower(): value for key, value in response.headers.items()}
    missing = []
    if headers.get("x-content-type-options", "").strip().lower() != "nosniff":
        missing.append("X-Content-Type-Options: nosniff")
    framing = headers.get("x-frame-options", "") or headers.get("content-security-policy", "")
    if "frame" not in framing.lower() and "deny" not in framing.lower() \
            and "sameorigin" not in framing.lower():
        missing.append("X-Frame-Options or a CSP frame-ancestors directive")

    assert not missing, (
        f"{urlsplit(str(response.url)).netloc} does not set: {'; '.join(missing)}"
    )


@allure.title("Host discloses no product version in its headers")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_no_server_version_disclosure(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """Server and X-Powered-By must not carry a version number.

    Host-level. A banner naming the exact build hands an attacker the CVE list
    for free; the header may stay, the version must not.
    """
    api_row = _require_runnable(operation_case, global_contract_context)
    response = _bootstrap_or_request(operation_case, global_contract_context, api_row)

    disclosed = {
        name: value
        for name, value in response.headers.items()
        if name.lower() in {"server", "x-powered-by", "x-aspnet-version"}
        and _VERSION_IN_HEADER.search(value or "")
    }

    assert not disclosed, (
        f"{urlsplit(str(response.url)).netloc} discloses a product version: {disclosed}"
    )


@allure.title("Host refuses the TRACE method")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_trace_method_is_disabled(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """TRACE echoes the request back and must be off.

    Host-level, and the one check here that sends a method the endpoint did
    not declare. It is safe by construction: TRACE mutates nothing, and the
    check exists precisely because it should be refused.
    """
    api_row = _require_runnable(operation_case, global_contract_context)

    response = perform_api_request(
        {**api_row, "HTTP Method": "TRACE", "Request Body": ""},
        global_contract_context.config_for(operation_case),
    )

    assert response.status_code >= 400, (
        f"{urlsplit(str(response.url)).netloc} answered TRACE with "
        f"{response.status_code}; TRACE echoes the request and must be disabled"
    )

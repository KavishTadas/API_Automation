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

from tests.auto_generated._api_test_helpers import (
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
from tests.global_contract.result_states import ResultState, format_reason
from tests.global_contract.run_manifest import (
    ManifestValidationError,
    load_manifest_from_env,
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

    @property
    def label(self) -> str:
        return self.entry_id or f"{self.method} {self.path}"


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


def _record_state(state: ResultState, detail: str) -> str:
    """Record a non-PASS/FAIL outcome so downstream tooling can read it back.

    Returns the formatted reason so callers can hand it straight to
    ``pytest.skip``.
    """
    reason = format_reason(state, detail)
    print(reason)
    allure.attach(
        reason,
        name=f"Result state: {state.name}",
        attachment_type=allure.attachment_type.TEXT,
    )
    return reason


def _skip_with_state(state: ResultState, detail: str) -> None:
    """End the current test in ``state``, carrying a machine-readable reason."""
    pytest.skip(_record_state(state, detail))


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
        )

    if global_contract_context is not None:
        result = global_contract_context.auth_result_for(operation_case)
        if result is not None and not result.succeeded:
            _skip_with_state(
                ResultState.SKIPPED_NO_TOKEN,
                f"{operation_case.label} (BLOCKED: {result.provider_id} failed) — "
                f"{result.reason}",
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
        return load_manifest_from_env()
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
    representatives: dict[str, str] = {}
    for case in _build_operation_cases():
        if case.host and case.host not in representatives:
            representatives[case.host] = case.label
    return representatives


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


def _timed_request(
    api_row: dict[str, Any],
    runtime_config: dict[str, str],
) -> tuple[httpx.Response, float]:
    """Perform a request and return it alongside its wall-clock duration in ms."""
    started_at = time.perf_counter()
    response = perform_api_request(api_row, runtime_config)
    return response, (time.perf_counter() - started_at) * 1000


@pytest.fixture(scope="session")
def global_contract_context() -> GlobalContractContext:
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
                    runtime_config.update(
                        {
                            "AUTH_TOKEN": token,
                            "API_AUTH_TOKEN": token,
                            "authToken": token,
                        }
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
        except Exception as error:
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
                except Exception:
                    continue

            # An uploaded definition brings its own error triggers, paired
            # Nth-to-Nth from its `Error Request Body` / `Error Response` rows.
            definition = resolver.definition(operation_case.method, operation_case.path)
            if definition is not None and operation_case.api_row is not None:
                for trigger_row in error_trigger_rows(definition, operation_case.api_row):
                    try:
                        samples.append(perform_api_request(trigger_row, case_config))
                    except Exception:
                        continue

        response_samples[operation_key] = tuple(samples)

    return GlobalContractContext(
        sources=sources,
        runtime_config=runtime_config,
        bootstrap_responses=bootstrap_responses,
        response_samples=response_samples,
        bootstrap_durations_ms=bootstrap_durations_ms,
        auth_results=auth_results,
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
        _skip_with_state(ResultState.NOT_APPLICABLE, "expected status not declared")
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

    # The success half is required: without it this test asserted nothing.
    assert any(200 <= status < 300 for status in observed_statuses), (
        f"{operation_case.method} {operation_case.path} schema check did not inspect "
        f"a success response; observed statuses: {observed_statuses}"
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
        _skip_with_state(ResultState.NOT_APPLICABLE, "no SLA target resolved")

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
    unknown_route_row = {
        **api_row,
        "Endpoint / Path": f"{operation_case.path.rstrip('/')}/nonexistent-xyz",
    }
    response = perform_api_request(
        unknown_route_row,
        global_contract_context.config_for(operation_case),
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

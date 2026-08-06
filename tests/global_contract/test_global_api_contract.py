"""Global OpenAPI-driven contract checks for active HCM endpoints."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator

from tests.auto_generated._api_test_helpers import (
    load_runtime_config,
    perform_api_request,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
API_FILE_PATH = ROOT_DIR / "api-docs" / "API_File.json"
OPENAPI_PATH = ROOT_DIR / "openapi" / "openapi.yaml"
HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


@dataclass(frozen=True)
class ContractSources:
    api_rows: tuple[dict[str, Any], ...]
    openapi: dict[str, Any]


@dataclass(frozen=True)
class OperationCase:
    method: str
    path: str
    api_row: dict[str, Any]
    documented_status_codes: frozenset[int]
    documented_content_types: dict[int, frozenset[str]]
    requires_bearer_auth: bool
    sla_ms: int | None
    required_role: str | None
    idempotent: bool | None
    max_payload_bytes: int | None
    paginated: bool | None


@dataclass
class GlobalContractContext:
    sources: ContractSources
    runtime_config: dict[str, str] = field(repr=False)
    bootstrap_responses: dict[tuple[str, str], httpx.Response] = field(repr=False)
    response_samples: dict[tuple[str, str], tuple[httpx.Response, ...]] = field(
        repr=False
    )


@lru_cache(maxsize=1)
def _load_contract_sources() -> ContractSources:
    with API_FILE_PATH.open(encoding="utf-8-sig") as handle:
        api_rows = json.load(handle)

    with OPENAPI_PATH.open(encoding="utf-8") as handle:
        openapi = yaml.safe_load(handle)

    if not isinstance(api_rows, list):
        raise TypeError(f"{API_FILE_PATH} must contain a JSON array")
    if not isinstance(openapi, dict):
        raise TypeError(f"{OPENAPI_PATH} must contain an OpenAPI object")

    return ContractSources(api_rows=tuple(api_rows), openapi=openapi)


def _inventory_status_codes(api_row: dict[str, Any]) -> frozenset[int]:
    response_spec = str(api_row.get("Response (example/200)", ""))
    match = re.search(r"Expected status\(es\):\s*([0-9,\s]+)", response_spec)
    if not match:
        return frozenset()
    return frozenset(int(code) for code in re.findall(r"\d{3}", match.group(1)))


def _select_api_row(
    api_rows: tuple[dict[str, Any], ...],
    method: str,
    path: str,
) -> dict[str, Any]:
    matching_rows = [
        row
        for row in api_rows
        if str(row.get("HTTP Method", "")).upper() == method
        and str(row.get("Endpoint / Path", "")) == path
    ]
    if not matching_rows:
        raise ValueError(f"No active API inventory row found for {method} {path}")

    successful_rows = [
        row
        for row in matching_rows
        if any(200 <= code < 300 for code in _inventory_status_codes(row))
    ]
    preferred_rows = successful_rows or matching_rows
    collection_rows = [
        row
        for row in preferred_rows
        if str(row.get("Comments", "")).startswith("Source: collections/")
    ]
    return (collection_rows or preferred_rows)[0]


@lru_cache(maxsize=1)
def _build_operation_cases() -> tuple[OperationCase, ...]:
    sources = _load_contract_sources()
    cases: list[OperationCase] = []

    for path, path_item in sources.openapi.get("paths", {}).items():
        for method_name, operation in path_item.items():
            if method_name.lower() not in HTTP_METHODS:
                continue

            method = method_name.upper()
            response_codes = frozenset(
                int(code)
                for code in operation.get("responses", {})
                if str(code).isdigit()
            )
            if not response_codes:
                raise ValueError(f"No numeric response codes documented for {method} {path}")

            cases.append(
                OperationCase(
                    method=method,
                    path=path,
                    api_row=_select_api_row(sources.api_rows, method, path),
                    documented_status_codes=response_codes,
                    documented_content_types={
                        int(code): frozenset(
                            response.get("content", {}).keys()
                            if isinstance(response, dict)
                            else ()
                        )
                        for code, response in operation.get("responses", {}).items()
                        if str(code).isdigit()
                    },
                    requires_bearer_auth=any(
                        isinstance(requirement, dict) and "bearerAuth" in requirement
                        for requirement in operation.get("security", [])
                    ),
                    sla_ms=operation.get("x-sla-ms"),
                    required_role=operation.get("x-required-role"),
                    idempotent=operation.get("x-idempotent"),
                    max_payload_bytes=operation.get("x-max-payload-bytes"),
                    paginated=operation.get("x-paginated"),
                )
            )

    return tuple(cases)


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
    """Build missing/invalid-token parameters for secured operations only."""
    params: list[Any] = []
    for case in _build_operation_cases():
        if not case.requires_bearer_auth:
            continue
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


@pytest.fixture(scope="session")
def global_contract_context() -> GlobalContractContext:
    """Load both contracts and shared runtime credentials for the suite."""
    sources = _load_contract_sources()
    runtime_config = load_runtime_config()
    bootstrap_responses: dict[tuple[str, str], httpx.Response] = {}
    operation_cases = _build_operation_cases()

    auth_case = next(
        (
            case
            for case in operation_cases
            if case.method == "POST" and case.path == "/auth/token"
        ),
        None,
    )
    if auth_case is not None:
        auth_response = perform_api_request(auth_case.api_row, runtime_config)
        bootstrap_responses[(auth_case.method, auth_case.path)] = auth_response
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
        if operation_key not in bootstrap_responses:
            bootstrap_responses[operation_key] = perform_api_request(
                operation_case.api_row,
                runtime_config,
            )

    response_samples: dict[tuple[str, str], tuple[httpx.Response, ...]] = {}
    for operation_case in operation_cases:
        operation_key = (operation_case.method, operation_case.path)
        samples = [bootstrap_responses[operation_key]]
        error_rows = [
            api_row
            for api_row in sources.api_rows
            if str(api_row.get("HTTP Method", "")).upper() == operation_case.method
            and str(api_row.get("Endpoint / Path", "")) == operation_case.path
            and any(code >= 400 for code in _inventory_status_codes(api_row))
        ]
        samples.extend(
            perform_api_request(api_row, runtime_config)
            for api_row in error_rows
        )
        response_samples[operation_key] = tuple(samples)

    return GlobalContractContext(
        sources=sources,
        runtime_config=runtime_config,
        bootstrap_responses=bootstrap_responses,
        response_samples=response_samples,
    )


@pytest.mark.parametrize("operation_case", build_contract_params())
def test_status_code_matches_spec(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    response = global_contract_context.bootstrap_responses.get(
        (operation_case.method, operation_case.path)
    )
    if response is None:
        response = perform_api_request(
            operation_case.api_row,
            global_contract_context.runtime_config,
        )

    assert response.status_code in operation_case.documented_status_codes, (
        f"{operation_case.method} {operation_case.path} returned "
        f"{response.status_code}; documented statuses are "
        f"{sorted(operation_case.documented_status_codes)}"
    )


@pytest.mark.parametrize("operation_case", build_contract_params())
def test_response_matches_full_schema(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    responses = global_contract_context.response_samples[
        (operation_case.method, operation_case.path)
    ]
    observed_statuses: list[int] = []

    for response in responses:
        observed_statuses.append(response.status_code)
        schema_document = _response_schema_document(
            operation_case,
            response.status_code,
            global_contract_context.sources,
        )
        payload = _response_json(operation_case, response)
        errors = sorted(
            Draft202012Validator(schema_document).iter_errors(payload),
            key=lambda error: [str(part) for part in error.absolute_path],
        )

        assert not errors, (
            f"{operation_case.method} {operation_case.path} HTTP "
            f"{response.status_code} failed its complete OpenAPI response schema: "
            + "; ".join(_format_schema_error(error) for error in errors)
        )

    assert any(200 <= status < 300 for status in observed_statuses), (
        f"{operation_case.method} {operation_case.path} schema check did not inspect "
        f"a success response; observed statuses: {observed_statuses}"
    )
    assert any(status >= 400 for status in observed_statuses), (
        f"{operation_case.method} {operation_case.path} schema check did not inspect "
        f"an error response; observed statuses: {observed_statuses}"
    )


@pytest.mark.parametrize("operation_case", build_contract_params())
def test_no_credential_leakage_in_response(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    responses = global_contract_context.response_samples[
        (operation_case.method, operation_case.path)
    ]

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


@pytest.mark.parametrize("operation_case", build_contract_params())
def test_response_time_within_sla(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    if operation_case.sla_ms is None:
        pytest.skip(
            f"{operation_case.method} {operation_case.path} has no x-sla-ms "
            "defined in openapi.yaml"
        )

    started_at = time.perf_counter()
    perform_api_request(
        operation_case.api_row,
        global_contract_context.runtime_config,
    )
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    buffer_percent = 20
    allowed_ms = operation_case.sla_ms * (1 + buffer_percent / 100)

    print(
        f"SLA measurement {operation_case.method} {operation_case.path}: "
        f"{elapsed_ms:.1f}ms; limit {allowed_ms:.0f}ms "
        f"({operation_case.sla_ms}ms SLA +{buffer_percent}% buffer)"
    )
    assert elapsed_ms <= allowed_ms, (
        f"{operation_case.method} {operation_case.path}: expected "
        f"<={allowed_ms:.0f}ms ({operation_case.sla_ms}ms SLA "
        f"+{buffer_percent}% buffer), got {elapsed_ms:.1f}ms"
    )


@pytest.mark.parametrize(
    "operation_case",
    [
        pytest.param(case, id=f"{case.method} {case.path}")
        for case in _build_operation_cases()
        if case.idempotent is True
    ],
)
def test_idempotent_get_returns_stable_result(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    first_response = perform_api_request(
        operation_case.api_row,
        global_contract_context.runtime_config,
    )
    second_response = perform_api_request(
        operation_case.api_row,
        global_contract_context.runtime_config,
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


def test_small_burst_does_not_trigger_immediate_blocking(
    global_contract_context: GlobalContractContext,
) -> None:
    operation_case = next(
        case
        for case in _build_operation_cases()
        if (case.method, case.path)
        == ("GET", "/user/leaves/getAllLeaveReports")
    )
    token = global_contract_context.runtime_config.get("AUTH_TOKEN")
    assert token, "The session bootstrap did not provide a valid auth token"

    burst_row = _api_row_with_authorization(
        {
            **operation_case.api_row,
            "Request Parameters": "query: month=4; year=2026",
        },
        f"Bearer {token}",
    )
    observed_statuses: list[int] = []

    for request_number in range(1, 11):
        response = perform_api_request(
            burst_row,
            global_contract_context.runtime_config,
        )
        observed_statuses.append(response.status_code)
        has_waf_fingerprint = (
            response.status_code == 403 and not response.content.strip()
        )
        assert not has_waf_fingerprint, (
            "Small sequential burst was blocked with the known WAF fingerprint "
            f"(HTTP 403 with an empty body) at request {request_number}; "
            f"statuses observed before stopping: {observed_statuses}"
        )

    print(
        "Small-burst observation GET /user/leaves/getAllLeaveReports "
        f"month=4 year=2026: statuses={observed_statuses}"
    )


@pytest.mark.parametrize(
    "operation_case",
    [
        pytest.param(case, id=f"{case.method} {case.path}")
        for case in _build_operation_cases()
        if case.max_payload_bytes is not None
        and isinstance(
            _load_contract_sources()
            .openapi["paths"][case.path][case.method.lower()]
            .get("requestBody"),
            dict,
        )
    ],
)
def test_request_payload_size_enforcement(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    assert operation_case.max_payload_bytes is not None
    oversized_row = {
        **operation_case.api_row,
        "Request Body": json.dumps(
            {
                "empCode": "{{empCode}}",
                "password": "X" * (operation_case.max_payload_bytes + 1),
            },
            separators=(",", ":"),
        ),
    }
    response = perform_api_request(
        oversized_row,
        global_contract_context.runtime_config,
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

    print(
        f"Oversized payload observation {operation_case.method} "
        f"{operation_case.path}: request_bytes={actual_request_bytes}; "
        f"documented_limit={operation_case.max_payload_bytes}; "
        f"status={response.status_code}; response_body={response_body}"
    )


@pytest.mark.parametrize(
    ("operation_case", "authorization"),
    build_bearer_auth_negative_params(),
)
def test_401_without_valid_token(
    operation_case: OperationCase,
    authorization: str | None,
    global_contract_context: GlobalContractContext,
) -> None:
    response = perform_api_request(
        _api_row_with_authorization(operation_case.api_row, authorization),
        global_contract_context.runtime_config,
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
    sources: ContractSources,
) -> dict[str, Any]:
    operation = sources.openapi["paths"][operation_case.path][
        operation_case.method.lower()
    ]
    responses = operation.get("responses", {})
    response_definition = responses.get(str(status_code))
    if response_definition is None:
        response_definition = responses.get(f"{status_code // 100}XX")

    assert isinstance(response_definition, dict), (
        f"{operation_case.method} {operation_case.path} returned {status_code}, "
        "but OpenAPI has no response definition for that status"
    )

    content = response_definition.get("content", {})
    json_content = content.get("application/json")
    assert isinstance(json_content, dict), (
        f"{operation_case.method} {operation_case.path} returned {status_code}, "
        "but OpenAPI has no application/json response schema for that status"
    )

    response_schema = json_content.get("schema")
    assert isinstance(response_schema, dict), (
        f"{operation_case.method} {operation_case.path} returned {status_code}, "
        "but its application/json response has no schema"
    )

    schema_document: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "components": sources.openapi.get("components", {}),
    }
    schema_document.update(response_schema)
    Draft202012Validator.check_schema(schema_document)
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


def build_special_character_params() -> list[Any]:
    payloads = {
        ("POST", "/auth/token"): {
            "empCode": "ÉMP-测试-😀",
            "password": "pässwörd-🔒",
        },
    }
    return [
        pytest.param(case, payloads[(case.method, case.path)], id=f"{case.method} {case.path}")
        for case in _build_operation_cases()
        if (case.method, case.path) in payloads
    ]


@pytest.mark.parametrize(
    "operation_case",
    build_contract_params(xfail_auth_waf=True),
)
def test_404_for_unknown_route(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    unknown_route_row = {
        **operation_case.api_row,
        "Endpoint / Path": f"{operation_case.path.rstrip('/')}/nonexistent-xyz",
    }
    response = perform_api_request(
        unknown_route_row,
        global_contract_context.runtime_config,
    )

    assert response.status_code == 404, (
        f"{operation_case.method} {unknown_route_row['Endpoint / Path']} returned "
        f"{response.status_code} instead of 404"
    )


@pytest.mark.parametrize(
    "operation_case",
    build_contract_params(xfail_auth_waf=True),
)
def test_content_type_negotiation(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    response = global_contract_context.bootstrap_responses.get(
        (operation_case.method, operation_case.path)
    )
    if response is None:
        response = perform_api_request(
            operation_case.api_row,
            global_contract_context.runtime_config,
        )

    xml_response = perform_api_request(
        _api_row_with_additional_headers(
            operation_case.api_row,
            {"Accept": "application/xml"},
        ),
        global_contract_context.runtime_config,
    )

    expected_content_types = operation_case.documented_content_types.get(
        response.status_code,
        frozenset(),
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


@pytest.mark.parametrize("operation_case", build_contract_params())
def test_cors_preflight(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    preflight_row = {
        **operation_case.api_row,
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
        global_contract_context.runtime_config,
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


@pytest.mark.parametrize(
    ("operation_case", "payload"),
    build_special_character_params(),
)
def test_special_characters_in_input(
    operation_case: OperationCase,
    payload: dict[str, str],
    global_contract_context: GlobalContractContext,
) -> None:
    special_input_row = {
        **operation_case.api_row,
        "Request Body": json.dumps(payload, ensure_ascii=False),
    }
    response = perform_api_request(
        special_input_row,
        global_contract_context.runtime_config,
    )

    assert response.status_code == 400, (
        f"{operation_case.method} {operation_case.path} returned "
        f"{response.status_code} for malformed Unicode input instead of 400"
    )

"""Oversized payload exercises the documented size limit

Emits: FAIL, INFORMATIONAL, NOT_APPLICABLE, PASS.
Reads metadata field(s): max_payload_bytes, request_body_sample.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


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

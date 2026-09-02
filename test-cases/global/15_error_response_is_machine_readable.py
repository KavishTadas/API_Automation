"""Error responses are machine readable

A 4xx must answer in JSON, not an HTML error page.

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): error_response, path_variables.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


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

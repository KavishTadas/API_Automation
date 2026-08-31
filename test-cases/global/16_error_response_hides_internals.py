"""Error responses hide internal detail

An error body must not carry a stack trace, class path or SQL fragment.

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): error_response, path_variables.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


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

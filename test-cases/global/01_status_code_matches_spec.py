"""Response status matches the OpenAPI contract

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): documented_status_codes.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


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

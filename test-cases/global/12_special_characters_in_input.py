"""Unicode input is handled without a server error

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): request_body_sample.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


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

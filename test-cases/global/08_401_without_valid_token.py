"""Missing or invalid Bearer token returns HTTP 401

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): requires_bearer_auth.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


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

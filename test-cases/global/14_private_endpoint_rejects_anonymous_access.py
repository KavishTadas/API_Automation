"""Private endpoint refuses an anonymous caller

A private endpoint called with no Authorization header must refuse.

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


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

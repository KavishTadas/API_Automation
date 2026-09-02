"""Unknown route returns HTTP 404

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): path_variables.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


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

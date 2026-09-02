"""An unknown sort column is rejected without a server error or a type leak

Ported from the attendance repo's `TC-GLOB-06`, which is the highest-yield check
in that suite: it found two HTTP 500s, and both leaked a JPA entity name
(`AttendanceStatusThresholdMaster`, `LateEarlyPolicyMaster`) straight into the
response. Nothing in this tier looked for either.

Two failures are asserted separately because they are different defects. A 500
says the sort parameter reached the persistence layer unvalidated. A leaked type
name says the resulting stack trace was handed to the caller -- an information
disclosure that survives even if the 500 is later turned into a 400.

Emits: FAIL, NOT_APPLICABLE, NOT_ASSERTED, PASS.
Reads metadata field(s): paginated.
"""

from _support import *  # noqa: F401,F403

UNKNOWN_SORT_COLUMN = "notAColumn_zzz,asc"


@allure.title("Unknown sort column is rejected cleanly — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_invalid_sort_column_is_rejected_cleanly(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)

    if not _looks_like_collection(operation_case):
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} is not a collection "
            "endpoint, so a sort parameter has nothing to order",
            field="paginated",
        )

    response = perform_api_request(
        _with_query(api_row, f"sort={UNKNOWN_SORT_COLUMN}"),
        global_contract_context.config_for(operation_case),
    )
    _require_reached_the_handler(response, operation_case, "the sort parameter")
    body = response.text or ""

    print(
        f"Invalid sort observation {operation_case.method} {operation_case.path}: "
        f"status={response.status_code}"
    )

    assert response.status_code < 500, (
        f"{operation_case.method} {operation_case.path} returned "
        f"{response.status_code} for sort={UNKNOWN_SORT_COLUMN!r}; an unknown "
        "column is caller error and must not reach the persistence layer"
    )

    leaked = _leaked_internal_type(body)
    assert not leaked, (
        f"{operation_case.method} {operation_case.path} disclosed the internal "
        f"type {leaked!r} while rejecting an unknown sort column"
    )

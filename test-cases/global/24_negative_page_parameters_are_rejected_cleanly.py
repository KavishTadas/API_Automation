"""A negative page or size is rejected without a server error

Ported from the attendance repo's `TC-GLOB-07`. This tier had no pagination
probe at all -- `test_paginated_list_declares_page_metadata` only inspects a
*successful* page, so nothing exercised what happens when the parameters are
nonsense.

`page=-1&size=-10` is caller error. A 4xx is the right answer and a 200 with a
sane page is an acceptable one; a 5xx means the value was passed through to
something that could not cope, which is the same class of defect as the unknown
sort column next door.

Emits: FAIL, NOT_APPLICABLE, NOT_ASSERTED, PASS.
Reads metadata field(s): paginated.
"""

from _support import *  # noqa: F401,F403

NEGATIVE_PAGE = "page=-1&size=-10"


@allure.title("Negative page parameters are rejected cleanly — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_negative_page_parameters_are_rejected_cleanly(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)

    if not _looks_like_collection(operation_case):
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} is not a collection "
            "endpoint, so page parameters do not apply",
            field="paginated",
        )

    response = perform_api_request(
        _with_query(api_row, NEGATIVE_PAGE),
        global_contract_context.config_for(operation_case),
    )

    _require_reached_the_handler(response, operation_case, "the page parameters")

    print(
        f"Negative page observation {operation_case.method} {operation_case.path}: "
        f"status={response.status_code}"
    )

    assert response.status_code < 500, (
        f"{operation_case.method} {operation_case.path} returned "
        f"{response.status_code} for {NEGATIVE_PAGE}; a negative page index is "
        "caller error, not a server failure"
    )

    leaked = _leaked_internal_type(response.text or "")
    assert not leaked, (
        f"{operation_case.method} {operation_case.path} disclosed the internal "
        f"type {leaked!r} while handling a negative page index"
    )

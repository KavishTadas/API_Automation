"""A page far past the end returns an empty page, not an error

Ported from the attendance repo's `TC-GLOB-08`. Asking for page 999999 of a
short list is not caller error -- it is a legitimate request whose answer is
"nothing here". The contract is that the endpoint says so calmly.

Deliberately weaker than the sibling checks: a 4xx is accepted, because some
APIs reasonably treat an out-of-range page as a bad request. Only a 5xx, or a
leaked internal type, is a failure. Asserting `== 200` here would fail APIs
that are behaving defensibly.

Emits: FAIL, NOT_APPLICABLE, NOT_ASSERTED, PASS.
Reads metadata field(s): paginated.
"""

from _support import *  # noqa: F401,F403

OUT_OF_BOUNDS_PAGE = f"page={UNKNOWN_ENTITY_ID}&size=10"


@allure.title("Out-of-bounds page returns an empty page — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_out_of_bounds_page_returns_an_empty_page(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)

    if not _looks_like_collection(operation_case):
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} is not a collection "
            "endpoint, so there is no page to run off the end of",
            field="paginated",
        )

    response = perform_api_request(
        _with_query(api_row, OUT_OF_BOUNDS_PAGE),
        global_contract_context.config_for(operation_case),
    )

    _require_reached_the_handler(response, operation_case, "the page index")

    print(
        f"Out-of-bounds page observation {operation_case.method} "
        f"{operation_case.path}: status={response.status_code}"
    )

    assert response.status_code < 500, (
        f"{operation_case.method} {operation_case.path} returned "
        f"{response.status_code} for {OUT_OF_BOUNDS_PAGE}; a page past the end "
        "of the data is an empty result, not a server failure"
    )

    leaked = _leaked_internal_type(response.text or "")
    assert not leaked, (
        f"{operation_case.method} {operation_case.path} disclosed the internal "
        f"type {leaked!r} for an out-of-bounds page"
    )

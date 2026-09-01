"""Fetching an entity that does not exist returns 404, not 200 and not 500

Ported from the attendance repo's `TC-GLOB-13`, where all six masters answered
404 -- so this is a contract they already meet and a regression guard rather
than a bug hunt.

Distinct from `test_404_for_unknown_route`, which probes a route the API does
not publish. This probes a route it *does* publish, with an id behind which
nothing exists. Those fail differently: an unknown route is caught by the
router, an unknown id only by the handler, and only the second tells you the
lookup path checks for absence before it dereferences.

A 200 is the serious failure: it means the endpoint returned *something* for an
entity that does not exist.

Emits: FAIL, NOT_APPLICABLE, NOT_ASSERTED, PASS.
Reads metadata field(s): none.
"""

from _support import *  # noqa: F401,F403


@allure.title("Unknown entity id returns 404 — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_unknown_entity_id_returns_404(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)

    if operation_case.method.upper() != "GET":
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "read-only probe; the mutation form is covered by its own check",
        )

    current = _id_segment(operation_case.path)
    if not current:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.path} addresses no entity id to make unknown",
        )
    if current == UNKNOWN_ENTITY_ID:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"the operation already addresses id {UNKNOWN_ENTITY_ID}",
        )

    response = perform_api_request(
        _with_unknown_entity_id(api_row, operation_case.path),
        global_contract_context.config_for(operation_case),
    )

    _require_reached_the_handler(response, operation_case, "the entity lookup")

    print(
        f"Unknown id observation {operation_case.method} {operation_case.path} "
        f"(id {current} -> {UNKNOWN_ENTITY_ID}): status={response.status_code}"
    )

    assert response.status_code != 200, (
        f"{operation_case.method} {operation_case.path} returned 200 for entity "
        f"{UNKNOWN_ENTITY_ID}, which does not exist"
    )
    assert response.status_code < 500, (
        f"{operation_case.method} {operation_case.path} returned "
        f"{response.status_code} for a non-existent entity; absence is a 404, "
        "not a server failure"
    )

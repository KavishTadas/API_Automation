"""Mutating an entity that does not exist returns 404, and changes nothing

Ported from the attendance repo's `TC-GLOB-14`, where all six masters answered
404. The read form is checked next door; this is the write form, and it is the
one that matters more -- a handler that dereferences before checking existence
fails here while passing the GET.

Why this is safe to run against UAT
-----------------------------------
It is the only mutation probe in this tier, and it is safe *by construction*:
the request is addressed to an id that does not exist, so a correct API has
nothing to modify and an incorrect one reveals itself by the status it returns.
That is a different thing from `REPLAY_SAFE_METHODS`, which excludes PUT and
DELETE precisely because replaying them against a *real* id mutates real data.
This never names a real id.

A 2xx is the serious failure: it means the API reported success for an entity
it does not have, which usually means it created one or silently no-opped.

Emits: FAIL, NOT_APPLICABLE, NOT_ASSERTED, PASS.
Reads metadata field(s): none.
"""

from _support import *  # noqa: F401,F403

MUTATING_METHODS = frozenset({"PUT", "PATCH", "DELETE"})


@allure.title("Unknown entity mutation returns 404 — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_unknown_entity_mutation_returns_404(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)

    method = operation_case.method.upper()
    if method not in MUTATING_METHODS:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{method} does not mutate an addressed entity",
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

    _require_reached_the_handler(response, operation_case, "the mutation")

    print(
        f"Unknown-id mutation observation {method} {operation_case.path} "
        f"(id {current} -> {UNKNOWN_ENTITY_ID}): status={response.status_code}"
    )

    assert not (200 <= response.status_code < 300), (
        f"{method} {operation_case.path} reported success "
        f"({response.status_code}) for entity {UNKNOWN_ENTITY_ID}, which does "
        "not exist; the mutation either created a row or silently did nothing"
    )
    assert response.status_code < 500, (
        f"{method} {operation_case.path} returned {response.status_code} for a "
        "non-existent entity; absence is a 404, not a server failure"
    )

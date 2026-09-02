"""Declared idempotency matches the method

PUT and DELETE are idempotent by RFC 9110; GET and HEAD are safe.

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): idempotent.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Declared idempotency matches the method — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_declared_idempotency_matches_method(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """PUT and DELETE are idempotent by RFC 9110; GET and HEAD are safe.

    Metadata only. Verifying idempotency by repeating a write would mutate a
    real environment twice, so this checks the *declaration* instead — a PUT
    documented as non-idempotent is a contract error worth surfacing.
    """
    _require_runnable(operation_case, global_contract_context)

    if operation_case.idempotent is None:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "idempotency is not declared for this operation",
            field="idempotent",
        )

    # An inventory-sourced value was inferred from REPLAY_SAFE_METHODS, which
    # answers "is this safe to replay against UAT", not "is this idempotent per
    # RFC 9110". PUT and DELETE are deliberately False there. Asserting RFC
    # semantics on it would fail every write method for agreeing with a rule it
    # was never expressing -- and there is no human declaration to contradict.
    if operation_case.idempotent_source not in {"openapi", "definition"}:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "idempotency was inferred from the method, not declared by a source",
            field="idempotent",
        )

    expected = operation_case.method in {"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}
    assert operation_case.idempotent == expected, (
        f"{operation_case.method} {operation_case.path} declares "
        f"idempotent={operation_case.idempotent}; RFC 9110 makes "
        f"{operation_case.method} {'idempotent' if expected else 'non-idempotent'}"
    )

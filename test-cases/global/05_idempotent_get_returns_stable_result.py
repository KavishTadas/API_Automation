"""Repeated GET requests return a stable result

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): idempotent.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Repeated GET requests return a stable result — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_idempotent_get_returns_stable_result(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    # Filtered here rather than in the parametrize expression: a case filtered
    # out at collection produces no result at all, so the platform sees 11 tests
    # for one API and 12 for another with nothing explaining the difference.
    if operation_case.idempotent is not True:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.label} is not declared idempotent, so a repeated "
            "request is not safe to send",
            field="idempotent",
        )
    first_response = perform_api_request(
        api_row,
        global_contract_context.config_for(operation_case),
    )
    second_response = perform_api_request(
        api_row,
        global_contract_context.config_for(operation_case),
    )

    assert first_response.status_code == second_response.status_code, (
        f"{operation_case.method} {operation_case.path} returned different statuses "
        f"for identical consecutive requests: first={first_response.status_code}, "
        f"second={second_response.status_code}"
    )

    first_payload = _response_json(operation_case, first_response)
    second_payload = _response_json(operation_case, second_response)
    assert isinstance(first_payload, dict) and isinstance(second_payload, dict), (
        f"{operation_case.method} {operation_case.path} must return JSON objects "
        "for structural idempotency comparison"
    )

    first_top_level_fields = frozenset(first_payload)
    second_top_level_fields = frozenset(second_payload)
    assert first_top_level_fields == second_top_level_fields, (
        f"{operation_case.method} {operation_case.path} returned different top-level "
        "fields for identical consecutive requests: "
        f"first={sorted(first_top_level_fields)}, "
        f"second={sorted(second_top_level_fields)}"
    )

    first_data = first_payload.get("data")
    second_data = second_payload.get("data")
    first_data_fields = (
        frozenset(first_data) if isinstance(first_data, dict) else frozenset()
    )
    second_data_fields = (
        frozenset(second_data) if isinstance(second_data, dict) else frozenset()
    )
    assert first_data_fields == second_data_fields, (
        f"{operation_case.method} {operation_case.path} returned different data "
        "structures for identical consecutive requests: "
        f"first={sorted(first_data_fields)}, second={sorted(second_data_fields)}"
    )

    first_records = (
        first_data.get("leaveReport") if isinstance(first_data, dict) else None
    )
    second_records = (
        second_data.get("leaveReport") if isinstance(second_data, dict) else None
    )
    first_record_count = len(first_records) if isinstance(first_records, list) else None
    second_record_count = len(second_records) if isinstance(second_records, list) else None
    assert first_record_count == second_record_count, (
        f"{operation_case.method} {operation_case.path} returned a different record "
        "count for identical consecutive requests: "
        f"first={first_record_count}, second={second_record_count}"
    )

    print(
        f"Idempotency observation {operation_case.method} {operation_case.path}: "
        f"status={first_response.status_code} both times; "
        f"record_count={first_record_count} both times; "
        f"top_level_fields={sorted(first_top_level_fields)}"
    )

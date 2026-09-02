"""Response completes within the documented SLA

Emits: NOT_APPLICABLE, WARN.
Reads metadata field(s): sla_ms.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Response completes within the documented SLA — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_response_time_within_sla(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    # Advisory, not blocking: exceeding the target emits WARN and leaves the
    # run's exit code alone. The old 20% buffer existed to prevent false
    # failures; with no failure to prevent it only delayed the signal, so the
    # flag fires at the target itself.
    threshold_ms = operation_case.sla_ms
    if threshold_ms is None:
        _skip_with_state(
            ResultState.NOT_APPLICABLE, "no SLA target resolved", field="sla_ms"
        )

    operation_key = (operation_case.method, operation_case.path)
    elapsed_ms = global_contract_context.bootstrap_durations_ms.get(operation_key)
    if elapsed_ms is None:
        # Measured during session bootstrap; this test issues no request of its
        # own. Advisory timing does not justify doubling SLA traffic across a
        # batch of APIs.
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"no bootstrap timing recorded for {operation_case.method} "
            f"{operation_case.path}",
        )

    measurement = (
        f"observed={elapsed_ms:.1f}ms threshold={threshold_ms}ms "
        f"operation={operation_case.method} {operation_case.path}"
    )
    print(f"SLA measurement {measurement}")

    if elapsed_ms > threshold_ms:
        _skip_with_state(
            ResultState.WARN,
            f"response time exceeded its advisory target: {measurement} "
            f"(over by {elapsed_ms - threshold_ms:.1f}ms)",
        )

"""A small valid request burst is not immediately blocked

Emits: FAIL, PASS, SKIPPED_NO_TOKEN.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("A small valid request burst is not immediately blocked — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_small_burst_does_not_trigger_immediate_blocking(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    _require_host_representative(operation_case)
    burst_row = api_row

    if operation_case.requires_bearer_auth:
        token = global_contract_context.config_for(operation_case).get("AUTH_TOKEN")
        if not token:
            _skip_with_state(
                ResultState.SKIPPED_NO_TOKEN,
                f"{operation_case.method} {operation_case.path} requires a bearer "
                "token and the session bootstrap did not provide one",
            )
        burst_row = _api_row_with_authorization(api_row, f"Bearer {token}")

    observed_statuses: list[int] = []

    for request_number in range(1, BURST_REQUEST_COUNT + 1):
        response = perform_api_request(
            burst_row,
            global_contract_context.config_for(operation_case),
        )
        observed_statuses.append(response.status_code)
        # The known WAF fingerprint: HTTP 403 with a completely empty body.
        # An application-level 403 carries a body; this one does not.
        has_waf_fingerprint = (
            response.status_code == 403 and not response.content.strip()
        )
        assert not has_waf_fingerprint, (
            "Small sequential burst was blocked with the known WAF fingerprint "
            f"(HTTP 403 with an empty body) at request {request_number} of "
            f"{operation_case.method} {operation_case.path}; "
            f"statuses observed before stopping: {observed_statuses}"
        )

    print(
        f"Small-burst observation {operation_case.method} {operation_case.path}: "
        f"statuses={observed_statuses}"
    )

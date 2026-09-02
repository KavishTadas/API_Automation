"""Host refuses the TRACE method

TRACE echoes the request back and must be off.

Emits: FAIL, PASS.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Host refuses the TRACE method")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_trace_method_is_disabled(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """TRACE echoes the request back and must be off.

    Host-level, and the one check here that sends a method the endpoint did
    not declare. It is safe by construction: TRACE mutates nothing, and the
    check exists precisely because it should be refused.
    """
    api_row = _require_runnable(operation_case, global_contract_context)

    response = perform_api_request(
        {**api_row, "HTTP Method": "TRACE", "Request Body": ""},
        global_contract_context.config_for(operation_case),
    )

    assert response.status_code >= 400, (
        f"{urlsplit(str(response.url)).netloc} answered TRACE with "
        f"{response.status_code}; TRACE echoes the request and must be disabled"
    )

"""Write endpoints refuse an unsupported media type

A JSON endpoint sent text/plain must refuse it rather than parse it.

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Write endpoints refuse an unsupported media type — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_unsupported_media_type_rejected(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """A JSON endpoint sent text/plain must refuse it rather than parse it.

    Gated on a documented request body: an endpoint the inventory records no
    body for has no media type to get wrong.
    """
    api_row = _require_runnable(operation_case, global_contract_context)

    if operation_case.method not in {"POST", "PUT", "PATCH"}:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} carries no request body",
            field="HTTP Method",
        )
    if not str(api_row.get("Request Body", "")).strip():
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "inventory records no request body for this endpoint",
            field="Request Body",
        )

    response = perform_api_request(
        _headers_with(api_row, "Content-Type=text/plain"),
        global_contract_context.config_for(operation_case),
    )

    assert response.status_code >= 400, (
        f"{operation_case.method} {operation_case.path} accepted a text/plain body "
        f"with {response.status_code}; a JSON endpoint should answer 415"
    )

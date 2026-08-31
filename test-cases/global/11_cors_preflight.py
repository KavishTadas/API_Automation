"""CORS preflight permits the documented method

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("CORS preflight permits the documented method — {param_id}")
@pytest.mark.skipif(
    not _cors_preflight_enabled(),
    reason=format_reason(
        ResultState.NOT_APPLICABLE,
        f"CORS preflight is opt-in; set {CORS_PREFLIGHT_FLAG}=1 to enable it. "
        "These are internal server-to-server APIs behind a WAF and are not "
        "expected to emit Access-Control-* headers",
    ),
)
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_cors_preflight(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    preflight_row = {
        **api_row,
        "HTTP Method": "OPTIONS",
        "Request Body": "",
        "Request Parameters": (
            "headers: Origin=https://global-contract.example; "
            f"Access-Control-Request-Method={operation_case.method}; "
            "Access-Control-Request-Headers=authorization,content-type"
        ),
        "Dependent APIs / Services": "",
    }
    response = perform_api_request(
        preflight_row,
        global_contract_context.config_for(operation_case),
    )

    allow_origin = response.headers.get("access-control-allow-origin")
    allow_methods = response.headers.get("access-control-allow-methods")
    allowed_methods = {
        method.strip().upper()
        for method in (allow_methods or "").split(",")
        if method.strip()
    }

    assert allow_origin and allow_methods and operation_case.method in allowed_methods, (
        f"OPTIONS {operation_case.path} returned {response.status_code}; "
        f"Access-Control-Allow-Origin={allow_origin!r}, "
        f"Access-Control-Allow-Methods={allow_methods!r}"
    )

"""Transport is HTTPS

The resolved host must be TLS. Metadata only — issues no request.

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Transport is HTTPS — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_transport_is_https(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """The resolved host must be TLS. Metadata only — issues no request."""
    api_row = _require_runnable(operation_case, global_contract_context)

    resolved = _resolve_templates(
        api_row.get("Base URL", ""), global_contract_context.config_for(operation_case)
    ).strip()
    if not resolved or "{{" in resolved:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "base URL did not resolve, so its scheme cannot be checked",
            field="Base URL",
        )

    scheme = urlsplit(resolved).scheme.lower()
    assert scheme == "https", (
        f"{operation_case.method} {operation_case.path} resolves to {scheme}://; "
        "credentials and tokens must never cross a plaintext transport"
    )

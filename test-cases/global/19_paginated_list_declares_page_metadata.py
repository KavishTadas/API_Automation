"""Paginated list declares its page metadata

A list documented as paginated must return page metadata with the page.

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): paginated, response.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Paginated list declares its page metadata — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_paginated_list_declares_page_metadata(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """A list documented as paginated must return page metadata with the page."""
    api_row = _require_runnable(operation_case, global_contract_context)

    if not operation_case.paginated:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "operation is not declared paginated",
            field="paginated",
        )

    response = _bootstrap_or_request(operation_case, global_contract_context, api_row)
    if response.status_code >= 400:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"list returned {response.status_code}; no page to inspect",
            field="response",
        )

    try:
        payload = response.json()
    except ValueError:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "response is not JSON; page metadata cannot be located",
            field="response",
        )

    candidates = {"page", "pagenumber", "pagesize", "total", "totalelements",
                  "totalpages", "count", "offset", "limit", "hasnext", "next"}
    seen: set[str] = set()
    if isinstance(payload, dict):
        seen = {str(key).lower().replace("_", "") for key in payload}
        for wrapper in ("data", "result", "payload", "meta", "pageable"):
            inner = payload.get(wrapper)
            if isinstance(inner, dict):
                seen |= {str(key).lower().replace("_", "") for key in inner}

    assert seen & candidates, (
        f"{operation_case.method} {operation_case.path} is documented as paginated "
        f"but its response carries no page metadata; saw keys {sorted(seen) or 'none'}"
    )

"""Host discloses no product version in its headers

Server and X-Powered-By must not carry a version number.

Emits: FAIL, PASS.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Host discloses no product version in its headers")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_no_server_version_disclosure(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """Server and X-Powered-By must not carry a version number.

    Host-level. A banner naming the exact build hands an attacker the CVE list
    for free; the header may stay, the version must not.
    """
    api_row = _require_runnable(operation_case, global_contract_context)
    response = _bootstrap_or_request(operation_case, global_contract_context, api_row)

    disclosed = {
        name: value
        for name, value in response.headers.items()
        if name.lower() in {"server", "x-powered-by", "x-aspnet-version"}
        and _VERSION_IN_HEADER.search(value or "")
    }

    assert not disclosed, (
        f"{urlsplit(str(response.url)).netloc} discloses a product version: {disclosed}"
    )

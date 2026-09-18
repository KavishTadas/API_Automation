"""Host sets the baseline security response headers

X-Content-Type-Options, and a framing policy.

Emits: FAIL, PASS.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Host sets the baseline security response headers")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_security_headers_present(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    """X-Content-Type-Options, and a framing policy.

    Host-level: these are set by the gateway, not by an endpoint, so this is
    measured once per host and referenced from the other APIs on it.
    """
    api_row = _require_runnable(operation_case, global_contract_context)
    # Declared host-level in catalogue.HOST_LEVEL_TESTS and described so above,
    # but it ran once per API -- so one server setting surfaced as one failure
    # for every endpoint behind that server (42 in the 2026-09-17 run). The
    # finding is unchanged; only its multiplicity was wrong.
    _require_host_representative(operation_case)
    response = _bootstrap_or_request(operation_case, global_contract_context, api_row)

    headers = {key.lower(): value for key, value in response.headers.items()}
    missing = []
    if headers.get("x-content-type-options", "").strip().lower() != "nosniff":
        missing.append("X-Content-Type-Options: nosniff")
    framing = headers.get("x-frame-options", "") or headers.get("content-security-policy", "")
    if "frame" not in framing.lower() and "deny" not in framing.lower() \
            and "sameorigin" not in framing.lower():
        missing.append("X-Frame-Options or a CSP frame-ancestors directive")

    assert not missing, (
        f"{urlsplit(str(response.url)).netloc} does not set: {'; '.join(missing)}"
    )

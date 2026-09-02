"""Response exposes no credentials or tokens

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Response exposes no credentials or tokens — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_no_credential_leakage_in_response(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    responses = global_contract_context.response_samples.get(
        (operation_case.method, operation_case.path),
        (),
    )
    if not responses:
        # Nothing was executed, so nothing was inspected. Falling through the
        # loop would report a pass for a check that never ran — exactly the
        # accounting this tier must not produce.
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"no response sample to inspect for {operation_case.method} "
            f"{operation_case.path}",
        )

    for sample_index, response in enumerate(responses):
        payload = _response_json(operation_case, response)
        fields = _field_paths(payload)
        credential_paths = [
            path
            for field_name, path in fields
            if re.search(r"password|secret", field_name, re.IGNORECASE)
        ]
        assert not credential_paths, (
            f"{operation_case.method} {operation_case.path} HTTP "
            f"{response.status_code} exposed credential field(s): "
            f"{credential_paths}"
        )

        token_paths = [
            path
            for field_name, path in fields
            if re.sub(r"[^a-z0-9]", "", field_name.lower())
            in {"token", "authtoken"}
        ]
        is_expected_auth_success = (
            sample_index == 0
            and operation_case.method == "POST"
            and operation_case.path == "/auth/token"
            and response.status_code == 200
        )
        if is_expected_auth_success:
            assert token_paths == ["$.token"], (
                "POST /auth/token HTTP 200 must contain exactly one root token field; "
                f"observed token field paths: {token_paths}"
            )
        else:
            assert not token_paths, (
                f"{operation_case.method} {operation_case.path} HTTP "
                f"{response.status_code} unexpectedly exposed token field(s): "
                f"{token_paths}"
            )

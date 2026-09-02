"""Response honors documented content negotiation

Emits: FAIL, NOT_APPLICABLE, PASS.
Reads metadata field(s): documented_content_types.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Response honors documented content negotiation — {param_id}")
@pytest.mark.parametrize(
    "operation_case",
    build_contract_params(xfail_auth_waf=True),
)
def test_content_type_negotiation(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)
    response = global_contract_context.bootstrap_responses.get(
        (operation_case.method, operation_case.path)
    )
    if response is None:
        response = perform_api_request(
            api_row,
            global_contract_context.config_for(operation_case),
        )

    xml_response = perform_api_request(
        _api_row_with_additional_headers(
            api_row,
            {"Accept": "application/xml"},
        ),
        global_contract_context.config_for(operation_case),
    )

    expected_content_types = operation_case.documented_content_types.get(
        response.status_code,
        frozenset(),
    )
    if not expected_content_types:
        # No source declares a content type for the status this API actually
        # returned. That is missing metadata, and test_status_code_matches_spec
        # already fails an undocumented status — reporting it here too would
        # count one defect twice.
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"no content type declared for {operation_case.method} "
            f"{operation_case.path} HTTP {response.status_code}",
            field="documented_content_types",
        )

    actual_content_type = _response_media_type(response)
    xml_content_type = _response_media_type(xml_response)
    errors: list[str] = []

    if actual_content_type not in expected_content_types:
        errors.append(
            f"normal request returned status {response.status_code} with "
            f"Content-Type {actual_content_type or '<missing>'}; documented types are "
            f"{sorted(expected_content_types)}"
        )
    if xml_response.status_code != 406 and xml_content_type != "application/json":
        errors.append(
            f"Accept: application/xml returned status {xml_response.status_code} with "
            f"Content-Type {xml_content_type or '<missing>'}; expected 406 or ignored "
            "negotiation with application/json"
        )

    assert not errors, f"{operation_case.method} {operation_case.path}: {'; '.join(errors)}"

"""Response body matches the full OpenAPI schema

Emits: FAIL, NOT_APPLICABLE, NOT_ASSERTED, PASS.
Reads metadata field(s): none.

Split from test_global_api_contract.py in Phase 4; the assertion is
byte-identical to the pre-split source.
"""

from _support import *  # noqa: F401,F403


@allure.title("Response body matches the full OpenAPI schema — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_response_matches_full_schema(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    responses = global_contract_context.response_samples.get(
        (operation_case.method, operation_case.path),
        (),
    )
    if not responses:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "no response sample available to validate",
        )

    observed_statuses: list[int] = []
    unschematized_statuses: list[int] = []

    for response in responses:
        observed_statuses.append(response.status_code)
        schema_document = _response_schema_document(
            operation_case,
            response.status_code,
        )
        if schema_document is None:
            # No source describes this status. test_status_code_matches_spec
            # already fails an undocumented status, so reporting it here too
            # would double-count one defect.
            unschematized_statuses.append(response.status_code)
            continue

        payload = _response_json(operation_case, response)
        errors = sorted(
            Draft202012Validator(schema_document).iter_errors(payload),
            key=lambda error: [str(part) for part in error.absolute_path],
        )

        assert not errors, (
            f"{operation_case.method} {operation_case.path} HTTP "
            f"{response.status_code} failed its complete response schema: "
            + "; ".join(_format_schema_error(error) for error in errors)
        )

    if unschematized_statuses:
        _record_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} has no response schema "
            f"for observed status(es) {sorted(set(unschematized_statuses))}",
        )

    # Without a success sample this test asserted nothing about the success
    # schema. That is an absence, not a defect -- and for a destructive verb it
    # is deliberate: the suite refuses to fire a real DELETE with a real id at
    # UAT, so no 2xx can ever be observed. Failing here punished the endpoint
    # for a guardrail the engine imposed on itself, and D7's mirror forbids it:
    # a request we chose not to make cannot be scored as a failure. The error
    # half below already reports its own absence the same way.
    if not any(200 <= status < 300 for status in observed_statuses):
        _skip_with_state(
            ResultState.NOT_ASSERTED,
            f"{operation_case.method} {operation_case.path} success-schema half not "
            f"validated: no success response was observed "
            f"(observed {observed_statuses or 'nothing'})",
        )

    # The error half is validated only when an error sample exists. It used to
    # be mandatory, which hard-failed every API that simply had no 4xx sample
    # row — a failure on absence rather than on merit.
    if not any(status >= 400 for status in observed_statuses):
        _record_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} error-schema half not "
            f"validated: no error sample available (observed {observed_statuses})",
        )

"""Whitespace-only and quotes-only names are rejected, not stored

Ported from the attendance repo's `TC-GLOB-03` and `TC-GLOB-04`, combined
because they are the same question asked with two samples. That suite found two
real defects here: Status Threshold and Late/Early Policy both answered
`201 Created` to a name of `""""""`.

Not covered by `test_special_characters_in_input`, which sends
`ÉMP-测试-😀-🔒` and asserts only that the server does not fall over. Unicode is
*valid* input an API should accept; a blank name is *invalid* input it should
refuse. Opposite expectations, so they cannot be one check.

## This check has a side effect when it fails

It is `POST`-only, and a failure means the API accepted the payload -- which is
to say **a junk row now exists**. That is unavoidable: the only way to observe
"blank names get stored" is for one to get stored. It is scoped to create
endpoints deliberately, because a junk row is recoverable while a blank name
written over a real record by `PUT` is not.

Emits: FAIL, NOT_APPLICABLE, NOT_ASSERTED, PASS.
Reads metadata field(s): request_body_sample.
"""

from _support import *  # noqa: F401,F403

#: TC-GLOB-04 and TC-GLOB-03 respectively.
BLANK_SAMPLES = {"whitespace-only": "   ", "quotes-only": '""""""'}


#: Only name-like fields are blanked. Blanking *every* string field looks
#: stricter and is actually weaker: the rejection can then come from any field,
#: so a PASS says nothing about whether the name itself is validated. The source
#: probe sends `"policyName": "\"\"\"\"\"\""` with description and heading left
#: valid, which is the version that isolates the defect.
_NAME_FIELD = re.compile(r"name$|^name", re.I)


def _blank_name_body(operation_case: OperationCase, sample: str) -> str | None:
    """The API's own sample body with only its name-like fields blanked."""
    body = _resolver().request_body_sample(operation_case.method, operation_case.path)
    if not isinstance(body, (dict, list)):
        return None
    payload = json.loads(json.dumps(body))
    string_fields = _string_field_paths(payload)
    if not string_fields:
        return None

    targets = [p for p, _ in string_fields if p and _NAME_FIELD.search(str(p[-1]))]
    if not targets:
        # No field is named like a name. Falling back to the first string field
        # keeps the probe honest for payloads that spell it differently, rather
        # than silently reporting NOT_APPLICABLE for an endpoint that has one.
        targets = [string_fields[0][0]]

    for field_path in targets:
        _set_in(payload, field_path, sample)
    return json.dumps(payload, ensure_ascii=False)


@allure.title("Blank name input is rejected — {param_id}")
@pytest.mark.parametrize("operation_case", build_contract_params())
def test_blank_name_input_is_rejected(
    operation_case: OperationCase,
    global_contract_context: GlobalContractContext,
) -> None:
    api_row = _require_runnable(operation_case, global_contract_context)

    if operation_case.method.upper() != "POST":
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            "create-only: a blank name accepted by PUT would overwrite a real "
            "record, which is a worse thing to do than observing the defect",
        )

    accepted: list[str] = []
    probed = 0
    for label, sample in BLANK_SAMPLES.items():
        body = _blank_name_body(operation_case, sample)
        if body is None:
            continue
        probed += 1
        response = perform_api_request(
            {**api_row, "Request Body": body},
            global_contract_context.config_for(operation_case),
        )
        _require_reached_the_handler(response, operation_case, "the blank name")
        print(
            f"Blank name observation ({label}) {operation_case.method} "
            f"{operation_case.path}: status={response.status_code}"
        )
        if 200 <= response.status_code < 300:
            accepted.append(f"{label} -> {response.status_code}")

    if not probed:
        _skip_with_state(
            ResultState.NOT_APPLICABLE,
            f"{operation_case.method} {operation_case.path} has no request body "
            "sample with a string field to blank",
            field="request_body_sample",
        )

    assert not accepted, (
        f"{operation_case.method} {operation_case.path} accepted a blank name "
        f"({'; '.join(accepted)}); a record with no meaningful name was stored"
    )

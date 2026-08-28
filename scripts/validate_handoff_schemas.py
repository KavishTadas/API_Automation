"""Validate the handoff bundle against its published JSON Schemas.

    python scripts/validate_handoff_schemas.py

The bundle ships three Draft 2020-12 schemas and four samples. The schemas are
**normative**; the samples are illustrative. This checks that the samples --
and the two documents no sample covers, the ABORTED path and a live result --
actually satisfy the contract the platform team will generate Java types from.

It also runs the negative cases, because a schema that accepts everything
passes every positive test. A manifest carrying both ``ref`` and ``definition``,
a manifest with an unknown field, and a result missing ``cleanBlockers`` must
each be REJECTED, and the rejection must name a useful JSON path.

Exit 0 all checks passed, 1 something did not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "docs" / "platform-handoff"

#: sample -> schema. Every shipped sample must validate against its contract.
SAMPLES = {
    "sample-run-manifest.json": "schema-run-manifest.json",
    "sample-catalogue.json": "schema-catalogue.json",
    "sample-result-batch.json": "schema-result.json",
    "sample-result-single-api.json": "schema-result.json",
}


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(schema_name: str) -> Draft202012Validator:
    schema = _load(BUNDLE / schema_name)
    # Check the schema is itself a legal Draft 2020-12 schema before trusting
    # any verdict it gives. A typo'd keyword is silently ignored by JSON Schema,
    # so an invalid schema does not fail loudly -- it just stops checking.
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _errors(validator: Draft202012Validator, document: object) -> list[str]:
    return [
        f"{error.json_path}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda e: e.path)
    ]


def _aborted_document() -> dict:
    """The real ABORTED document, from the engine rather than hand-written.

    This is the path a consumer can least afford to crash on, and it already
    shipped one KeyError -- ``counts`` as ``{}`` and no ``cleanBlockers`` at
    all. Hand-writing the expected shape here would re-open exactly that gap,
    so it is imported.
    """
    from tests.global_contract.run import _aborted_document as build

    return build(
        "'PROD' is not registered; known environments are ['UAT']",
        run_id="acceptance-aborted",
        environment="PROD",
        requested_tiers=("global_contract",),
    )


def _drift_checks() -> list[tuple[str, list[str]]]:
    """Compare every closed vocabulary in the schemas to the engine's constants.

    Validating samples proves the schemas accept what the engine emits TODAY.
    It cannot catch the engine growing an eighth result state, or a manifest
    field being added, while these files stay behind -- the samples would keep
    passing and the platform's generated Java types would quietly be wrong.

    So each enum, const and required-key set is diffed against the constant it
    was derived from. This is the check that makes the schemas maintainable
    rather than a snapshot that rots.
    """
    from tests.global_contract.catalogue import (
        ASSERTION_STATES,
        GLOBAL_TEST_CATEGORIES,
        ApplicabilityState,
        build_catalogue,
    )
    from tests.global_contract.result_emitter import (
        CLEAN_BLOCKING_STATES,
        GatewayClassification,
        RunStatus,
    )
    from tests.global_contract.result_states import (
        EXECUTED_STATES,
        PASS_RATE_DENOMINATOR_STATES,
        REASON_SEPARATOR,
        ResultState,
    )
    from tests.global_contract.run_manifest import (
        KNOWN_TIERS,
        _DEFINITION_FIELDS,
        _ENTRY_FIELDS,
        _MANIFEST_FIELDS,
        _PAYLOAD_FIELDS,
        _RULE_FIELDS,
    )

    manifest = _load(BUNDLE / "schema-run-manifest.json")
    result = _load(BUNDLE / "schema-result.json")
    catalogue = _load(BUNDLE / "schema-catalogue.json")
    sample_catalogue = _load(BUNDLE / "sample-catalogue.json")

    states = [state.name for state in ResultState]
    rules = catalogue["$defs"]["classificationRules"]["properties"]

    pairs: list[tuple[str, object, object]] = [
        ("the seven result states", states, result["$defs"]["resultState"]["enum"]),
        ("summary.counts covers every state", states, result["$defs"]["counts"]["required"]),
        (
            "run statuses",
            [RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_ERRORS, RunStatus.ABORTED],
            result["$defs"]["runStatus"]["enum"],
        ),
        (
            "gateway classifications",
            [
                GatewayClassification.AUTH_FAILURE_401,
                GatewayClassification.APPLICATION_AUTH_FAILURE_403,
                GatewayClassification.GATEWAY_WAF_EMPTY_BODY_403,
            ],
            result["$defs"]["gatewayClassification"]["enum"],
        ),
        (
            "cleanBlockers states",
            [state.name for state in CLEAN_BLOCKING_STATES],
            result["$defs"]["summary"]["properties"]["cleanBlockers"]["items"]["enum"],
        ),
        ("manifest top-level fields", _MANIFEST_FIELDS, manifest["properties"]),
        ("manifest entry fields", _ENTRY_FIELDS, manifest["$defs"]["apiEntry"]["properties"]),
        ("definition fields", _DEFINITION_FIELDS, manifest["$defs"]["definition"]["properties"]),
        ("payload row fields", _PAYLOAD_FIELDS, manifest["$defs"]["payloadRow"]["properties"]),
        ("rule row fields", _RULE_FIELDS, manifest["$defs"]["ruleRow"]["properties"]),
        ("known tiers", KNOWN_TIERS, manifest["properties"]["requestedTiers"]["items"]["enum"]),
        ("assertion states", ASSERTION_STATES, catalogue["$defs"]["assertionState"]["enum"]),
        (
            "test categories",
            set(GLOBAL_TEST_CATEGORIES.values()) | {"coverage-gap"},
            catalogue["$defs"]["category"]["enum"],
        ),
        (
            "applicability states",
            [ApplicabilityState.PLANNED, ApplicabilityState.NOT_APPLICABLE],
            catalogue["$defs"]["applicabilityVerdict"]["properties"]["state"]["enum"],
        ),
        (
            "passRateDenominatorStates",
            [state.name for state in PASS_RATE_DENOMINATOR_STATES],
            rules["passRateDenominatorStates"]["const"],
        ),
        (
            "executedStates",
            [state.name for state in EXECUTED_STATES],
            rules["executedStates"]["const"],
        ),
        ("reasonSeparator", [REASON_SEPARATOR], [rules["reasonSeparator"]["const"]]),
        (
            # The tier grew 12 -> 22 on main while the bundle sat on a branch, and
            # every check here still passed: the samples were self-consistent and no
            # enum had changed. Nothing tied the SHIPPED catalogue to the tier the
            # engine actually discovers, so the drift was invisible until a reader
            # counted by hand. This is that tie.
            "shipped sample-catalogue lists every global check the engine discovers",
            [case["id"] for case in build_catalogue()["testCases"]["global"]],
            [case["id"] for case in sample_catalogue["testCases"]["global"]],
        ),
    ]

    checks: list[tuple[str, list[str]]] = []
    for label, engine, schema in pairs:
        engine_side, schema_side = sorted(engine), sorted(schema)
        if engine_side == schema_side:
            checks.append((label, []))
        else:
            checks.append(
                (
                    label,
                    [
                        f"engine has {engine_side}",
                        f"schema has {schema_side}",
                        "the engine is authoritative; update the schema",
                    ],
                )
            )
    return checks


def main() -> int:
    failures: list[str] = []
    checks = 0

    def report(label: str, problems: list[str]) -> None:
        nonlocal checks
        checks += 1
        if problems:
            failures.append(label)
            print(f"  FAIL  {label}")
            for problem in problems[:10]:
                print(f"          {problem}")
            if len(problems) > 10:
                print(f"          ... and {len(problems) - 10} more")
        else:
            print(f"  ok    {label}")

    print("Schemas are legal Draft 2020-12:")
    for schema_name in sorted(set(SAMPLES.values())):
        try:
            _validator(schema_name)
            report(schema_name, [])
        except Exception as error:  # noqa: BLE001 - report, do not raise
            report(schema_name, [f"$: {type(error).__name__}: {error}"])

    print("\nShipped samples validate against their schema:")
    for sample_name, schema_name in SAMPLES.items():
        validator = _validator(schema_name)
        report(
            f"{sample_name} -> {schema_name}",
            _errors(validator, _load(BUNDLE / sample_name)),
        )

    print("\nThe ABORTED document validates (the path least able to retry):")
    report(
        "_aborted_document() -> schema-result.json",
        _errors(_validator("schema-result.json"), _aborted_document()),
    )

    print("\nLive result documents validate, where present:")
    result_validator = _validator("schema-result.json")
    live = sorted((ROOT / "reports" / "platform").glob("*.json"))
    if not live:
        print("  --    none in reports/platform (run a scenario to generate one)")
    for path in live:
        report(f"reports/platform/{path.name}", _errors(result_validator, _load(path)))

    print("\nNegative cases are REJECTED, each naming a JSON path:")
    manifest_validator = _validator("schema-run-manifest.json")
    base_entry = {
        "ref": "get|/api/attendancepolicy|attendance policy master|get all policies",
        "credentialAlias": "attendance-svc-uat-01",
    }
    definition = {"HTTP Method": "GET", "Endpoint Path": "/api/attendancepolicy"}

    negatives: list[tuple[str, Draft202012Validator, object, str]] = [
        (
            "manifest carrying both 'ref' and 'definition'",
            manifest_validator,
            {
                "runId": "neg-both",
                "environment": "UAT",
                "requestedTiers": ["global_contract"],
                "apis": [{**base_entry, "definition": definition}],
            },
            "$.apis[0]",
        ),
        (
            "manifest carrying neither 'ref' nor 'definition'",
            manifest_validator,
            {
                "runId": "neg-neither",
                "environment": "UAT",
                "requestedTiers": ["global_contract"],
                "apis": [{"credentialAlias": "attendance-svc-uat-01"}],
            },
            "$.apis[0]",
        ),
        (
            "manifest with an unknown top-level field",
            manifest_validator,
            {
                "runId": "neg-unknown-top",
                "environment": "UAT",
                "requestedTiers": ["global_contract"],
                "apis": [base_entry],
                "$comment": "a header comment the engine rejects",
            },
            "$",
        ),
        (
            "manifest with a typo'd 'authProviderApiID'",
            manifest_validator,
            {
                "runId": "neg-unknown-entry",
                "environment": "UAT",
                "requestedTiers": ["global_contract"],
                "apis": [{**base_entry, "authProviderApiID": "post|/auth/token|x|y"}],
            },
            "$.apis[0]",
        ),
        (
            "manifest whose credentialAlias holds a JWT",
            manifest_validator,
            {
                "runId": "neg-jwt-alias",
                "environment": "UAT",
                "requestedTiers": ["global_contract"],
                "apis": [
                    {
                        "ref": base_entry["ref"],
                        "credentialAlias": "eyJhbGciOiJIUzI1NiJ9.FAKE0S.sig000",
                    }
                ],
            },
            "$.apis[0].credentialAlias",
        ),
    ]

    result_document = _load(BUNDLE / "sample-result-single-api.json")

    missing_blockers = json.loads(json.dumps(result_document))
    missing_blockers["summary"].pop("cleanBlockers")
    negatives.append(
        (
            "result missing summary.cleanBlockers",
            result_validator,
            missing_blockers,
            "$.summary",
        )
    )

    absent_count = json.loads(json.dumps(result_document))
    absent_count["summary"]["counts"].pop("NOT_ASSERTED")
    negatives.append(
        (
            "result whose counts omit a state instead of zeroing it",
            result_validator,
            absent_count,
            "$.summary.counts",
        )
    )

    warn_without_numbers = json.loads(json.dumps(result_document))
    warn_without_numbers["apis"][0]["results"][0].update(
        {"state": "WARN", "executed": True}
    )
    negatives.append(
        (
            "WARN result carrying neither observed nor threshold",
            result_validator,
            warn_without_numbers,
            "$.apis[0].results[0]",
        )
    )

    na_without_field = json.loads(json.dumps(result_document))
    for api in na_without_field["apis"]:
        for entry in api["results"]:
            if entry["state"] == "NOT_APPLICABLE":
                entry.pop("missingField")
                break
        else:
            continue
        break
    negatives.append(
        (
            "NOT_APPLICABLE result with no missingField key at all",
            result_validator,
            na_without_field,
            "$.apis[",
        )
    )

    bad_status = json.loads(json.dumps(result_document))
    bad_status["status"] = "PARTIAL"
    negatives.append(
        ("result with an invented run status", result_validator, bad_status, "$.status")
    )

    for label, validator, document, expected_path in negatives:
        problems = _errors(validator, document)
        if not problems:
            report(label, ["$: ACCEPTED but should have been rejected"])
        elif not any(p.startswith(expected_path) for p in problems):
            report(
                label,
                [f"rejected, but no error names {expected_path}: {problems[:3]}"],
            )
        else:
            named = next(p for p in problems if p.startswith(expected_path))
            checks += 1
            print(f"  ok    {label}")
            print(f"          rejected at {named.split(':')[0]}")

    print("\nSchema vocabularies match the engine's own constants:")
    for label, problems in _drift_checks():
        report(label, problems)

    print(f"\n{checks - len(failures)}/{checks} checks passed.")
    if failures:
        print("FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())

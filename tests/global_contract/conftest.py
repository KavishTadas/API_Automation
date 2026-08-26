"""Allure hierarchy and result emission for cross-cutting global contract checks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import allure
import pytest

from tests.global_contract.catalogue import (
    CATALOGUE_VERSION,
    HOST_LEVEL_TESTS,

    global_test_id,
)
from tests.global_contract.result_emitter import (
    ResultCollector,
    build_result_document,
    record_from_report,
    write_result_document,
)

SUITE_UMBRELLA = "Global Contract Checks"

#: Where the run's result document lands.
#:
#: Under ``reports/`` deliberately: that is the only tree the repo's redaction
#: layer (`scripts/reporter-config.js`) scopes its fs hooks to, and it is
#: gitignored, so a result document can never be committed by accident. The
#: Python emitter does its own redaction as well — the JS hook only covers Node
#: writes — see scripts/regression/verify-result-emitter-redaction.py.
RESULTS_ENV_VAR = "GLOBAL_CONTRACT_RESULT_PATH"
DEFAULT_RESULT_PATH = Path("reports") / "platform" / "global-contract-results.json"

def _feature_for_test(request: pytest.FixtureRequest) -> str:
    callspec = getattr(request.node, "callspec", None)
    operation_case = callspec.params.get("operation_case") if callspec else None

    if operation_case is not None:
        return f"{operation_case.method} {operation_case.path}"
    return "Cross-cutting API behavior"

@pytest.fixture(autouse=True)
def global_contract_allure_hierarchy(request: pytest.FixtureRequest) -> None:
    """Keep Phase G contract tests separate from collection-owned suites."""
    feature = _feature_for_test(request)
    story = (
        getattr(request.node, "originalname", None)
        or request.node.name.split("[", 1)[0]
    )

    allure.dynamic.epic(SUITE_UMBRELLA)
    allure.dynamic.feature(feature)
    allure.dynamic.story(story)
    allure.dynamic.parent_suite(SUITE_UMBRELLA)
    allure.dynamic.suite(feature)
    allure.dynamic.sub_suite(story)
    allure.dynamic.label("sourceType", "Python global-contract")

# ---------------------------------------------------------------------------
# Result emission
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    config._global_contract_collector = ResultCollector()  # type: ignore[attr-defined]

def _collector(config: pytest.Config) -> ResultCollector | None:
    return getattr(config, "_global_contract_collector", None)

def _measured_by(item: pytest.Item, host: str) -> str:
    """The apiRef carrying ``host``'s measurement, or ``""`` if unresolvable.

    Read off the test module rather than recomputed here, so there is exactly
    one definition of which case represents a host.

    Resolved through ``item.module`` — the module object pytest already holds
    for this test — rather than by looking a name up in ``sys.modules``. There
    is no ``__init__.py`` under ``tests/global_contract``, so pytest's default
    prepend import mode registers this module as ``test_global_api_contract``,
    not by its dotted path; a name-based lookup silently missed and every
    ``measuredBy`` came out null. Asking the item removes the guess.
    """
    if not host:
        return ""
    resolver = getattr(getattr(item, "module", None), "host_measured_by", None)
    if resolver is None:
        return ""
    return resolver().get(host, "")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Any:
    outcome = yield
    report = outcome.get_result()

    if report.when != "call" and not (report.when == "setup" and report.skipped):
        return

    collector = _collector(item.config)
    if collector is None:
        return

    callspec = getattr(item, "callspec", None)
    operation_case = callspec.params.get("operation_case") if callspec else None
    if operation_case is None:
        return

    function_name = getattr(item, "originalname", None) or item.name.split("[", 1)[0]
    test_id = global_test_id(function_name)
    api_ref = operation_case.api_ref

    # `reason` is where the state lives. A skip's longrepr is a
    # (path, lineno, reason) triple; an xfail carries it on `wasxfail`.
    reason = None
    if report.skipped and isinstance(report.longrepr, tuple):
        reason = report.longrepr[2]
    was_xfail = hasattr(report, "wasxfail")
    if was_xfail and not reason:
        reason = getattr(report, "wasxfail", "") or None

    if reason is None and report.failed:
        # A failure's longrepr is a traceback object, not the tuple a skip uses,
        # so the skip path above leaves it empty — and a FAIL with no reason is
        # a red row the platform cannot explain. Take the assertion's own crash
        # message: it is the one line that says what was expected and what came
        # back. The emitter redacts it on write like every other string.
        crash = getattr(getattr(report, "longrepr", None), "reprcrash", None)
        message = str(getattr(crash, "message", "") or "").strip()
        if not message:
            message = str(getattr(report, "longreprtext", "") or "").strip()
        # Assertion messages are multi-line; the first two carry the claim.
        reason = " ".join(message.splitlines()[:2]).strip() or None

    host_level = function_name in HOST_LEVEL_TESTS
    references_host = host_level and "is reported against" in str(reason or "")
    measured_by = _measured_by(item, operation_case.host) if host_level else ""

    collector.record_api(api_ref, operation_case.provenance)
    collector.add(
        record_from_report(
            test_id=test_id,
            api_ref=api_ref,
            outcome=report.outcome,
            reason=reason,
            was_xfail=was_xfail,
            duration_ms=report.duration * 1000,
            node_id=item.nodeid,
            host_level=host_level,
            host=operation_case.host,
            references_host_result=references_host,
            measured_by=measured_by,
            provenance=operation_case.provenance,
        )
    )

def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    collector = _collector(session.config)
    if collector is None or not collector.records:
        return

    manifest = getattr(session.config, "_global_contract_manifest", None)
    run_id = getattr(manifest, "run_id", "") or "local-run"
    environment = getattr(manifest, "environment", "") or os.environ.get(
        "API_TEST_ENV", ""
    )
    tiers = tuple(getattr(manifest, "requested_tiers", ()) or ("global_contract",))

    document = build_result_document(
        collector,
        run_id=run_id,
        environment=environment,
        requested_tiers=tiers,
        catalogue_version=CATALOGUE_VERSION,
    )

    destination = Path(
        os.environ.get(RESULTS_ENV_VAR, "").strip() or DEFAULT_RESULT_PATH
    )
    if not destination.is_absolute():
        destination = Path(__file__).resolve().parents[2] / destination

    written = write_result_document(destination, document)
    print(f"\nGlobal contract result document: {written}")

"""Allure hierarchy for cross-cutting global contract checks."""

from __future__ import annotations

import allure
import pytest


SUITE_UMBRELLA = "Global Contract Checks"


def _feature_for_test(request: pytest.FixtureRequest) -> str:
    callspec = getattr(request.node, "callspec", None)
    operation_case = callspec.params.get("operation_case") if callspec else None

    if operation_case is not None:
        return f"{operation_case.method} {operation_case.path}"
    if (
        getattr(request.node, "originalname", None)
        == "test_small_burst_does_not_trigger_immediate_blocking"
    ):
        return "GET /user/leaves/getAllLeaveReports"
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

"""Allure hierarchy for cross-cutting TLS-pinning security checks."""

from __future__ import annotations

import allure
import pytest


SUITE_UMBRELLA = "Security & TLS Pinning"
FEATURE_BY_TEST = {
    "test_live_request_succeeds_through_current_certificate_pin": "POST /auth/token",
    "test_wrong_certificate_pin_fails_closed_without_network": "Offline certificate pin enforcement",
}


@pytest.fixture(autouse=True)
def security_allure_hierarchy(request: pytest.FixtureRequest) -> None:
    """Keep TLS checks separate from collection-owned authentication suites."""
    story = (
        getattr(request.node, "originalname", None)
        or request.node.name.split("[", 1)[0]
    )
    feature = FEATURE_BY_TEST.get(story, "TLS certificate pinning")

    allure.dynamic.epic(SUITE_UMBRELLA)
    allure.dynamic.feature(feature)
    allure.dynamic.story(story)
    allure.dynamic.parent_suite(SUITE_UMBRELLA)
    allure.dynamic.suite(feature)
    allure.dynamic.sub_suite(story)
    allure.dynamic.label("sourceType", "Python security")

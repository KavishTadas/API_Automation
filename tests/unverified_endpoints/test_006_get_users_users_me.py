"""Archived generated check for the unverified ``GET /users/me`` endpoint.

The endpoint is not part of the authoritative HCM OpenAPI contract. This module
is preserved outside ``tests/auto_generated`` for traceability and must not make
HTTP requests as part of the HCM CI suite.
"""

from __future__ import annotations

import pytest

OUT_OF_SCOPE_REASON = (
    "GET /users/me is unverified and outside the authoritative HCM OpenAPI contract"
)
pytestmark = pytest.mark.skip(reason=OUT_OF_SCOPE_REASON)


def test_users_users_me_is_out_of_hcm_scope() -> None:
    """Retain the former generated check without invoking the endpoint."""
    pytest.skip(OUT_OF_SCOPE_REASON)

"""Emission hooks for the split tier.

The hooks themselves stay in ``tests/global_contract/conftest.py``; importing
them here registers them for this directory. They resolve their own module
globals, so re-export moves nothing but the registration.

``_support`` is star-imported so the session fixture is visible to every
check collected here.
"""

from __future__ import annotations

from tests.global_contract.conftest import *  # noqa: F401,F403
from tests.global_contract.conftest import (  # noqa: F401
    pytest_configure,
    pytest_runtest_makereport,
    pytest_sessionfinish,
)

from _support import *  # noqa: F401,F403

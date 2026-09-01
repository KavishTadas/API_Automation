"""Fixtures for the endpoint-specific case tier.

Lives here rather than in each case file so ``case_response`` and ``case_json``
are available to every case in the tree without an import. ``sys.path`` carries
the repo root so ``tests.api_runtime`` resolves: these files are collected by
path, not imported as a package, and ``test-cases`` is not a valid module name.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import case_json, case_response  # noqa: E402,F401

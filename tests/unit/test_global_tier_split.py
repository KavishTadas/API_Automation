"""Guards for the Phase 4 split and the hardened UI check.

Two properties are easy to break silently and neither shows up in a state count:

* a check file that exists but is never collected or never discovered, and
* a UI check that reports PASS because it interrogated a stale harness.
"""

from __future__ import annotations

import ast
import importlib.util
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GLOBAL_DIR = ROOT / "test-cases" / "global"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


registry = _load(GLOBAL_DIR / "_registry.py", "global_registry")
ui = _load(ROOT / "scripts" / "verify-harness-ui.py", "verify_harness_ui")


class TestSplitShape:
    def test_one_check_per_file(self):
        for path in sorted(GLOBAL_DIR.glob("[0-9][0-9]_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            tests = [
                n
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
            ]
            assert len(tests) == 1, f"{path.name} holds {len(tests)} checks"

    def test_registry_matches_the_files_on_disk(self):
        on_disk = sorted(p.name for p in GLOBAL_DIR.glob("[0-9][0-9]_*.py"))
        assert [f for _, _, f in registry.GLOBAL_CHECKS] == on_disk
        assert registry.CHECK_COUNT == 22

    def test_registry_agrees_with_the_catalogue(self):
        """The registry is the human index; the catalogue parses sources.

        They are derived independently on purpose -- a check cannot hide from
        the catalogue by being left out of the registry -- so they must agree.
        """
        from tests.global_contract.catalogue import global_tests

        catalogue_names = {t.function for t in global_tests()}
        registry_names = {fn for _, fn, _ in registry.GLOBAL_CHECKS}
        assert catalogue_names == registry_names

    def test_numbering_preserves_execution_order(self):
        numbers = [n for n, _, _ in registry.GLOBAL_CHECKS]
        assert numbers == sorted(numbers) == list(range(1, 23))

    def test_every_check_carries_the_shared_surface(self):
        """conftest resolves host_measured_by off the check's own module.

        A check importing only what it appears to reference would null
        `measuredBy` on every result it produces, and no state count would move.
        """
        for path in sorted(GLOBAL_DIR.glob("[0-9][0-9]_*.py")):
            body = path.read_text(encoding="utf-8")
            assert "from _support import *" in body, path.name

    def test_support_exports_the_underscore_helpers(self):
        """A star import skips underscore names unless __all__ says otherwise."""
        tree = ast.parse((GLOBAL_DIR / "_support.py").read_text(encoding="utf-8"))
        exported = next(
            n
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "__all__" for t in n.targets)
        )
        names = {c.value for c in exported.value.elts}
        for required in ("_require_runnable", "_skip_with_state", "host_measured_by"):
            assert required in names, required

    def test_no_assertion_lives_in_the_shared_module(self):
        """_support carries plumbing only; assertions belong to a named check."""
        tree = ast.parse((GLOBAL_DIR / "_support.py").read_text(encoding="utf-8"))
        tests = [
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        ]
        assert tests == []


class TestUiCheckHardening:
    def test_free_port_returns_a_usable_unused_port(self):
        port = ui.free_port()
        assert 1024 < port < 65536
        with socket.socket() as s:
            s.bind(("127.0.0.1", port))  # free right now, so this must succeed

    def test_free_port_varies(self):
        """A fixed port is what let a stale harness answer for a live one."""
        assert len({ui.free_port() for _ in range(6)}) > 1

    def test_startup_failure_aborts_rather_than_logging(self, monkeypatch):
        class DeadProcess:
            returncode = 1
            stdout = type("S", (), {"read": staticmethod(lambda: "bind failed")})()

            def poll(self):
                return 1

            def kill(self):
                pass

        monkeypatch.setattr(ui.subprocess, "Popen", lambda *a, **k: DeadProcess())
        with pytest.raises(ui.CheckAborted, match="exited with code 1"):
            ui.start_harness(12345)

    def test_a_reused_harness_is_refused(self, monkeypatch):
        """runsHeld > 0 means the process predates this check run."""
        class LiveProcess:
            def poll(self):
                return None

            def kill(self):
                pass

        monkeypatch.setattr(ui.subprocess, "Popen", lambda *a, **k: LiveProcess())
        monkeypatch.setattr(ui, "get_json", lambda *a, **k: {"runsHeld": 3})
        with pytest.raises(ui.CheckAborted, match="runsHeld=3"):
            ui.start_harness(12345)

    def test_provider_filter_is_read_from_ui_html(self, monkeypatch, tmp_path):
        """Restating the regexes would let the check pass against a filter the
        UI does not use -- the exact bug the filter was written to fix."""
        stub = tmp_path / "ui.html"
        stub.write_text("<html>no filter here</html>", encoding="utf-8")
        monkeypatch.setattr(ui, "UI_HTML", stub)
        with pytest.raises(ui.CheckAborted, match="no longer declares"):
            ui.ui_provider_filter()

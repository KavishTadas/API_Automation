"""Unit tests for the endpoint slug derivation.

Deliberately NOT under ``tests/global_contract/``: the global-contract runner
collects that entire directory, so a unit test placed there would change the
suite's result counts and break the phase verification these tests exist to
support.

Run with::

    python -m pytest tests/unit -q
"""

from __future__ import annotations

import pytest

from tests.global_contract.endpoint_slug import (
    MAX_SLUG_LENGTH,
    SlugCollisionError,
    SlugTooLongError,
    build_slug_map,
    slugify,
)


def row(module: str, method: str, path: str, sub: str = "case") -> dict[str, str]:
    return {
        "ref": f"{method.lower()}|{path}|{module}|{sub}",
        "module": module,
        "method": method,
        "path": path,
    }


class TestSlugify:
    def test_lowercases_and_replaces_separators(self):
        assert (
            slugify("Leave API", "GET", "/user/leaves/getAll", {})
            == "leave_api_get_user_leaves_getall"
        )

    def test_path_parameter_becomes_by_prefix(self):
        slug = slugify("X", "PUT", "/a/{holidayTemplateId}", {})
        assert slug == "x_put_a_by_holidaytemplateid"

    def test_collapses_runs_and_strips_edges(self):
        assert slugify("A--B", "GET", "//x//y//", {}) == "a_b_get_x_y"

    def test_alias_applies_case_insensitively(self):
        aliases = {"holiday template apis copy": "holiday-template"}
        slug = slugify("Holiday Template APIs Copy", "GET", "/a", aliases)
        assert slug.startswith("holiday_template_")

    def test_alias_does_not_touch_the_ref(self):
        """The alias changes the slug only; refs are contract-visible."""
        aliases = {"attenedance-july2026": "weekoff"}
        r = row("attenedance-july2026", "GET", "/api/attendance/week-offs/getAll")
        mapped = build_slug_map([r], aliases)
        assert mapped[r["ref"]].startswith("weekoff_")
        assert "attenedance-july2026" in r["ref"]  # typo preserved verbatim


class TestBuildSlugMap:
    def test_cases_on_one_endpoint_share_a_slug(self):
        rows = [
            row("employee auth api", "POST", "/auth/token", "tc01 - valid"),
            row("employee auth api", "POST", "/auth/token", "tc02 - invalid"),
            row("employee auth api", "POST", "/auth/token", "tc03 - missing"),
        ]
        mapped = build_slug_map(rows, {})
        assert len(mapped) == 3
        assert len(set(mapped.values())) == 1

    def test_distinct_endpoints_colliding_is_a_hard_error(self):
        """Two different endpoints must never silently share a directory."""
        rows = [row("mod", "GET", "/a/b"), row("mod", "GET", "/a-b")]
        with pytest.raises(SlugCollisionError) as excinfo:
            build_slug_map(rows, {})
        assert "mod_get_a_b" in str(excinfo.value)

    def test_over_length_is_a_hard_error_naming_every_offender(self):
        rows = [
            row("m", "GET", "/" + "x" * (MAX_SLUG_LENGTH + 10)),
            row("m", "GET", "/" + "y" * (MAX_SLUG_LENGTH + 20)),
        ]
        with pytest.raises(SlugTooLongError) as excinfo:
            build_slug_map(rows, {})
        message = str(excinfo.value)
        assert "2 slug(s) exceed" in message
        assert "Never truncate and never hash." in message

    def test_alias_is_the_documented_remedy_for_over_length(self):
        long_module = "a very long module name indeed"
        rows = [row(long_module, "DELETE", "/" + "z" * 60)]
        with pytest.raises(SlugTooLongError):
            build_slug_map(rows, {})
        build_slug_map(rows, {long_module: "m"})  # alias clears it


class TestRealCatalogue:
    """Guards the two properties the work order calls hard errors."""

    def test_live_catalogue_resolves_cleanly(self):
        from tests.global_contract.catalogue import build_catalogue
        from tests.global_contract.endpoint_slug import load_aliases

        apis = build_catalogue()["apis"]
        mapped = build_slug_map(apis, load_aliases())

        assert len(mapped) == len(apis)
        assert max(len(s) for s in mapped.values()) <= MAX_SLUG_LENGTH
        # 45 catalogue rows are 41 endpoints; the surplus are cases sharing one.
        assert len(set(mapped.values())) < len(apis)

"""The authoring surface must be a lossless inverse of the inventory.

This is the test that would have caught the Phase 3 blocker before it was hit. The
first YAML shape captured 15 of 18 columns and folded per-case content up to the
endpoint; both losses were invisible until the authority flip was attempted, because
nothing compared the two representations column by column.

Kept out of ``tests/global_contract/`` -- that directory is collected wholesale by the
runner, and a unit test inside it would change the very counts the phase gates on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

import importlib.util  # noqa: E402

# The generator is a script, not a package module, and its filename is not a valid
# identifier -- load it by path rather than renaming the file CI invokes.
_spec = importlib.util.spec_from_file_location(
    "generate_endpoint_yaml", ROOT / "scripts" / "generate-endpoint-yaml.py"
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


@pytest.fixture(scope="module")
def inventory() -> dict[str, dict[str, str]]:
    rows = json.loads((ROOT / "api-docs" / "API_File.json").read_text(encoding="utf-8"))
    return {r["API Identifier"]: r for r in rows}


@pytest.fixture(scope="module")
def documents() -> list[dict]:
    return gen.load_endpoint_documents()


class TestShape:
    def test_41_endpoints_45_cases(self, documents):
        assert len(documents) == 41
        assert sum(len(d["cases"]) for d in documents) == 45

    def test_endpoint_level_fields_cannot_differ_between_cases(self, documents):
        """If these differed, the cases would belong to different endpoints."""
        for doc in documents:
            for field in gen.ENDPOINT_LEVEL:
                values = {c.get(field) for c in doc["cases"]}
                assert values == {doc[field]}, f"{doc['slug']}: {field} differs"

    def test_multi_case_endpoints_keep_their_differences(self, documents):
        """The exact loss the first shape had: folding per-case content upward."""
        auth = next(d for d in documents if d["slug"] == "employee_auth_api_post_auth_token")
        assert len(auth["cases"]) == 3
        for field in ("subModule", "purpose"):
            assert len({c[field] for c in auth["cases"]}) == 3, f"{field} was folded"


class TestLosslessness:
    def test_every_inventory_column_survives(self, documents, inventory):
        """Column-by-column equality for all 45 rows. The real gate."""
        rebuilt = {r["API Identifier"]: r for r in gen.rows_from_endpoints()}
        assert set(rebuilt) == set(inventory)

        mismatches = []
        for ref, original in inventory.items():
            for column in gen.ALL_COLUMNS:
                want = str(original.get(column, "") or "")
                got = rebuilt[ref].get(column, "")
                if want != got:
                    mismatches.append(f"{ref}\n  column {column!r}\n  want {want!r}\n  got  {got!r}")
        assert not mismatches, "\n".join(mismatches[:5])

    def test_mapping_covers_exactly_eighteen_columns(self, inventory):
        columns = set()
        for row in inventory.values():
            columns |= set(row)
        assert len(columns) == 18
        assert gen.ALL_COLUMNS == columns

    def test_column_mapping_is_bijective(self):
        """No column may be written by two rules, or the inverse is ambiguous."""
        assert set(gen.SCALAR_COLUMNS) & set(gen.PAYLOAD_COLUMNS) == set()
        assert set(gen.SCALAR_COLUMNS) & set(gen.RULE_COLUMNS) == set()
        assert set(gen.PAYLOAD_COLUMNS) & set(gen.RULE_COLUMNS) == set()
        assert len(set(gen.PAYLOAD_COLUMNS.values())) == len(gen.PAYLOAD_COLUMNS)
        assert len(set(gen.RULE_COLUMNS.values())) == len(gen.RULE_COLUMNS)


class TestCanonicalRef:
    def test_byte_identical_to_the_catalogue(self, documents):
        from tests.global_contract.catalogue import build_catalogue

        catalogue = {a["ref"] for a in build_catalogue()["apis"]}
        found = {c["canonicalRef"] for d in documents for c in d["cases"]}
        assert found == catalogue

    def test_the_misspelling_is_preserved(self, documents):
        """attenedance-july2026 is contract-visible; the alias moves the slug only."""
        typos = [
            c["canonicalRef"]
            for d in documents
            for c in d["cases"]
            if "attenedance" in c["canonicalRef"]
        ]
        assert len(typos) == 7
        slugs = {d["slug"] for d in documents if any("attenedance" in c["canonicalRef"] for c in d["cases"])}
        assert all(s.startswith("weekoff_") for s in slugs)


class TestCaseRefScoping:
    """caseRef scopes a case file to one ref of an endpoint that carries several."""

    @staticmethod
    def _seed(tmp_path, monkeypatch, body: str, login: bool = False):
        """Create a case file under whichever root is being exercised.

        The two roots sit at different depths -- endpoint/<suite>/<endpoint>/ and
        the flat login/<endpoint>/ -- so both are patched and both are globbed.
        """
        if login:
            root = tmp_path / "login"
            case_dir = root / "employee_auth_api_POST_auth_token"
        else:
            root = tmp_path / "endpoint"
            case_dir = root / "some_suite" / "GET_api_thing"
        case_dir.mkdir(parents=True)
        (case_dir / "01_x.py").write_text(body, encoding="utf-8")
        monkeypatch.setattr(gen, "CASES_DIR", tmp_path / "endpoint")
        monkeypatch.setattr(gen, "CASES_LOGIN_DIR", tmp_path / "login")

    def test_valid_ref_accepted(self, tmp_path, monkeypatch, documents):
        ref = documents[0]["cases"][0]["canonicalRef"]
        self._seed(tmp_path, monkeypatch, f'caseRef = "{ref}"\n')
        assert gen.validate_case_files({ref}) == []

    def test_unknown_ref_is_an_error(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch, 'caseRef = "post|/nope|x|y"\n')
        problems = gen.validate_case_files({"post|/real|a|b"})
        assert len(problems) == 1 and "unknown caseRef" in problems[0]

    def test_omitting_caseRef_is_permitted(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch, '"""No scoping needed."""\n')
        assert gen.validate_case_files(set()) == []

    def test_login_root_is_also_scanned(self, tmp_path, monkeypatch):
        """The flat login root is one level shallower; a single glob would miss it."""
        self._seed(tmp_path, monkeypatch, 'caseRef = "post|/nope|x|y"\n', login=True)
        problems = gen.validate_case_files({"post|/real|a|b"})
        assert len(problems) == 1, "login cases must not be invisible to validation"


class TestCaseDirectories:
    """The tree shape: suite level, uppercase method, and the login collision."""

    def test_suite_uses_the_alias_never_the_raw_name(self):
        aliases = {"attenedance-july2026": "weekoff"}
        assert gen.suite_name("Attenedance-july2026", aliases) == "weekoff"
        assert gen.suite_name("Attendance Policy Master", {}) == "attendance_policy_master"

    def test_endpoint_dirname_keeps_method_uppercase(self):
        assert gen.endpoint_dirname("delete", "/api/x/{holidayTemplateId}") == (
            "DELETE_api_x_by_holidaytemplateid"
        )

    def test_login_endpoints_get_a_module_prefix_because_they_collide(self, documents):
        """Both auth endpoints are POST /auth/token, and the login root is flat."""
        docs = {d["slug"]: d for d in documents}
        dirs = gen.case_directories(docs, gen.load_aliases())
        emp = dirs["employee_auth_api_post_auth_token"]
        uat = dirs["login_auth_uat_api_post_auth_token"]
        assert emp != uat, "a flat login root would have collapsed these into one"
        assert emp.parent == gen.CASES_LOGIN_DIR and uat.parent == gen.CASES_LOGIN_DIR
        assert emp.name.startswith("employee_auth_api_")
        assert uat.name.startswith("login_auth_uat_api_")

    def test_the_third_auth_token_endpoint_stays_in_a_suite(self, documents):
        """module 'auth' shares the path but is not a login module."""
        docs = {d["slug"]: d for d in documents}
        dirs = gen.case_directories(docs, gen.load_aliases())
        assert dirs["auth_post_auth_token"].parent == gen.CASES_DIR / "auth"

    def test_every_endpoint_gets_a_distinct_directory(self, documents):
        docs = {d["slug"]: d for d in documents}
        dirs = gen.case_directories(docs, gen.load_aliases())
        assert len(dirs) == 41
        assert len(set(dirs.values())) == 41

    def test_paths_stay_under_the_ceiling(self, documents):
        docs = {d["slug"]: d for d in documents}
        dirs = gen.case_directories(docs, gen.load_aliases())
        worst = max(len(str(d)) for d in dirs.values()) + 1 + gen.CASE_FILENAME_BUDGET
        assert worst <= gen.MAX_PATH_LENGTH

    def test_an_unresolvable_collision_is_a_hard_error(self, monkeypatch):
        """Same suite, same method+path -- the module prefix cannot separate them."""
        docs = {
            "a": {"slug": "a", "module": "m", "method": "GET", "endpointPath": "/x"},
            "b": {"slug": "b", "module": "m", "method": "GET", "endpointPath": "/x"},
        }
        with pytest.raises(gen.CaseDirectoryError, match="share a case directory"):
            gen.case_directories(docs, {})

    def test_over_long_path_is_a_hard_error(self, monkeypatch):
        monkeypatch.setattr(gen, "MAX_PATH_LENGTH", 60)
        docs = {"a": {"slug": "a", "module": "m", "method": "GET", "endpointPath": "/" + "z" * 80}}
        with pytest.raises(gen.CaseDirectoryError, match="exceed 60 characters"):
            gen.case_directories(docs, {})

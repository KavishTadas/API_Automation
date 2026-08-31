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
    """caseRef lets co-located case files be scoped to one ref of a shared endpoint."""

    def test_valid_ref_accepted(self, tmp_path, monkeypatch, documents):
        ref = documents[0]["cases"][0]["canonicalRef"]
        case_dir = tmp_path / "some_endpoint"
        case_dir.mkdir()
        (case_dir / "01_x.py").write_text(f'caseRef = "{ref}"\n', encoding="utf-8")
        monkeypatch.setattr(gen, "CASES_DIR", tmp_path)
        assert gen.validate_case_files({ref}) == []

    def test_unknown_ref_is_an_error(self, tmp_path, monkeypatch):
        case_dir = tmp_path / "some_endpoint"
        case_dir.mkdir()
        (case_dir / "01_x.py").write_text('caseRef = "post|/nope|x|y"\n', encoding="utf-8")
        monkeypatch.setattr(gen, "CASES_DIR", tmp_path)
        problems = gen.validate_case_files({"post|/real|a|b"})
        assert len(problems) == 1 and "unknown caseRef" in problems[0]

    def test_omitting_caseRef_is_permitted(self, tmp_path, monkeypatch):
        case_dir = tmp_path / "some_endpoint"
        case_dir.mkdir()
        (case_dir / "01_x.py").write_text('"""No scoping needed."""\n', encoding="utf-8")
        monkeypatch.setattr(gen, "CASES_DIR", tmp_path)
        assert gen.validate_case_files(set()) == []

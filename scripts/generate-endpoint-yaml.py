"""Materialise the authoring surface, and be the inverse of the inventory.

`api-endpoints/*.yaml` is the source of truth from Phase 3 onward, which imposes a
hard requirement this script exists to meet: **the YAML must carry every column the
inventory carries, losslessly.** The first cut did not, and the gap was only visible
once the flip was attempted -- it captured 15 of 18 columns, and the three it dropped
(`Request Parameters`, `Request Body Schema`, `Response (example/200)`) are read by
`metadata_resolver`, `curl_adapter` and the anonymous-access check. It also folded
per-case content up to the endpoint, which silently discarded the differing purposes
and payloads of the three multi-case endpoints.

Shape
-----
41 files, 45 cases. A file is an **endpoint**; a `cases[]` entry is one inventory row.
Endpoint-level fields are those that genuinely cannot differ between cases on the same
endpoint (module, method, path). Everything else lives per case, because on
``POST /auth/token`` it demonstrably does differ.

The column mapping is **bijective** -- exactly 18 columns in, 18 out, no dedup and no
merging -- so ``case_to_row`` is a true inverse and the round-trip is verifiable
rather than assumed. That property is tested, not asserted: see
``tests/unit/test_endpoint_yaml_roundtrip.py``.

Usage::

    python scripts/generate-endpoint-yaml.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from tests.global_contract.catalogue import build_catalogue  # noqa: E402
from tests.global_contract.endpoint_slug import build_slug_map, load_aliases  # noqa: E402

API_FILE = ROOT_DIR / "api-docs" / "API_File.json"
OPENAPI = ROOT_DIR / "openapi" / "openapi.yaml"
ENDPOINT_DIR = ROOT_DIR / "api-endpoints"
CASES_DIR = ROOT_DIR / "test-cases" / "endpoint"
REF_MAP = ROOT_DIR / "api-docs" / "ref-to-slug.json"

X_FIELDS = (
    "x-sla-ms",
    "x-required-role",
    "x-idempotent",
    "x-max-payload-bytes",
    "x-paginated",
)

#: Inventory column -> case field. Nine columns map to a plain scalar field.
SCALAR_COLUMNS = OrderedDict(
    (
        ("Sr. No", "apiId"),
        ("Module Name", "module"),
        ("Sub-Module Name", "subModule"),
        ("Access", "access"),
        ("Functional Purpose", "purpose"),
        ("Base URL", "basePath"),
        ("Endpoint / Path", "endpointPath"),
        ("HTTP Method", "method"),
        ("Request Parameters", "requestParameters"),
        ("Request Body Schema", "requestBodySchema"),
        ("Response (example/200)", "responseExample"),
        ("Owner / Developer", "owner"),
        ("API Identifier", "canonicalRef"),
    )
)

#: Three columns become samplePayloads[], keyed bijectively by payloadType.
PAYLOAD_COLUMNS = OrderedDict(
    (
        ("Request Body", "Request Body"),
        ("Example Request Payload", "Example Request Payload"),
        ("Example Response Payload", "Example Response Payload"),
    )
)

#: Two columns become rules[], keyed bijectively by category.
RULE_COLUMNS = OrderedDict(
    (
        ("Dependent APIs / Services", "Dependency"),
        ("Comments", "Non-Functional"),
    )
)

#: Endpoint-level fields. These cannot differ between cases on one endpoint -- the
#: slug is derived from module+method+path, so a difference would be a different
#: endpoint by definition.
ENDPOINT_LEVEL = ("module", "method", "endpointPath")

ALL_COLUMNS = set(SCALAR_COLUMNS) | set(PAYLOAD_COLUMNS) | set(RULE_COLUMNS)


class _Literal(str):
    """A string YAML should emit as a block scalar."""


yaml.add_representer(
    _Literal,
    lambda d, v: d.represent_scalar("tag:yaml.org,2002:str", str(v), style="|"),
)
yaml.add_representer(
    OrderedDict,
    lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v.items()),
)


def _emit(value: str) -> Any:
    """Preserve the column verbatim; only the YAML *style* varies."""
    if value is None or value == "":
        return None
    return _Literal(value) if "\n" in value else value


def _read(value: Any) -> str:
    """Inverse of :func:`_emit`. Absent and empty both mean the empty column."""
    return "" if value is None else str(value)


def load_openapi_extensions() -> dict[tuple[str, str], dict[str, Any]]:
    """Declared ``x-`` extensions only. Resolver defaults are never baked in."""
    if not OPENAPI.exists():
        return {}
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8")) or {}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for path, operations in (spec.get("paths") or {}).items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if isinstance(operation, dict):
                declared = {f: operation[f] for f in X_FIELDS if f in operation}
                if declared:
                    found[(method.upper(), path)] = declared
    return found


def row_to_case(row: dict[str, Any], api: dict[str, Any]) -> OrderedDict:
    """One inventory row -> one ``cases[]`` entry. Carries all 18 columns."""
    case = OrderedDict()
    for column, field in SCALAR_COLUMNS.items():
        case[field] = _emit(str(row.get(column, "") or ""))

    # canonicalRef must survive byte-identical. The inventory's API Identifier and
    # the catalogue ref are the same string; prefer the catalogue's, since that is
    # what every downstream consumer keys on.
    case["canonicalRef"] = api["ref"]

    payloads = []
    for column, payload_type in PAYLOAD_COLUMNS.items():
        raw = str(row.get(column, "") or "")
        if raw:
            entry = OrderedDict()
            entry["payloadType"] = payload_type
            entry["json"] = _emit(raw)
            payloads.append(entry)
    case["samplePayloads"] = payloads

    rules = []
    for column, category in RULE_COLUMNS.items():
        raw = str(row.get(column, "") or "")
        if raw:
            entry = OrderedDict()
            entry["category"] = category
            entry["description"] = _emit(raw)
            rules.append(entry)
    case["rules"] = rules

    # Provenance, from the catalogue rather than the inventory.
    case["assertionState"] = api.get("assertionState")
    case["sourceType"] = api.get("sourceType")
    case["sourceCollection"] = api.get("sourceCollection")
    return case


def case_to_row(case: dict[str, Any]) -> dict[str, str]:
    """Exact inverse of :func:`row_to_case`, reconstructing the 18-column row."""
    row: dict[str, str] = {}
    for column, field in SCALAR_COLUMNS.items():
        row[column] = _read(case.get(field))

    by_type = {
        p.get("payloadType"): _read(p.get("json"))
        for p in (case.get("samplePayloads") or [])
    }
    for column, payload_type in PAYLOAD_COLUMNS.items():
        row[column] = by_type.get(payload_type, "")

    by_category = {
        r.get("category"): _read(r.get("description"))
        for r in (case.get("rules") or [])
    }
    for column, category in RULE_COLUMNS.items():
        row[column] = by_category.get(category, "")

    row["API Identifier"] = _read(case.get("canonicalRef"))
    return row


def load_endpoint_documents() -> list[OrderedDict]:
    """Read the authoring surface. This is what the flipped generator consumes."""
    documents = []
    for path in sorted(ENDPOINT_DIR.glob("*.yaml")):
        if path.name == "module-aliases.yaml":
            continue
        documents.append(yaml.safe_load(path.read_text(encoding="utf-8")))
    return documents


def rows_from_endpoints() -> list[dict[str, str]]:
    """Every case in the tree, back as inventory rows, in stable apiId order."""
    rows = [case_to_row(c) for doc in load_endpoint_documents() for c in doc["cases"]]
    rows.sort(key=lambda r: int(r["Sr. No"] or 0))
    return rows


def build_documents() -> tuple[dict[str, OrderedDict], dict[str, str]]:
    catalogue = build_catalogue()
    apis = catalogue["apis"]
    ref_to_slug = build_slug_map(apis, load_aliases())  # raises on collision/length
    inventory = {
        str(r.get("API Identifier", "")): r
        for r in json.loads(API_FILE.read_text(encoding="utf-8"))
    }
    extensions = load_openapi_extensions()

    documents: dict[str, OrderedDict] = {}
    for api in apis:
        slug = ref_to_slug[api["ref"]]
        case = row_to_case(inventory.get(api["ref"], {}), api)

        if slug in documents:
            documents[slug]["cases"].append(case)
            continue

        doc = OrderedDict()
        doc["slug"] = slug
        doc["module"] = api.get("module")
        doc["method"] = api.get("method")
        doc["endpointPath"] = api.get("path")
        doc["environments"] = list(catalogue.get("environments") or [])
        doc["version"] = None
        # Alias only, never a value. Bound to an endpoint by the run manifest.
        doc["credentialAlias"] = None
        doc["metadata"] = (
            OrderedDict(sorted(extensions.get((api["method"], api["path"]), {}).items()))
            or None
        )
        doc["cases"] = [case]
        documents[slug] = doc

    return documents, ref_to_slug


HEADER = """# AUTHORED -- this file is the source of truth for this endpoint.
#
# A `cases[]` entry is one test case and carries all 18 inventory columns.
# Content lives per case, not per endpoint: on POST /auth/token the purpose,
# request payload and response differ across tc01/tc02/tc03, and folding them
# up to the endpoint silently discarded two of the three.
#
# canonicalRef is contract-visible. Do not normalise it, do not fix its
# spelling -- the harness, run manifest and result document all key on it.
"""

CASE_README = """# {slug}

`{method} {path}`

Endpoint-specific test cases go here: **one Python file per case**, named
`<NN>_<case_title>.py`. Hand-authored, never written by a tool.

## Scoping a case to one ref with `caseRef`

This endpoint carries **{n_cases}** case(s), so a file here must say which one it
tests. Declare it at module level:

```python
caseRef = "{example_ref}"
```

`caseRef` must be one of the `canonicalRef` values below, byte-identical. Omit it
only where the endpoint has a single case and the file applies to all of it.
Co-located files with different `caseRef` values are independent: each is scoped to
its own ref and runs only when that ref is in the manifest.

## Cases on this endpoint

{coverage}

## Adding a case

Number it after the highest existing file. State in the docstring what it asserts and
which result state it emits on failure. The 22 global checks already run against this
endpoint on every run -- add a case here only for behaviour specific to this endpoint.
"""


def render_case_readme(doc: dict[str, Any]) -> str:
    lines = []
    for case in doc["cases"]:
        source = case.get("sourceCollection") or case.get("sourceType") or "unknown"
        lines.append(
            f"- **{case['subModule']}**\n"
            f"  - `caseRef`: `{case['canonicalRef']}`\n"
            f"  - assertion state: `{case['assertionState']}` — currently in `{source}`"
        )
    return CASE_README.format(
        slug=doc["slug"],
        method=doc["method"],
        path=doc["endpointPath"],
        n_cases=len(doc["cases"]),
        example_ref=doc["cases"][0]["canonicalRef"],
        coverage="\n".join(lines),
    )


CASE_REF_PATTERN = __import__("re").compile(
    r"^caseRef\s*=\s*[\"'](?P<ref>[^\"']+)[\"']", __import__("re").M
)


def validate_case_files(known_refs: set[str]) -> list[str]:
    """Every declared ``caseRef`` must name a real ref, byte-identical.

    Endpoint directories can hold cases for several refs -- ``POST /auth/token``
    carries three. A file says which one it scopes to by declaring ``caseRef`` at
    module level. A typo there would silently scope the case to nothing and the
    case would look like it ran, so this is an error rather than a warning.
    """
    problems: list[str] = []
    for path in sorted(CASES_DIR.glob("*/*.py")):
        match = CASE_REF_PATTERN.search(path.read_text(encoding="utf-8"))
        if match is None:
            continue  # permitted: single-case endpoints need no scoping
        ref = match.group("ref")
        if ref not in known_refs:
            # relative_to raises for a path outside the repo; reporting a bad
            # caseRef must never itself crash, so fall back to the full path.
            try:
                shown = path.relative_to(ROOT_DIR)
            except ValueError:
                shown = path
            problems.append(f"{shown}\n    unknown caseRef: {ref!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate-endpoint-yaml")
    parser.add_argument("--check", action="store_true", help="report without writing")
    args = parser.parse_args(argv)

    try:
        documents, ref_to_slug = build_documents()
    except Exception as error:
        print(f"GENERATION FAILED: {type(error).__name__}", file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 2

    n_cases = sum(len(d["cases"]) for d in documents.values())

    bad_refs = validate_case_files(set(ref_to_slug))
    if bad_refs:
        print("INVALID caseRef DECLARATIONS:", file=sys.stderr)
        for problem in bad_refs:
            print(f"  {problem}", file=sys.stderr)
        return 3

    if args.check:
        print(f"{len(ref_to_slug)} refs -> {len(documents)} endpoints, {n_cases} cases")
        print(f"longest slug: {max(map(len, documents))} chars")
        print(f"case files with a valid caseRef: {len(list(CASES_DIR.glob('*/*.py')))}")
        return 0

    ENDPOINT_DIR.mkdir(parents=True, exist_ok=True)
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    for slug, doc in sorted(documents.items()):
        (ENDPOINT_DIR / f"{slug}.yaml").write_text(
            HEADER + yaml.dump(doc, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        case_dir = CASES_DIR / slug
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "README.md").write_text(render_case_readme(doc), encoding="utf-8")

    REF_MAP.write_text(
        json.dumps(
            {
                "generatedBy": "scripts/generate-endpoint-yaml.py",
                "refCount": len(ref_to_slug),
                "endpointCount": len(documents),
                "caseCount": n_cases,
                "refToSlug": OrderedDict(sorted(ref_to_slug.items())),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"{len(ref_to_slug)} refs -> {len(documents)} endpoints, {n_cases} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

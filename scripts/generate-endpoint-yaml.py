"""Materialise the authoring surface from the current sources. Read-only upstream.

Phase 2 of the authoring-surface work order. This script *writes* the new tree
and *reads* everything else. Nothing in the suite reads the tree back yet, so a
run before and after must be identical -- that is the phase's whole verification.

Sources, in order of authority:

* ``tests.global_contract.catalogue`` -- endpoint identity: ref, module,
  subModule, method, path, owner, sourceType, sourceCollection.
* ``api-docs/API_File.json`` -- the 18-column inventory: purpose, base URL,
  sample payloads, dependencies, comments.
* ``openapi/openapi.yaml`` -- the ``x-`` contract extensions, emitted **only
  where declared**. Resolver defaults (``DEFAULT_SLA_MS = 700``,
  ``DEFAULT_MAX_PAYLOAD_BYTES = 1 MiB``) are deliberately NOT baked in: writing
  a global fallback into 41 files would turn one default into 41 per-endpoint
  declarations that nobody chose, and a later change to the default would
  silently disagree with every file.

45 catalogue rows resolve to 41 endpoints; refs that share an endpoint become
entries in that endpoint's ``testCases`` list, each carrying its own
byte-identical ``canonicalRef``.

Usage::

    python scripts/generate-endpoint-yaml.py [--check]

``--check`` reports what would change without writing, for CI.
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
from tests.global_contract.endpoint_slug import (  # noqa: E402
    build_slug_map,
    load_aliases,
    slugify,
)

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

#: Sample payload columns, mapped to the template's payloadType vocabulary.
PAYLOAD_COLUMNS = (
    ("Example Request Payload", "Request Body", None),
    ("Example Response Payload", "Success Response", 200),
    ("Request Body", "Request Body", None),
)

#: Free-prose columns that become `rules[]` entries, with their category.
RULE_COLUMNS = (
    ("Functional Purpose", "Business Rule"),
    ("Dependent APIs / Services", "Dependency"),
    ("Comments", "Non-Functional"),
)


class _Literal(str):
    """A string YAML should emit as a block scalar."""


def _literal_representer(dumper: yaml.Dumper, data: _Literal) -> Any:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


def _ordered_representer(dumper: yaml.Dumper, data: OrderedDict) -> Any:
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())


yaml.add_representer(_Literal, _literal_representer)
yaml.add_representer(OrderedDict, _ordered_representer)


def _block(value: str | None) -> Any:
    """Multi-line prose as a block scalar; short strings stay inline."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _Literal(text + "\n") if "\n" in text else text


def load_openapi_extensions() -> dict[tuple[str, str], dict[str, Any]]:
    """Declared ``x-`` extensions, keyed by (METHOD, path). Declared only."""
    if not OPENAPI.exists():
        return {}
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8")) or {}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for path, operations in (spec.get("paths") or {}).items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            declared = {f: operation[f] for f in X_FIELDS if f in operation}
            if declared:
                found[(method.upper(), path)] = declared
    return found


def load_inventory() -> dict[str, dict[str, Any]]:
    """The 18-column inventory, keyed by its ``API Identifier`` (== catalogue ref)."""
    if not API_FILE.exists():
        return {}
    rows = json.loads(API_FILE.read_text(encoding="utf-8"))
    return {str(r.get("API Identifier", "")): r for r in rows}


def _samples(row: dict[str, Any]) -> list[OrderedDict]:
    seen: set[tuple[str, str]] = set()
    out: list[OrderedDict] = []
    for column, payload_type, status in PAYLOAD_COLUMNS:
        raw = (row.get(column) or "").strip()
        if not raw:
            continue
        key = (payload_type, raw)
        if key in seen:
            continue
        seen.add(key)
        entry = OrderedDict()
        entry["payloadType"] = payload_type
        entry["responseStatus"] = status
        entry["json"] = _block(raw)
        out.append(entry)
    return out


def _rules(row: dict[str, Any]) -> list[OrderedDict]:
    out: list[OrderedDict] = []
    for column, category in RULE_COLUMNS:
        text = (row.get(column) or "").strip()
        if not text:
            continue
        entry = OrderedDict()
        entry["category"] = category
        entry["description"] = _block(text)
        out.append(entry)
    return out


def build_documents() -> tuple[dict[str, OrderedDict], dict[str, str]]:
    """One document per endpoint, plus the ref -> slug map over all 45 rows."""
    catalogue = build_catalogue()
    apis = catalogue["apis"]
    aliases = load_aliases()
    ref_to_slug = build_slug_map(apis, aliases)  # raises on collision / length
    inventory = load_inventory()
    extensions = load_openapi_extensions()

    documents: dict[str, OrderedDict] = {}

    for api in apis:
        slug = ref_to_slug[api["ref"]]
        row = inventory.get(api["ref"], {})

        case = OrderedDict()
        # Byte-identical to catalogue output. Never normalised, never re-cased.
        case["canonicalRef"] = api["ref"]
        case["name"] = api.get("subModule") or api.get("name")
        case["assertionState"] = api.get("assertionState")
        case["sourceType"] = api.get("sourceType")
        case["sourceCollection"] = api.get("sourceCollection")

        existing = documents.get(slug)
        if existing is not None:
            existing["testCases"].append(case)
            continue

        doc = OrderedDict()
        doc["slug"] = slug
        doc["apiId"] = row.get("Sr. No") or api.get("displayId")
        doc["name"] = api.get("name")
        doc["module"] = api.get("module")
        doc["subModule"] = api.get("subModule")
        doc["purpose"] = _block(row.get("Functional Purpose"))
        doc["owner"] = api.get("owner")

        doc["method"] = api.get("method")
        doc["basePath"] = row.get("Base URL") or None
        doc["endpointPath"] = api.get("path")
        doc["authType"] = row.get("Access") or None
        doc["environments"] = list(catalogue.get("environments") or [])
        doc["version"] = None

        # The primary case's ref. Every ref, including this one, also appears
        # verbatim under testCases[].canonicalRef.
        doc["canonicalRef"] = api["ref"]

        # Alias only, never a value. The catalogue registers aliases globally
        # (ATTENDANCE_SVC_UAT_01, LEAVE_SVC_UAT_01) and the run manifest binds
        # one to an endpoint at run time, so there is nothing per-endpoint to
        # record here yet.
        doc["credentialAlias"] = None

        doc["metadata"] = (
            OrderedDict(sorted(extensions.get((api["method"], api["path"]), {}).items()))
            or None
        )
        doc["samplePayloads"] = _samples(row)
        doc["rules"] = _rules(row)
        doc["testCases"] = [case]

        documents[slug] = doc

    return documents, ref_to_slug


CASE_README = """# {slug}

`{method} {path}`

Endpoint-specific test cases go in this directory: **one Python file per case**,
named `<NN>_<case_title>.py`. Written by hand, never by a tool.

## What covers this endpoint today

{coverage}

## Adding a case

Number it after the highest existing file. State in the docstring what it
asserts and which result state it emits on failure. The 22 global checks already
run against this endpoint on every run -- do not restate them here; add a case
only for behaviour specific to this endpoint.
"""


def render_case_readme(doc: OrderedDict) -> str:
    lines = []
    for case in doc["testCases"]:
        source = case.get("sourceCollection") or case.get("sourceType") or "unknown"
        lines.append(
            f"- **{case['name']}** — `{case['assertionState']}` — "
            f"currently lives in `{source}`"
        )
    lines.append(
        "\nGenerated contract coverage: `tests/auto_generated/` "
        "(disposable — regenerated, never edited)."
    )
    return CASE_README.format(
        slug=doc["slug"],
        method=doc["method"],
        path=doc["endpointPath"],
        coverage="\n".join(lines),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate-endpoint-yaml")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what would change without writing anything",
    )
    args = parser.parse_args(argv)

    try:
        documents, ref_to_slug = build_documents()
    except Exception as error:  # collisions and over-length slugs land here
        print(f"GENERATION FAILED: {type(error).__name__}", file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 2

    if args.check:
        print(f"{len(ref_to_slug)} refs -> {len(documents)} endpoints")
        longest = max(documents, key=len)
        print(f"longest slug: {len(longest)} chars  {longest}")
        return 0

    ENDPOINT_DIR.mkdir(parents=True, exist_ok=True)
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    for slug, doc in sorted(documents.items()):
        (ENDPOINT_DIR / f"{slug}.yaml").write_text(
            "# GENERATED by scripts/generate-endpoint-yaml.py for Phase 2.\n"
            "# From Phase 3 this file becomes the source of truth and is edited\n"
            "# by hand. canonicalRef is contract-visible -- do not normalise it.\n"
            + yaml.dump(doc, sort_keys=False, allow_unicode=True, width=100),
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
                "refToSlug": OrderedDict(sorted(ref_to_slug.items())),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"{len(ref_to_slug)} refs -> {len(documents)} endpoint definitions")
    print(f"wrote {ENDPOINT_DIR.relative_to(ROOT_DIR)}/*.yaml")
    print(f"wrote {CASES_DIR.relative_to(ROOT_DIR)}/<slug>/README.md")
    print(f"wrote {REF_MAP.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

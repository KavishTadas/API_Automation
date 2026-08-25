"""The discovery catalogue: what this suite would test, without running it.

The platform must show a QA engineer every test case that will execute *before*
a run starts. Newman only reveals ``pm.test()`` names at execution time, and the
global tier's titles live in ``@allure.title`` decorators — neither is reachable
without publishing them. This module publishes them.

**Zero HTTP requests.** Everything here is read from files already in the repo:
the generated inventory, the Newman collections, the global tier's own source,
and the registered environment keys. Nothing is fetched, and nothing is written
back.

**Byte-stable.** No timestamps, no ordering that depends on dict iteration, no
absolute paths. Regenerating with unchanged inputs produces an identical file,
so a diff means something actually changed.

Four sections
-------------
``apis``              one entry per inventory row, keyed by the engine-resolvable ``ref``
``testCases``         ``global`` (the shared set, emitted once) and ``apiSpecific``
``environments``      derived from registered ``<MODULE>_BASE_URL_<ENV>`` keys
``credentialAliases`` alias **labels** only — never a value, a length, or a masked form

Test identity
-------------
See :func:`global_test_id`, :func:`generated_test_id` and :func:`newman_test_id`.
The platform prototype currently joins catalogue entries to results with
``assertions[index % assertions.length]``; these IDs are what replaces that.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from tests.global_contract.metadata_resolver import (
    ROOT_DIR,
    ApiDefinition,
    MetadataResolver,
    get_resolver,
)
from tests.global_contract.run_manifest import (
    normalize_environment,
    registered_environments_from,
)


__all__ = [
    "ApplicabilityState",
    "GlobalTest",
    "GLOBAL_TEST_CATEGORIES",
    "build_catalogue",
    "generated_test_id",
    "global_result_id",
    "global_test_id",
    "global_tests",
    "newman_test_id",
    "resolve_applicability",
    "write_catalogue",
]


COLLECTIONS_DIR = ROOT_DIR / "collections"
GLOBAL_TIER_SOURCE = Path(__file__).with_name("test_global_api_contract.py")
GENERATED_TESTS_DIR = ROOT_DIR / "tests" / "auto_generated"

CATALOGUE_VERSION = "1.0"

#: Category per global test. Sprint 4 groups results by this.
GLOBAL_TEST_CATEGORIES = {
    "test_status_code_matches_spec": "functional",
    "test_response_matches_full_schema": "schema",
    "test_no_credential_leakage_in_response": "security",
    "test_response_time_within_sla": "performance",
    "test_idempotent_get_returns_stable_result": "functional",
    "test_small_burst_does_not_trigger_immediate_blocking": "resilience",
    "test_request_payload_size_enforcement": "resilience",
    "test_401_without_valid_token": "security",
    "test_404_for_unknown_route": "functional",
    "test_content_type_negotiation": "schema",
    "test_cors_preflight": "security",
    "test_special_characters_in_input": "security",
}

#: Tests that measure a host/gateway property rather than an endpoint property.
#: Sprint 2 runs these once per distinct host and references the result from the
#: other APIs on that host; applicability has to say the same thing.
HOST_LEVEL_TESTS = frozenset(
    {
        "test_small_burst_does_not_trigger_immediate_blocking",
        "test_request_payload_size_enforcement",
    }
)


class ApplicabilityState:
    """What the catalogue can say about a test before anything runs."""

    PLANNED = "PLANNED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class GlobalTest:
    """One member of the shared global test set."""

    id: str
    function: str
    title: str
    category: str
    host_level: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "scope": "GLOBAL",
            "tier": "global_contract",
            "category": self.category,
            "hostLevel": self.host_level,
        }


# ---------------------------------------------------------------------------
# Test identity
# ---------------------------------------------------------------------------
# All three schemes are deterministic and contain no run-specific data. Two of
# them are derived from code identifiers and survive any title change; the
# Newman one is title-derived, and that is a deliberate, documented trade-off —
# see newman_test_id().


def global_test_id(function_name: str) -> str:
    """ID for a global test. Derived from the function name, never the title.

    Rewording an ``@allure.title`` changes what the platform displays and leaves
    the ID — and therefore the result history — untouched.
    """
    return f"global_contract::{function_name}"


def global_result_id(test_id: str, api_ref: str) -> str:
    """The per-API result ID a global test produces for one API.

    The global set is published once, but it executes once per selected API, so
    a result is keyed by both. Sprint 4's emitter joins on this.
    """
    return f"{test_id}::{api_ref}"


def generated_test_id(api_ref: str, check: str) -> str:
    """ID for a generated-tier check. Derived from the check name, not the title."""
    return f"generated::{api_ref}::{check}"


def newman_test_id(api_ref: str, assertion_name: str, ordinal: int = 0) -> str:
    """ID for one Newman assertion.

    **Title-derived, deliberately.** A Postman assertion has no identity of its
    own: not an id, not a stable position. Newman reports results by assertion
    *name*, so a name-derived ID is the only thing that can actually join a
    catalogue entry to a result. The alternative — positional indexing — is what
    the platform prototype does today with ``assertions[index % length]``, and
    it silently mismatches the moment anyone reorders a collection.

    Consequence, stated plainly: **renaming a ``pm.test()`` string changes the
    ID.** The renamed assertion appears as a new test case and the old one
    disappears; its history does not follow. Reordering assertions is safe,
    which is the more common edit.

    ``ordinal`` disambiguates two assertions in one request whose names slugify
    identically; it is assigned in sheet order and is stable.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(assertion_name).lower()).strip("-") or "assertion"
    suffix = f"-{ordinal + 1}" if ordinal else ""
    return f"newman::{api_ref}::{slug}{suffix}"


# ---------------------------------------------------------------------------
# Global test set (T3a) — published once, not duplicated under every API
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def global_tests() -> tuple[GlobalTest, ...]:
    """The twelve global checks, with titles read from their decorators.

    Parsed statically out of the tier's source rather than imported, so building
    a catalogue cannot trigger collection, fixtures, or any other side effect.
    """
    tree = ast.parse(GLOBAL_TIER_SOURCE.read_text(encoding="utf-8"))
    found: list[GlobalTest] = []

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue

        title = ""
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "title"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                title = str(decorator.args[0].value)
                break

        # The decorator carries a per-parameter suffix for the run report; the
        # shared set describes the check itself, so the suffix comes off.
        title = re.sub(r"\s*[—-]\s*\{param_id\}\s*$", "", title).strip()
        if not title:
            title = node.name.removeprefix("test_").replace("_", " ").capitalize()

        found.append(
            GlobalTest(
                id=global_test_id(node.name),
                function=node.name,
                title=title,
                category=GLOBAL_TEST_CATEGORIES.get(node.name, "functional"),
                host_level=node.name in HOST_LEVEL_TESTS,
            )
        )

    return tuple(sorted(found, key=lambda t: t.id))


# ---------------------------------------------------------------------------
# Applicability (T3b) — computable with zero HTTP requests
# ---------------------------------------------------------------------------


def _not_applicable(reason: str) -> dict[str, str]:
    return {"state": ApplicabilityState.NOT_APPLICABLE, "reason": reason}


_PLANNED = {"state": ApplicabilityState.PLANNED, "reason": ""}


def resolve_applicability(
    method: str,
    path: str,
    *,
    resolver: MetadataResolver | None = None,
    definition: ApiDefinition | None = None,
    environment: str = "",
    cors_enabled: bool = False,
    is_host_representative: bool = True,
    host: str = "",
    api_row_present: bool | None = None,
) -> dict[str, dict[str, str]]:
    """Decide, statically, which global tests will run for one API.

    Every gate below reads its metadata from
    :mod:`~tests.global_contract.metadata_resolver` — the same precedence chain
    the tier itself resolves through at run time — so the answer cannot drift
    from what actually happens. No HTTP request is made.

    An uploaded API is not in the catalogue (under DR-2 the platform holds its
    definition), so pass ``definition`` to have it registered for the duration
    of this call.
    """
    resolver = resolver or get_resolver()
    if definition is not None:
        resolver.register_definition(definition)
        method, path = definition.method, definition.path

    metadata = resolver.resolve(method, path, environment=environment)
    has_row = (
        metadata.api_row is not None if api_row_present is None else api_row_present
    )

    verdicts: dict[str, dict[str, str]] = {}

    def record(function: str, verdict: dict[str, str]) -> None:
        verdicts[global_test_id(function)] = verdict

    if not has_row:
        # Nothing can be requested, so nothing can be checked.
        reason = f"no request row for {method} {path}"
        for test in global_tests():
            record(test.function, _not_applicable(reason))
        return verdicts

    no_statuses = not metadata.documented_status_codes
    has_body = resolver.has_request_body(method, path)
    has_body_sample = resolver.request_body_sample(method, path) is not None
    has_content_types = any(metadata.documented_content_types.values())

    record(
        "test_status_code_matches_spec",
        _not_applicable("expected status not declared") if no_statuses else _PLANNED,
    )
    record("test_response_matches_full_schema", _PLANNED)
    record("test_no_credential_leakage_in_response", _PLANNED)
    record(
        "test_response_time_within_sla",
        _PLANNED if metadata.sla_ms is not None else _not_applicable("no SLA target"),
    )
    record(
        "test_idempotent_get_returns_stable_result",
        _PLANNED
        if metadata.idempotent is True
        else _not_applicable("not declared idempotent, so a repeat is not safe to send"),
    )
    record("test_404_for_unknown_route", _PLANNED)
    record(
        "test_401_without_valid_token",
        _PLANNED
        if metadata.requires_bearer_auth
        else _not_applicable("operation is not secured, so there is no token state to reject"),
    )
    record(
        "test_content_type_negotiation",
        _PLANNED if has_content_types else _not_applicable("no content type declared"),
    )
    record(
        "test_cors_preflight",
        _PLANNED
        if cors_enabled
        else _not_applicable("CORS preflight is opt-in and currently disabled"),
    )
    record(
        "test_special_characters_in_input",
        _PLANNED
        if has_body_sample
        else _not_applicable("no request body to substitute Unicode into"),
    )

    # Host-level probes: PLANNED only for the representative case, matching the
    # probe/result split the tier uses. Every other API on the host still gets a
    # verdict, pointing at where the measurement is reported.
    host_note = f"host-level probe for {host or 'this host'} is reported against the host's representative API"
    for function in sorted(HOST_LEVEL_TESTS):
        if not host:
            record(function, _not_applicable("no resolvable host to probe"))
        elif not is_host_representative:
            record(function, _not_applicable(host_note))
        elif function == "test_request_payload_size_enforcement":
            if metadata.max_payload_bytes is None:
                record(function, _not_applicable("no payload ceiling to exercise"))
            elif not has_body:
                record(function, _not_applicable("takes no request body to oversize"))
            else:
                record(function, _PLANNED)
        else:
            record(function, _PLANNED)

    return verdicts


# ---------------------------------------------------------------------------
# Newman assertions and assertionState (T4)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _collection_assertion_index() -> dict[tuple[str, str], bool | None]:
    """Map ``(collection, request name)`` -> whether that request carries assertions.

    Keyed on the request name rather than folder-plus-name: only some
    collections nest their requests in folders, and where they do the inventory
    records the *folder* as ``Module Name`` while a flat collection records the
    collection's own name there. The request name is the one field that means
    the same thing in both shapes.

    A name that appears twice in one collection with disagreeing assertion state
    maps to ``None`` — reported as ``unknown`` rather than guessed, since
    guessing here would mark an unasserted request as asserted.

    Presence only. The assertion *names* come from the inventory's
    ``Functional Purpose`` column, which ``scripts/generate-api-file.js`` already
    scrapes out of ``pm.test()`` — this deliberately does not re-scrape them.
    """
    index: dict[tuple[str, str], bool | None] = {}
    if not COLLECTIONS_DIR.exists():
        return index

    for collection_path in sorted(COLLECTIONS_DIR.rglob("*.json")):
        relative = collection_path.relative_to(ROOT_DIR).as_posix()
        try:
            document = json.loads(collection_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue

        def walk(items: Any) -> None:
            for item in items or ():
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", ""))
                if "item" in item:
                    walk(item.get("item"))
                elif "request" in item:
                    has_assertions = any(
                        event.get("listen") == "test"
                        and any(
                            str(line).strip()
                            for line in (event.get("script") or {}).get("exec") or ()
                        )
                        for event in item.get("event") or ()
                        if isinstance(event, dict)
                    )
                    key = (relative, name)
                    if key in index and index[key] != has_assertions:
                        index[key] = None
                    else:
                        index.setdefault(key, has_assertions)

        walk(document.get("item"))

    return index


def _source_collection(api_row: dict[str, Any]) -> str:
    match = re.search(r"Source:\s*([^;]+)", str(api_row.get("Comments", "")))
    return match.group(1).strip() if match else ""


def _row_has_assertions(api_row: dict[str, Any]) -> bool | None:
    """Whether this row's source request carries assertions. ``None`` if unknown."""
    source = _source_collection(api_row)
    if source.startswith("collections/"):
        return _collection_assertion_index().get(
            (source, str(api_row.get("Sub-Module Name", "")))
        )
    if source.endswith(".bru"):
        # A Bruno flow carries its assertions in a `tests { ... }` block. These
        # are not Newman requests, but they are asserted, and reporting them as
        # not-asserted would put them in the same bucket as the 37 Attendance
        # requests that genuinely have no assertions at all.
        return _bru_has_tests(ROOT_DIR / source)
    return None


@lru_cache(maxsize=None)
def _bru_has_tests(path: Path) -> bool | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"\btests\s*\{(.*)\}", text, re.DOTALL)
    return bool(match and re.search(r"\btest\s*\(", match.group(1)))


def _assertion_titles(api_row: dict[str, Any]) -> tuple[str, ...]:
    """The ``pm.test()`` names for this row, from the existing scraper's output.

    ``generate-api-file.js`` writes them into ``Functional Purpose``, joined with
    ``"; "``. Reading that column back is what "extend the existing scraper"
    means here — regenerating the inventory is not a safe no-op, and writing a
    second scraper is exactly what the brief forbids.
    """
    raw = str(api_row.get("Functional Purpose", "") or "").strip()
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(";") if part.strip())


# ---------------------------------------------------------------------------
# Catalogue assembly (T1)
# ---------------------------------------------------------------------------


def _api_entry(
    api_row: dict[str, Any],
    resolver: MetadataResolver,
) -> dict[str, Any]:
    ref = str(api_row.get("API Identifier", ""))
    asserted = _row_has_assertions(api_row)
    source = _source_collection(api_row)

    if source.startswith("collections/"):
        source_type = "newman"
    elif source.startswith("bruno/"):
        source_type = "bruno"
    else:
        source_type = "unknown"

    return {
        "ref": ref,
        # Template `API-001` style IDs are display labels only, scoped to whoever
        # filled in the sheet. The inventory has none, so this is null rather
        # than invented.
        "displayId": None,
        "name": str(api_row.get("Sub-Module Name", "")) or None,
        "module": str(api_row.get("Module Name", "")) or None,
        "subModule": str(api_row.get("Sub-Module Name", "")) or None,
        "method": str(api_row.get("HTTP Method", "")).upper(),
        "path": str(api_row.get("Endpoint / Path", "")),
        # Currently populated for 0 of 45 rows. Emitted as null rather than
        # back-filled with a guess.
        "owner": str(api_row.get("Owner / Developer", "")) or None,
        "sourceType": source_type,
        "sourceCollection": source or None,
        "assertionState": (
            "asserted" if asserted else "not-asserted" if asserted is False else "unknown"
        ),
    }


def _api_specific_tests(api_row: dict[str, Any]) -> list[dict[str, Any]]:
    """Newman and generated-tier cases for one API."""
    ref = str(api_row.get("API Identifier", ""))
    cases: list[dict[str, Any]] = []

    # Newman-tier cases only for requests Newman actually runs. A Bruno flow has
    # assertions of its own — so it is still `asserted` — but `run-newman.js`
    # never executes it, and publishing its checks under the newman tier would
    # promise results no run will produce.
    if _source_collection(api_row).startswith("collections/") and _row_has_assertions(
        api_row
    ):
        seen: dict[str, int] = {}
        for title in _assertion_titles(api_row):
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "assertion"
            ordinal = seen.get(slug, 0)
            seen[slug] = ordinal + 1
            cases.append(
                {
                    "id": newman_test_id(ref, title, ordinal),
                    "title": title,
                    "scope": "API_SPECIFIC",
                    "tier": "newman",
                    "category": "functional",
                    "apiRef": ref,
                }
            )

    # The generated tier emits exactly these two checks per inventory row.
    for check, title in (
        ("status_code", "returns the documented HTTP status"),
        ("response_schema", "response matches the documented schema"),
    ):
        label = str(api_row.get("Sub-Module Name", "")) or str(
            api_row.get("Endpoint / Path", "")
        )
        cases.append(
            {
                "id": generated_test_id(ref, check),
                "title": f"{label} — {title}",
                "scope": "API_SPECIFIC",
                "tier": "generated",
                "category": "functional" if check == "status_code" else "schema",
                "apiRef": ref,
            }
        )

    return cases


def build_catalogue(
    config: dict[str, str] | None = None,
    *,
    cors_enabled: bool = False,
    environment: str = "",
) -> dict[str, Any]:
    """Build the discovery catalogue. Makes no HTTP requests.

    ``config`` supplies the registered keys the environment and credential-alias
    sections are derived from; it defaults to the process environment merged
    over the repo's ``.env``.
    """
    resolver = get_resolver()
    config = _catalogue_config() if config is None else dict(config)
    # Canonicalised through the same helper the manifest validator uses, so
    # `uat` and `UAT` cannot produce two different catalogues.
    environment = normalize_environment(environment)
    api_rows = resolver.sources.api_rows

    apis = [_api_entry(row, resolver) for row in api_rows]
    api_specific: list[dict[str, Any]] = []
    for row in api_rows:
        api_specific.extend(_api_specific_tests(row))

    hosts_seen: set[str] = set()
    applicability: dict[str, dict[str, dict[str, str]]] = {}
    for row in api_rows:
        ref = str(row.get("API Identifier", ""))
        host = _row_host(row, config)
        representative = bool(host) and host not in hosts_seen
        if host:
            hosts_seen.add(host)
        applicability[ref] = resolve_applicability(
            str(row.get("HTTP Method", "")).upper(),
            str(row.get("Endpoint / Path", "")),
            resolver=resolver,
            environment=environment,
            cors_enabled=cors_enabled,
            is_host_representative=representative,
            host=host,
            api_row_present=True,
        )

    return {
        "catalogueVersion": CATALOGUE_VERSION,
        "apis": sorted(apis, key=lambda entry: entry["ref"]),
        "testCases": {
            "global": [test.as_dict() for test in global_tests()],
            "apiSpecific": sorted(api_specific, key=lambda case: case["id"]),
        },
        "applicability": {
            ref: dict(sorted(verdicts.items()))
            for ref, verdicts in sorted(applicability.items())
        },
        "environments": sorted(registered_environments_from(config)),
        # Labels only. Never a value, never a length, never a masked form —
        # a masked value still leaks its shape and its existence.
        "credentialAliases": sorted(_registered_aliases(config)),
    }


def _catalogue_config() -> dict[str, str]:
    import os

    from tests.auto_generated._api_test_helpers import load_runtime_config

    try:
        config = load_runtime_config()
    except Exception:  # pragma: no cover - config loading is defensive
        config = {}
    return {**os.environ, **config}


def _row_host(api_row: dict[str, Any], config: dict[str, str]) -> str:
    from urllib.parse import urlsplit

    from tests.auto_generated._api_test_helpers import _resolve_templates

    raw = str(api_row.get("Base URL", "") or "")
    if not raw:
        return ""
    resolved = _resolve_templates(raw, config)
    if "{{" in resolved:
        return ""
    split = urlsplit(resolved if "://" in resolved else f"https://{resolved}")
    return f"{split.scheme}://{split.netloc}" if split.netloc else ""


def _registered_aliases(config: dict[str, str]) -> set[str]:
    """Alias labels derived from registered ``CRED_<ALIAS>_EMP_CODE`` keys."""
    aliases: set[str] = set()
    for key in config:
        match = re.fullmatch(r"CRED_(?P<alias>.+)_EMP_CODE", str(key))
        if match:
            aliases.add(match.group("alias"))
    return aliases


def write_catalogue(destination: str | Path, **kwargs: Any) -> Path:
    """Write the catalogue as deterministic JSON and return the path."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        build_catalogue(**kwargs), indent=2, ensure_ascii=False, sort_keys=False
    )
    path.write_text(payload + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "-"
    if target == "-":
        print(json.dumps(build_catalogue(), indent=2, ensure_ascii=False))
    else:
        print(write_catalogue(target))

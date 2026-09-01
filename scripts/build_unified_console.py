"""Build the single-file unified console from the real handoff contracts.

The UI must never carry a hand-typed copy of the schema: every state name,
denominator rule, API row, host and credential alias below is read out of
``docs/platform-handoff/`` so the page cannot drift from the contract it
claims to render.

    python scripts/build_unified_console.py

Writes ``docs/platform-ui/unified-console.html`` — self-contained, no CDN.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "docs" / "platform-handoff"
UI = ROOT / "docs" / "platform-ui"
TEMPLATE = UI / "unified-console.template.html"
OUT = UI / "unified-console.html"

#: Verified working hosts. ATTENDANCE is deliberately *not* the underscore
#: hostname still hard-coded across the repo — that one is the resolved
#: misroute, and baking it in here would re-introduce a fixed bug.
HOSTS = {
    "attendance": "https://uatmcdphcmplatform.omfysgroup.com",
    "leave": "https://devmcdphcmplatform.omfysgroup.com",
    "auth": "https://uat-mcdp-be.omfysgroup.com",
}

#: Attendance authenticates through Login_Auth_UAT_API; a token minted by
#: Employee_Auth_API is rejected with INVALID_TOKEN. Carried so a blocked
#: result can name what blocked it.
AUTH_PROVIDER_REF = (
    "post|/auth/token|login auth uat api|tc01 - valid credentials return token"
)

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def load(name: str) -> dict:
    path = HANDOFF / name
    if not path.exists():
        sys.exit(f"missing contract sample: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def global_test_cases(catalogue: dict) -> list[dict]:
    """The 12 global checks, taken from whichever catalogue entry carries them.

    ``testCases`` is keyed by ref, and every entry repeats the same global
    block, so the first one that has it is authoritative.
    """
    cases = catalogue.get("testCases") or {}

    # Shape 1: {"global": [...]} at the top level.
    if isinstance(cases, dict) and isinstance(cases.get("global"), list):
        return sorted(cases["global"], key=lambda t: t["id"])

    # Shape 2: keyed by ref, each entry repeating the same global block.
    if isinstance(cases, dict):
        for entry in cases.values():
            if isinstance(entry, dict) and entry.get("global"):
                return sorted(entry["global"], key=lambda t: t["id"])

    sys.exit("catalogue carries no global test cases")


def applicability(catalogue: dict) -> dict:
    """Normalise the per-ref applicability map to ``{ref: {global: {id: {...}}}}``.

    The catalogue keys each ref directly by test id, with ``{"state", "reason"}``
    as the value, and there is no ``global`` wrapper — an earlier revision
    assumed one and silently dropped all 45 entries. Both shapes are accepted
    so a catalogue revision cannot reintroduce that failure quietly.

    Only non-PLANNED predictions are kept: PLANNED is the default the UI
    already assumes, and dropping it removes most of the 179KB.
    """
    out: dict[str, dict] = {}
    for ref, entry in (catalogue.get("applicability") or {}).items():
        block = entry.get("global") if isinstance(entry, dict) and "global" in entry else entry
        if isinstance(block, list):
            block = {item.get("id"): item for item in block}
        if not isinstance(block, dict):
            continue

        trimmed = {}
        for tid, value in block.items():
            if isinstance(value, dict):
                state, reason = value.get("state"), value.get("reason") or ""
            else:
                state, reason = value, ""
            if state and state != "PLANNED":
                trimmed[tid] = {"state": state, "reason": reason}
        if trimmed:
            out[ref] = {"global": trimmed}

    if not out:
        sys.exit(
            "applicability normalised to nothing — the catalogue shape changed; "
            "fix this rather than shipping a page that predicts PLANNED for everything"
        )
    return out


def load_inventory() -> dict:
    """api-docs/API_File.json keyed by ref.

    The catalogue describes *what can be tested*; the inventory carries the
    request and response examples parsed out of the collections. They join on
    the inventory's ``API Identifier``, which is the same ref the catalogue
    uses. A miss is worth knowing about rather than silently blanking a panel.
    """
    path = ROOT / "api-docs" / "API_File.json"
    if not path.exists():
        sys.exit(f"missing inventory: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {(r.get("API Identifier") or "").strip().lower(): r for r in rows}


def _clean(v) -> str:
    """Inventory cells arrive as prose, ``None``, or the string ``'None'``."""
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("", "none", "n/a", "-") else s


def _payload(v) -> str:
    """Pretty-print a cell that holds JSON; leave prose untouched."""
    s = _clean(v)
    if not s:
        return ""
    start = min((i for i in (s.find("{"), s.find("[")) if i >= 0), default=-1)
    if start < 0:
        return s
    try:
        return json.dumps(json.loads(s[start:]), indent=2)
    except Exception:
        return s


def _display_id(index: int) -> str:
    """API-001 style. Positional, and the list is sorted before numbering, so
    the same inventory always yields the same ids."""
    return f"API-{index + 1:03d}"


def _source_of(row: dict) -> tuple[str, str]:
    """Where an endpoint came from, read from the row's own provenance note.

    The generator records the file it parsed in Comments as "Source: <path>",
    which is the only place this is stated -- the inventory has no column for
    it.
    """
    comments = str(row.get("Comments", "") or "")
    match = re.search(r"Source:\s*([^;]+)", comments)
    path = match.group(1).strip() if match else ""
    if path.startswith("bruno/"):
        return "bruno", path
    if path.startswith("collections/"):
        return "newman", path
    return ("uploaded" if path else ""), path


def endpoints_from_inventory(inv: dict, catalogue: dict) -> list[dict]:
    """Build the console's endpoint list from the inventory.

    Curated fields on an endpoint the catalogue already describes are kept: a
    derived name should not silently replace one someone chose. Everything
    else -- and every endpoint the catalogue has never seen -- comes from the
    inventory, which is what makes a merged PR appear without a hand edit.
    """
    curated = {str(a.get("ref", "")).strip().lower(): a for a in catalogue.get("apis", [])}

    built: list[dict] = []
    for key, row in inv.items():
        ref = str(row.get("API Identifier", "") or "").strip()
        if not ref:
            continue
        was = curated.get(ref.strip().lower(), {})
        source_type, source_collection = _source_of(row)
        built.append({
            "ref": ref,
            "name": was.get("name") or _clean(row.get("Sub-Module Name")) or ref.split("|")[1],
            "module": was.get("module") or _clean(row.get("Module Name")),
            "subModule": was.get("subModule") or _clean(row.get("Sub-Module Name")) or None,
            "method": str(row.get("HTTP Method", "") or "").upper(),
            "path": _clean(row.get("Endpoint / Path")),
            "owner": _clean(row.get("Owner / Developer")) or None,
            "sourceType": source_type or was.get("sourceType") or "",
            "sourceCollection": source_collection or was.get("sourceCollection") or None,
            # Nothing in the inventory records whether a collection defines its
            # own assertions, so a curated value wins and the rest default to
            # the honest answer: only the global tier covers them.
            "assertionState": was.get("assertionState") or "global-only",
        })

    built.sort(key=lambda a: (a["module"] or "", a["path"] or "", a["method"] or ""))
    for i, api in enumerate(built):
        api["displayId"] = _display_id(i)
    return built


def enrich(api: dict, inv: dict) -> dict:
    """Attach the host, and the request/response examples for this endpoint."""
    module = (api.get("module") or "").lower()
    if "leave" in module:
        host = HOSTS["leave"]
    elif "auth" in module:
        host = HOSTS["auth"]
    else:
        host = HOSTS["attendance"]
    api = dict(api)
    api["baseUrl"] = host

    row = inv.get((api.get("ref") or "").strip().lower(), {})
    api["purpose"] = _clean(row.get("Functional Purpose"))
    api["access"] = _clean(row.get("Access"))
    api["params"] = _clean(row.get("Request Parameters"))
    api["dependsOn"] = _clean(row.get("Dependent APIs / Services"))
    api["requestBody"] = _payload(row.get("Example Request Payload")) or _payload(row.get("Request Body"))
    api["requestSchema"] = _payload(row.get("Request Body Schema"))
    api["successResponse"] = _payload(row.get("Example Response Payload")) or _payload(row.get("Response (example/200)"))
    #: The inventory has no error-example column. D12 leaves error-schema
    #: validation best-effort, so this stays empty rather than invented.
    api["errorResponse"] = ""
    api["notes"] = _clean(row.get("Comments"))

    try:
        api["samplePayload"] = json.loads(api["requestBody"]) if api["requestBody"] else {}
    except Exception:
        api["samplePayload"] = {}
    return api


def main() -> int:
    catalogue = load("sample-catalogue.json")
    inv = load_inventory()
    template = TEMPLATE.read_text(encoding="utf-8")

    seed = {
        # When this console was built. Piece B surfaces it, so "my PR merged but the
        # console still shows yesterday's inventory" is a visible fact, not a hunch.
        "generatedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "catalogueVersion": catalogue["catalogueVersion"],
        "resultStates": catalogue["resultStates"],
        "apis": [enrich(a, inv) for a in endpoints_from_inventory(inv, catalogue)],
        "globalTestCases": global_test_cases(catalogue),
        "applicability": applicability(catalogue),
        "environments": catalogue["environments"],
        "credentialAliases": catalogue["credentialAliases"],
        "hosts": HOSTS,
        "authProviderRef": AUTH_PROVIDER_REF,
    }

    # The console's endpoint list comes from the catalogue, and nothing
    # regenerates the catalogue -- so an endpoint added to the inventory by CI
    # is invisible here until someone updates it by hand. That is a hole in the
    # Bruno round trip and it fails silently: the inventory grew 45 -> 47 while
    # the console stayed at 45 and said nothing.
    #
    # The catalogue carries test cases and applicability the inventory does not,
    # so it cannot simply be replaced by one. Naming the orphans is the honest
    # minimum: a build that drops an endpoint should say which one.
    # The endpoint list is generated now, so an inventory row can no longer go
    # missing. What can go wrong instead is the opposite: testCases and
    # applicability are keyed by ref, and a hand-written key that no longer
    # matches any endpoint points at nothing. That is the
    # %7bholidaytemplateid%7d defect, where six test cases silently addressed an
    # endpoint that had been renamed out from under them -- so it fails the
    # build rather than shipping a catalogue that references thin air.
    live = {str(a.get("ref", "")) for a in seed["apis"]}
    dangling: list[str] = []
    for case in catalogue.get("testCases", {}).get("apiSpecific", []):
        ref = str(case.get("apiRef", "") or "")
        if ref and ref not in live:
            dangling.append(f"testCases.apiSpecific -> {ref}")
    for ref in catalogue.get("applicability", {}):
        if str(ref) not in live:
            dangling.append(f"applicability -> {ref}")
    if dangling:
        print(f"  {len(dangling)} catalogue key(s) reference an endpoint that no longer exists:")
        for d in dangling[:10]:
            print(f"    {d}")
        if len(dangling) > 10:
            print(f"    ... and {len(dangling) - 10} more")
        sys.exit(
            "catalogue keys must resolve to a real endpoint - "
            "the inventory is generated, so a stale ref here is a rename that "
            "left its test cases behind"
        )

    blob = json.dumps(seed, separators=(",", ":"), ensure_ascii=False)

    # A stray control character in embedded JSON fails silently at parse time,
    # which is exactly how the 0x08-in-a-regex defect survived a green suite.
    stray = CONTROL_CHARS.search(blob)
    if stray:
        sys.exit(f"control character {stray.group()!r} at offset {stray.start()}")

    # Guard the two ways an inlined <script> block can escape its own tag.
    blob = blob.replace("</", "<\\/").replace("<!--", "<\\!--")

    if "__SEED__" not in template:
        sys.exit("template lost its __SEED__ placeholder")

    OUT.write_text(template.replace("__SEED__", blob), encoding="utf-8")

    print(f"wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"  {len(seed['apis'])} APIs · {len(seed['globalTestCases'])} global checks")
    joined = sum(1 for a in seed["apis"] if a["purpose"])
    bodies = sum(1 for a in seed["apis"] if a["requestBody"])
    resps = sum(1 for a in seed["apis"] if a["successResponse"])
    print(f"  inventory joined for {joined}/{len(seed['apis'])} · "
          f"{bodies} request bodies · {resps} response examples")
    if joined != len(seed["apis"]):
        print("  WARNING: some endpoints did not join the inventory by ref")
    print(f"  {len(seed['applicability'])} refs carry a non-PLANNED prediction")
    print(f"  environments: {', '.join(seed['environments'])}")
    print(f"  aliases: {', '.join(seed['credentialAliases'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

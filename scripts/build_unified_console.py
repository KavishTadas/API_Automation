"""Build the single-file unified console from the real handoff contracts.

The UI must never carry a hand-typed copy of the schema: every state name,
denominator rule, API row, host and credential alias below is read out of
``docs/platform-handoff/`` so the page cannot drift from the contract it
claims to render.

    python scripts/build_unified_console.py

Writes ``docs/platform-ui/unified-console.html`` — self-contained, no CDN.
"""

from __future__ import annotations

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


def enrich(api: dict) -> dict:
    """Attach the host and a payload placeholder the catalogue does not carry."""
    module = (api.get("module") or "").lower()
    if "leave" in module:
        host = HOSTS["leave"]
    elif "auth" in module:
        host = HOSTS["auth"]
    else:
        host = HOSTS["attendance"]
    api = dict(api)
    api["baseUrl"] = host
    api.setdefault("samplePayload", {})
    return api


def main() -> int:
    catalogue = load("sample-catalogue.json")
    template = TEMPLATE.read_text(encoding="utf-8")

    seed = {
        "catalogueVersion": catalogue["catalogueVersion"],
        "resultStates": catalogue["resultStates"],
        "apis": [enrich(a) for a in catalogue["apis"]],
        "globalTestCases": global_test_cases(catalogue),
        "applicability": applicability(catalogue),
        "environments": catalogue["environments"],
        "credentialAliases": catalogue["credentialAliases"],
        "hosts": HOSTS,
        "authProviderRef": AUTH_PROVIDER_REF,
    }

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
    print(f"  {len(seed['applicability'])} refs carry a non-PLANNED prediction")
    print(f"  environments: {', '.join(seed['environments'])}")
    print(f"  aliases: {', '.join(seed['credentialAliases'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

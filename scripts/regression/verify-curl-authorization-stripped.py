"""A pasted cURL token must not survive the parse, on any path.

``curl_adapter`` exists so the platform does not write a second cURL parser and
reimplement -- or forget -- this. The behaviour is only worth relying on if it
holds on the failure paths too, so this checks stdout, stderr, warnings, the
stored ``cURL`` text, the definition's repr, the manifest block, and the
exception messages raised by malformed input.

Run: python scripts/regression/verify-curl-authorization-stripped.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.global_contract.curl_adapter import (  # noqa: E402
    CurlParseError,
    curl_to_definition,
    curl_to_inventory_row,
    parse_curl,
)
from tests.global_contract.run_manifest import (  # noqa: E402
    ManifestValidationError,
    definition_to_manifest_block,
    validate_manifest,
)

#: Distinctive enough that a substring check cannot match by accident.
TOKEN = "eyJhbGciOiJIUzI1NiJ9.SUPERSECRETPAYLOAD9137.sigABCDEF0123456789"
PASSWORD = "Sup3rS3cretPassw0rd9137"
SECRETS = (TOKEN, PASSWORD)

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}" + (f"\n         {detail}" if detail else ""))


def leaks(text: object) -> str:
    """Return the secret found in ``text``, or ``''``."""
    blob = str(text)
    for secret in SECRETS:
        if secret in blob:
            return secret
    return ""


# --------------------------------------------------------------------------
# 1. Every in-process surface of a successful parse
# --------------------------------------------------------------------------
print("Parsed definition surfaces")

COMMANDS = {
    "single-quoted Authorization": f"curl 'https://h.example.com/a' -H 'Authorization: Bearer {TOKEN}'",
    "double-quoted Authorization": f'curl "https://h.example.com/a" -H "Authorization: Bearer {TOKEN}"',
    "unquoted Authorization": f"curl https://h.example.com/a -H Authorization:Bearer{TOKEN}",
    "lowercase --header": f"curl https://h.example.com/a --header 'authorization: Bearer {TOKEN}'",
    "-u basic credentials": f"curl https://h.example.com/a -u admin:{PASSWORD}",
    "Cookie header": f"curl https://h.example.com/a -H 'Cookie: session={TOKEN}'",
    "Proxy-Authorization": f"curl https://h.example.com/a -H 'Proxy-Authorization: Bearer {TOKEN}'",
    "token in body too": (
        f"curl -X POST https://h.example.com/a -H 'Authorization: Bearer {TOKEN}' "
        f"-H 'X-Trace: keep-me' -d '{{\"note\":\"body stays\"}}'"
    ),
}

for label, command in COMMANDS.items():
    definition, warnings = curl_to_definition(command, api_id="API-CHK", module="M")
    row, _, row_warnings = curl_to_inventory_row(command, api_id="API-CHK", module="M")
    parsed = parse_curl(command)
    block = definition_to_manifest_block(definition)

    surfaces = {
        "definition repr": repr(definition),
        "stored cURL text": definition.curl,
        "warnings": " ".join(warnings) + " ".join(row_warnings),
        "manifest block": json.dumps(block, ensure_ascii=False),
        "inventory row": json.dumps(row, ensure_ascii=False),
        "parsed headers": json.dumps(parsed.headers, ensure_ascii=False),
        "parsed repr": repr(parsed),
        "stripped header names": json.dumps(list(parsed.stripped_headers)),
    }
    found = {name: leaks(value) for name, value in surfaces.items()}
    bad = {n: s for n, s in found.items() if s}
    check(f"{label}: secret absent from all {len(surfaces)} surfaces", not bad, str(bad))

# The endpoint's *need* for auth must survive even though the value does not.
definition, _ = curl_to_definition(COMMANDS["single-quoted Authorization"])
check(
    "an Authorization header still yields Auth Type 'Bearer Token'",
    str(definition.auth_type).lower().startswith("bearer"),
    f"auth_type={definition.auth_type!r}",
)
# A non-sensitive header must be kept, or stripping is just data loss.
parsed = parse_curl(COMMANDS["token in body too"])
check("non-sensitive headers survive", parsed.headers.get("X-Trace") == "keep-me")


# --------------------------------------------------------------------------
# 2. Error paths -- a malformed Authorization header is a plausible paste
# --------------------------------------------------------------------------
print("\nException messages")

MALFORMED = {
    "header missing its colon": f"curl https://h.example.com/a -H 'Authorization Bearer {TOKEN}'",
    "bare token as a header": f"curl https://h.example.com/a -H '{TOKEN}'",
    "unclosed quote": f"curl https://h.example.com/a -H 'Authorization: Bearer {TOKEN}",
    "no URL at all": f"curl -H 'Authorization: Bearer {TOKEN}'",
}
for label, command in MALFORMED.items():
    try:
        result, _ = curl_to_definition(command)
        check(f"{label}: parsed, secret absent", not leaks(result.curl), str(result.curl))
    except CurlParseError as error:
        check(f"{label}: CurlParseError names no secret", not leaks(error), str(error))
    except Exception as error:  # noqa: BLE001 - the point is to catch everything
        check(f"{label}: {type(error).__name__} names no secret", not leaks(error), str(error))


# --------------------------------------------------------------------------
# 3. The CLI, end to end -- stdout and stderr of a real subprocess
# --------------------------------------------------------------------------
print("\nCLI subprocess (stdout + stderr)")

with tempfile.TemporaryDirectory() as tmp:
    curl_file = Path(tmp) / "cmd.curl"
    curl_file.write_text(COMMANDS["token in body too"], encoding="utf-8")

    for label, argv, stdin in [
        ("file input", [str(curl_file), "--api-id", "API-1"], None),
        ("stdin input", ["-", "--api-id", "API-1"], COMMANDS["single-quoted Authorization"]),
        ("--entry wrapper", [str(curl_file), "--entry", "--credential-alias", "svc-01"], None),
    ]:
        proc = subprocess.run(
            [sys.executable, "-m", "tests.global_contract.parse_curl", *argv],
            cwd=ROOT_DIR, input=stdin, capture_output=True, text=True,
        )
        check(f"{label}: exit 0", proc.returncode == 0, proc.stderr[:200])
        check(f"{label}: stdout carries no secret", not leaks(proc.stdout))
        check(f"{label}: stderr carries no secret", not leaks(proc.stderr))
        try:
            json.loads(proc.stdout)
            check(f"{label}: stdout is valid JSON", True)
        except ValueError as error:
            check(f"{label}: stdout is valid JSON", False, str(error))

    # The failure path must not echo the command either.
    bad_file = Path(tmp) / "bad.curl"
    bad_file.write_text(MALFORMED["header missing its colon"], encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "tests.global_contract.parse_curl", str(bad_file)],
        cwd=ROOT_DIR, capture_output=True, text=True,
    )
    check("unparseable input: exit 2", proc.returncode == 2, f"got {proc.returncode}")
    check("unparseable input: stdout carries no secret", not leaks(proc.stdout))
    check("unparseable input: stderr carries no secret", not leaks(proc.stderr), proc.stderr[:200])


# --------------------------------------------------------------------------
# 4. The emitted block is actually usable as a manifest entry
# --------------------------------------------------------------------------
print("\nEmitted block is manifest-shaped")

definition, _ = curl_to_definition(
    COMMANDS["token in body too"], api_id="API-CURL-1", module="Uploaded"
)
manifest = {
    "runId": "curl-check",
    "environment": "UAT",
    "requestedTiers": ["global_contract"],
    "apis": [{"definition": definition_to_manifest_block(definition),
              "credentialAlias": "leave-svc-uat-01"}],
}
check("manifest carrying the block holds no secret", not leaks(json.dumps(manifest)))

try:
    validate_manifest(manifest, registered_environments=frozenset({"UAT"}))
    check("manifest validates", True)
except ManifestValidationError as error:
    # A manifest built from a cURL upload must pass the same validation a
    # hand-written one does, credential-key scan included.
    check("manifest validates", False, "; ".join(getattr(error, "errors", [str(error)])))
except Exception as error:  # noqa: BLE001
    check("manifest validates", False, f"{type(error).__name__}: {error}")


print()
if failures:
    print(f"{len(failures)} check(s) FAILED:")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("All cURL Authorization-stripping checks passed.")

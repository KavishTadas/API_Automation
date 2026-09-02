"""Refuse a response header that names a product version.

    python scripts/regression/verify-response-header-hygiene.py [--json] [--strict]

Guards the finding in RCA-001: every host in this estate answers with
``Server: nginx/1.18.0 (Ubuntu)``, which hands a reader the exact CVE list for
the build. The fix is one nginx directive, and it is applied on infrastructure
this repository does not contain -- so the fix cannot be committed here, only
verified from here. That is what this script is for: it is the acceptance test
ops runs after changing nginx, and the regression gate that catches the header
coming back.

It duplicates ``test_no_server_version_disclosure`` deliberately. That check
needs a credential, a manifest and the whole pytest tier to reach a host; this
needs a URL. Ops should not have to run someone else's test suite to confirm
their own change, and CI should not need a token to notice a banner returned.

Exit status
    0  no reachable host disclosed a version
    1  a reachable host disclosed one -- the regression this guards
    2  nothing could be reached, so nothing was proved

An unreachable host is never a pass. A dead DNS entry once read as a clean
result for four minutes here, and the seven-state model exists because of
exactly that: a check that could not run must not render as one that ran.
Standard library only -- CI installs nothing before calling it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]

#: Byte-identical to test-cases/global/_support.py. Two spellings of "is this a
#: version" would eventually disagree, and the day they do, one of them passes a
#: banner the other fails.
VERSION_IN_HEADER = re.compile(r"\d+\.\d+")

#: Headers that name the product. `Server` may stay; the version may not.
DISCLOSING_HEADERS = ("server", "x-powered-by", "x-aspnet-version")

#: Advisory only. Absence is reported, and fails the run only under --strict,
#: because adding them is a separate change with its own blast radius.
EXPECTED_HARDENING = {
    "strict-transport-security": "HSTS - without it the first request over http is stealable",
    "x-content-type-options": "nosniff",
    "x-frame-options": "or a CSP frame-ancestors directive",
}

TIMEOUT_SECONDS = 20


def read_dotenv(path: Path) -> dict[str, str]:
    """Same parsing as tests/api_runtime/_api_test_helpers.py:_read_dotenv."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


def discover_hosts(explicit: list[str]) -> list[str]:
    """Every distinct origin this repository is configured to call.

    Reads *_BASE_URL* from the environment and .env rather than a hardcoded
    list, so a host added to the estate is covered without editing this file --
    the same reason the base-URL convention in .env.example derives keys instead
    of tabulating them.
    """
    if explicit:
        return list(dict.fromkeys(explicit))

    config = {**read_dotenv(ROOT / ".env"), **os.environ}
    origins: list[str] = []
    for key, value in config.items():
        if "BASE_URL" not in key.upper() or not value:
            continue
        parts = urlsplit(value.strip())
        if parts.scheme in ("http", "https") and parts.netloc:
            origins.append(f"{parts.scheme}://{parts.netloc}")
    return sorted(dict.fromkeys(origins))


def probe(origin: str) -> dict:
    """One request per origin. Header hygiene is a property of the host."""
    request = urllib.request.Request(origin + "/", method="GET")
    request.add_header("User-Agent", "header-hygiene-check/1.0")
    # A 401 or 404 carries the same response headers as a 200 and needs no
    # credential, so an auth failure here is a perfectly good sample. Only a
    # transport failure means we learned nothing.
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            headers, status = response.headers, response.status
    except urllib.error.HTTPError as exc:
        headers, status = exc.headers, exc.code
    except Exception as exc:  # noqa: BLE001 - DNS, TLS, timeout all mean "no sample"
        return {"origin": origin, "reachable": False, "error": f"{type(exc).__name__}: {exc}"}

    present = {key.lower(): value for key, value in headers.items()}
    disclosed = {
        name: present[name]
        for name in DISCLOSING_HEADERS
        if name in present and VERSION_IN_HEADER.search(present[name] or "")
    }
    missing = {
        name: why for name, why in EXPECTED_HARDENING.items() if name not in present
    }
    return {
        "origin": origin,
        "reachable": True,
        "status": status,
        "server": present.get("server", ""),
        "disclosed": disclosed,
        "missingHardening": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify-response-header-hygiene.py",
        description="Fail if a reachable host names a product version in its headers.",
    )
    parser.add_argument("hosts", nargs="*", help="Origins to probe. Default: every *_BASE_URL*.")
    parser.add_argument("--json", action="store_true", help="Machine-readable report on stdout.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also fail when a hardening header is absent, not just when a version leaks.",
    )
    args = parser.parse_args(argv)

    origins = discover_hosts(args.hosts)
    if not origins:
        print("No *_BASE_URL* configured; nothing to probe.", file=sys.stderr)
        return 2

    results = [probe(origin) for origin in origins]
    if args.json:
        print(json.dumps({"results": results}, indent=2))
    else:
        for row in results:
            if not row["reachable"]:
                print(f"  UNREACHABLE  {row['origin']}\n                 {row['error']}")
                continue
            verdict = "DISCLOSES  " if row["disclosed"] else "clean      "
            print(f"  {verdict}  {row['origin']}  (HTTP {row['status']})")
            for name, value in row["disclosed"].items():
                print(f"                 {name}: {value}")
            for name, why in row["missingHardening"].items():
                print(f"                 missing {name}  ({why})")

    reached = [r for r in results if r["reachable"]]
    leaking = [r for r in reached if r["disclosed"]]
    unhardened = [r for r in reached if r["missingHardening"]]

    print()
    if not reached:
        print(f"Nothing reachable of {len(origins)} origin(s); no conclusion.")
        return 2
    if leaking:
        print(f"{len(leaking)} of {len(reached)} reachable origin(s) disclose a product version.")
        return 1
    if args.strict and unhardened:
        print(f"{len(unhardened)} of {len(reached)} reachable origin(s) miss a hardening header.")
        return 1
    print(f"No product version disclosed by {len(reached)} reachable origin(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

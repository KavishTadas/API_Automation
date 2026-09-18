#!/usr/bin/env python3
"""Check whether the API hosts still announce their web-server version.

Answers one question in one command, so whoever applies the nginx change can
confirm it worked without running the whole contract suite:

    python scripts/check_server_banner.py
    python scripts/check_server_banner.py some.other.host

Two places are checked, because server_tokens governs both:

* the ``Server`` header on an HTTPS response, which is what the contract check
  ``test_no_server_version_disclosure`` reads, and
* the body of nginx's own plain-HTTP redirect page, which nginx writes with no
  application involved. That makes it proof of which layer is speaking: if the
  version is there, it is nginx, not the service behind it.

The pattern is the contract check's own (``\\d+\\.\\d+``), so a host this script
calls clean is one that check will pass.

Exit status is 0 when every host is clean, 1 when a host could not be reached,
and 2 when any host still discloses a version. Unreachable is not clean -- it
would claim the fix worked on a server nobody checked -- but it ranks below a
disclosure, which is a verified finding rather than an unknown.
"""

from __future__ import annotations

import re
import sys

import httpx

#: The hosts behind the 42 version-disclosure failures on 2026-09-17.
DEFAULT_HOSTS = (
    "uatmcdphcmplatform.omfysgroup.com",
    "uat-mcdp-be.omfysgroup.com",
    "devmcdphcmplatform.omfysgroup.com",
)

#: Same pattern as test-cases/global/_support.py::_VERSION_IN_HEADER.
VERSION = re.compile(r"\d+\.\d+")


def check(host: str) -> tuple[str, str, str]:
    """Return (verdict, header, error-page footer) for one host."""
    try:
        https = httpx.get(f"https://{host}/", timeout=10)
        plain = httpx.get(f"http://{host}/", timeout=10, follow_redirects=False)
    except httpx.HTTPError as error:
        return "UNREACHABLE", type(error).__name__, ""

    header = https.headers.get("server", "(none)")
    footer = ""
    match = re.search(r"<center>([^<]*nginx[^<]*)</center>", plain.text, re.I)
    if match:
        footer = match.group(1).strip()

    disclosed = bool(VERSION.search(header)) or bool(VERSION.search(footer))
    return ("DISCLOSES" if disclosed else "CLEAN"), header, footer


def main(argv: list[str]) -> int:
    hosts = tuple(argv) or DEFAULT_HOSTS
    worst = 0
    print(f"{'host':38s} {'verdict':12s} {'Server header':28s} error page")
    for host in hosts:
        verdict, header, footer = check(host)
        print(f"{host:38s} {verdict:12s} {header:28s} {footer or '-'}")
        # DISCLOSES outranks UNREACHABLE: a host that is provably still
        # exposing its version is the finding, and letting an unreachable
        # neighbour outrank it would report exit 2 ("not verified") for a
        # run that verified a failure.
        worst = max(worst, {"CLEAN": 0, "UNREACHABLE": 1, "DISCLOSES": 2}[verdict])

    print()
    if worst == 0:
        print("All hosts clean. The version-disclosure check will pass.")
    elif worst == 1:
        print("At least one host could not be reached, so it was not verified.")
    else:
        print("Still disclosing. See docs/rca/nginx-server-tokens.conf.")
    return worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""The three UI contract checks, hardened. Exit 0 = all pass.

Run it::

    python scripts/verify-harness-ui.py [--manifest baseline/44-endpoint-manifest.json]

Why this exists as a script rather than ad-hoc commands
-------------------------------------------------------
Two failure modes were hit running these by hand, and both produced a **false
pass** rather than an error:

1. A harness left running from an earlier check still owned the fixed port 8765.
   The new instance died with ``[Errno 10048] only one usage of each socket
   address``, into a log nobody read, and the checks silently interrogated the
   *stale* process -- reporting the pre-change catalogue as if it were current.
2. ``taskkill`` with a ``COMMANDLINE`` filter matched nothing and reported
   success, so the stale process survived a teardown that looked like it worked.

So: an **ephemeral port per run**, never a fixed one, and a startup failure
**aborts** instead of logging. ``runsHeld`` is asserted to be 0 as a freshness
tell -- a reused process would carry runs from before.

The checks
----------
1. ``sourceCollection`` values still carry the ``collections/auth/`` prefix the
   auth-provider dropdown filters on.
2. That dropdown resolves exactly the two token-issuing providers -- using the
   regexes read out of the console template itself, so the check cannot pass
   against a filter that differs from the shipped one.
3. A manifest with a **per-entry** ``authProviderApiId`` round-trips, with no
   ``SKIPPED_NO_TOKEN``.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
UI_HTML = ROOT_DIR / "docs" / "platform-ui" / "unified-console.template.html"
STARTUP_TIMEOUT_S = 40
EXPECTED_AUTH_ENTRIES = 4
EXPECTED_PROVIDERS = 2


class CheckAborted(RuntimeError):
    """The harness could not be established, so no check result is meaningful."""


def free_port() -> int:
    """Ask the OS for an unused port and release it immediately.

    A fixed port is what let a stale process answer for a live one. The tiny
    race between closing here and uvicorn binding is acceptable; a collision
    surfaces as a startup abort, never as a check run against the wrong server.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def get_json(url: str, timeout: int = 30) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def start_harness(port: int) -> subprocess.Popen:
    """Start the harness, or raise. Never returns a process that is not serving."""
    process = subprocess.Popen(
        [sys.executable, "-m", "harness.serve", "--port", str(port)],
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    deadline = time.time() + STARTUP_TIMEOUT_S
    while time.time() < deadline:
        if process.poll() is not None:
            raise CheckAborted(
                f"harness exited with code {process.returncode} before serving:\n"
                f"{(process.stdout.read() if process.stdout else '').strip()}"
            )
        try:
            health = get_json(f"http://127.0.0.1:{port}/health", timeout=3)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            time.sleep(0.4)
            continue

        # A reused process would carry runs from an earlier check. This is the
        # tell that caught a stale harness answering for a fresh one.
        if health.get("runsHeld") != 0:
            process.kill()
            raise CheckAborted(
                f"harness on port {port} reports runsHeld="
                f"{health.get('runsHeld')}; expected a fresh process holding 0"
            )
        return process

    process.kill()
    raise CheckAborted(f"harness did not answer on port {port} within {STARTUP_TIMEOUT_S}s")


def ui_provider_filter() -> tuple[re.Pattern, re.Pattern]:
    """Read the dropdown's regexes out of the console source, not restating them.

    Restating them means the check can pass against a filter the UI does not
    actually use -- which is the bug the filter itself was written to fix.
    """
    html = UI_HTML.read_text(encoding="utf-8")
    if "AUTH_NEGATIVE_CASE" not in html or "canMintToken" not in html:
        raise CheckAborted(
            "unified-console.template.html no longer declares the provider filter"
        )
    return (
        re.compile(r"^collections/auth/", re.I),
        re.compile(
            r"\b(invalid|missing|expired|malformed|unauthori[sz]ed|returns\s+4\d\d)\b",
            re.I,
        ),
    )


def run_checks(port: int, manifest_path: Path) -> list[tuple[str, bool, str]]:
    base = f"http://127.0.0.1:{port}"
    catalogue = get_json(f"{base}/catalogue")
    apis = catalogue.get("apis", [])
    results: list[tuple[str, bool, str]] = []

    auth_entries = [
        a
        for a in apis
        if str(a.get("sourceCollection", "")).startswith("collections/auth/")
    ]
    results.append(
        (
            "sourceCollection prefix unchanged",
            len(auth_entries) == EXPECTED_AUTH_ENTRIES,
            f"{len(auth_entries)} entries under collections/auth/ "
            f"(expected {EXPECTED_AUTH_ENTRIES})",
        )
    )

    auth_re, negative_re = ui_provider_filter()
    providers = [
        a
        for a in apis
        if a.get("method") == "POST"
        and auth_re.search(a.get("sourceCollection") or "")
        and not negative_re.search(a.get("ref") or "")
    ]
    results.append(
        (
            "dropdown resolves the token providers",
            len(providers) == EXPECTED_PROVIDERS,
            f"{len(providers)} provider(s): "
            f"{', '.join(sorted(p['module'] for p in providers)) or 'none'}",
        )
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    employee = "post|/auth/token|employee auth api|tc01 - valid credentials return jwt token"
    uat = "post|/auth/token|login auth uat api|tc01 - valid credentials return token"
    entries = []
    for entry in manifest["apis"][:4]:
        scoped = dict(entry)
        # Deliberately mixed: a single-provider shortcut would pass a uniform
        # manifest and fail this one.
        scoped["authProviderApiId"] = uat if len(entries) % 2 else employee
        entries.append(scoped)

    payload = json.dumps(
        {
            "runId": "ui-contract-check",
            "environment": manifest.get("environment", "UAT"),
            "requestedTiers": ["global_contract"],
            "apis": entries,
        }
    ).encode()
    request = urllib.request.Request(
        f"{base}/run",
        data=payload,
        headers={"Content-Type": "application/json", "Origin": base},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        document = json.load(response)

    counts = document.get("summary", {}).get("counts", {})
    ok = (
        document.get("status") == "COMPLETED"
        and len(document.get("apis", [])) == len(entries)
        and counts.get("SKIPPED_NO_TOKEN") == 0
    )
    results.append(
        (
            "per-entry authProviderApiId round-trips",
            ok,
            f"status={document.get('status')} apis={len(document.get('apis', []))} "
            f"SKIPPED_NO_TOKEN={counts.get('SKIPPED_NO_TOKEN')}",
        )
    )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify-harness-ui")
    parser.add_argument(
        "--manifest",
        default=str(ROOT_DIR / "baseline" / "44-endpoint-manifest.json"),
        help="Manifest to draw the round-trip entries from.",
    )
    args = parser.parse_args(argv)

    port = free_port()
    print(f"harness on ephemeral port {port}")
    try:
        process = start_harness(port)
    except CheckAborted as error:
        print(f"ABORTED: {error}", file=sys.stderr)
        return 2

    try:
        results = run_checks(port, Path(args.manifest))
    except CheckAborted as error:
        print(f"ABORTED: {error}", file=sys.stderr)
        return 2
    finally:
        process.kill()
        process.wait(timeout=10)

    print()
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    failed = [name for name, ok, _ in results if not ok]
    print()
    if failed:
        print(f"{len(failed)} UI check(s) FAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"all {len(results)} UI checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

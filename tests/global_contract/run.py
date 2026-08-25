"""CLI entry point: run a manifest, write a result document, exit on run status.

    python -m tests.global_contract.run <manifest> --out <path>

Why this exists
---------------
Without it, a caller has to set two environment variables, invoke pytest, and
interpret pytest's exit code — which is non-zero whenever any test fails. That
directly contradicts the contract this engine publishes: **a test FAIL is not a
run failure**. A platform wiring itself to pytest's exit code would report an
engine outage every time one assertion failed.

So the exit code here carries *engine-level* status only:

===========================  ====  =========================================
Status                       Exit  Meaning
===========================  ====  =========================================
``COMPLETED``                0     Every requested tier executed
``COMPLETED_WITH_ERRORS``    0     A tier ran partially (e.g. auth bootstrap)
``ABORTED``                  2     A tier could not start
(unexpected internal error)  3     The runner itself broke
===========================  ====  =========================================

Both `COMPLETED` states are success: the run did what it was asked. Whether the
APIs behaved is in the result document, which is where the platform reads it.

A result document is written on **every** path, including ABORTED, so the caller
always has something to render rather than having to special-case an empty
response.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]

from tests.global_contract.catalogue import CATALOGUE_VERSION  # noqa: E402
from tests.global_contract.result_emitter import (  # noqa: E402
    RunStatus,
    write_result_document,
)
from tests.global_contract.run_manifest import (  # noqa: E402
    RUN_MANIFEST_ENV_VAR,
    ManifestValidationError,
    load_manifest,
    registered_environments_from,
)


#: Exit codes. Only ABORTED and an internal error are non-zero.
EXIT_OK = 0
EXIT_ABORTED = 2
EXIT_INTERNAL_ERROR = 3

DEFAULT_OUT = Path("reports") / "platform" / "global-contract-results.json"

RESULTS_ENV_VAR = "GLOBAL_CONTRACT_RESULT_PATH"


def _aborted_document(
    reason: str,
    *,
    run_id: str = "",
    environment: str = "",
    requested_tiers: tuple[str, ...] = (),
) -> dict:
    """A result document for a run that never started.

    The caller gets the same shape it would get from a successful run, so its
    renderer needs no special case for "nothing came back".
    """
    return {
        "runId": run_id or "unknown",
        "environment": environment,
        "requestedTiers": list(requested_tiers),
        "catalogueVersion": CATALOGUE_VERSION,
        "status": RunStatus.ABORTED,
        "statusReason": reason,
        "summary": {
            "total": 0,
            "referencedHostResults": 0,
            "counts": {},
            "passRate": None,
            "passRateApplicable": False,
            "passRateBasis": "PASS / (PASS + FAIL)",
            "clean": False,
        },
        "apis": [],
    }


def _config() -> dict[str, str]:
    from tests.auto_generated._api_test_helpers import load_runtime_config

    try:
        config = load_runtime_config()
    except Exception:  # pragma: no cover - defensive
        config = {}
    return {**os.environ, **config}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tests.global_contract.run",
        description="Run a global-contract manifest and emit a result document.",
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        help=(
            "Path to the run manifest. Defaults to $"
            f"{RUN_MANIFEST_ENV_VAR} when omitted."
        ),
    )
    parser.add_argument(
        "--out",
        default="",
        help=f"Where to write the result document (default: {DEFAULT_OUT}).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress pytest's own output; print only the result path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # The environment variable stays authoritative when no argument is given, so
    # every existing invocation keeps working unchanged.
    manifest_path = args.manifest or os.environ.get(RUN_MANIFEST_ENV_VAR, "").strip()
    out_path = Path(
        args.out or os.environ.get(RESULTS_ENV_VAR, "").strip() or DEFAULT_OUT
    )
    if not out_path.is_absolute():
        out_path = ROOT_DIR / out_path

    if not manifest_path:
        write_result_document(
            out_path,
            _aborted_document(
                "no manifest supplied: pass one as an argument or set "
                f"{RUN_MANIFEST_ENV_VAR}"
            ),
        )
        print(f"ABORTED: no manifest supplied. Result document: {out_path}", file=sys.stderr)
        return EXIT_ABORTED

    # Validate before running anything. An invalid manifest is a caller error and
    # must abort rather than half-run a batch nobody asked for.
    try:
        manifest = load_manifest(
            manifest_path, registered_environments_from(_config())
        )
    except ManifestValidationError as error:
        write_result_document(out_path, _aborted_document(str(error)))
        print(f"ABORTED: {error}", file=sys.stderr)
        print(f"Result document: {out_path}", file=sys.stderr)
        return EXIT_ABORTED

    os.environ[RUN_MANIFEST_ENV_VAR] = str(manifest_path)
    os.environ[RESULTS_ENV_VAR] = str(out_path)

    import pytest

    pytest_args = [str(ROOT_DIR / "tests" / "global_contract"), "-p", "no:cacheprovider"]
    if args.quiet:
        pytest_args += ["-q", "--tb=no"]

    try:
        pytest.main(pytest_args)
    except Exception as error:  # pragma: no cover - defensive
        write_result_document(
            out_path,
            _aborted_document(
                f"the runner failed: {type(error).__name__}",
                run_id=manifest.run_id,
                environment=manifest.environment,
                requested_tiers=manifest.requested_tiers,
            ),
        )
        print(f"Result document: {out_path}", file=sys.stderr)
        return EXIT_INTERNAL_ERROR

    # pytest's exit code is deliberately ignored: it is non-zero whenever a test
    # fails, and a test failure is not a run failure. The status in the document
    # is the only thing that decides this process's exit code.
    if not out_path.exists():
        write_result_document(
            out_path,
            _aborted_document(
                "the tier produced no results; nothing was collected",
                run_id=manifest.run_id,
                environment=manifest.environment,
                requested_tiers=manifest.requested_tiers,
            ),
        )
        print(f"ABORTED: no results produced. Result document: {out_path}", file=sys.stderr)
        return EXIT_ABORTED

    try:
        document = json.loads(out_path.read_text(encoding="utf-8"))
        status = str(document.get("status", ""))
    except (OSError, ValueError) as error:
        print(
            f"Result document at {out_path} is unreadable ({type(error).__name__})",
            file=sys.stderr,
        )
        return EXIT_INTERNAL_ERROR

    if status == RunStatus.ABORTED:
        print(f"ABORTED: {document.get('statusReason', '')}", file=sys.stderr)
        print(f"Result document: {out_path}", file=sys.stderr)
        return EXIT_ABORTED

    summary = document.get("summary", {})
    counts = summary.get("counts", {})
    print(f"\nstatus:  {status}")
    if document.get("statusReason"):
        print(f"reason:  {document['statusReason']}")
    print(
        "results: "
        + ", ".join(f"{name}={value}" for name, value in counts.items() if value)
    )
    rate = summary.get("passRate")
    print(f"passRate: {'not applicable' if rate is None else rate}")
    print(f"Result document: {out_path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

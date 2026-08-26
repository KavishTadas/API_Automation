"""Local validation harness — HTTP service. DISPOSABLE, NOT THE PLATFORM PLUGIN.

Wraps the Sprint 3 catalogue and the Sprint 4 CLI behind four endpoints so a
browser can drive the same contracts the platform will drive. Everything here is
throwaway: no auth, no persistence, no multi-user safety.

Two boundaries are enforced rather than assumed, because harness habits become
product habits:

**Localhost only.** The service refuses to bind anything else. A validation rig
holding UAT credentials must not be reachable from the network.

**Credentials never cross to the browser.** The browser sends a
``credentialAlias`` — a label. This process resolves it from the environment at
run time. No raw value is ever serialised into a response, and the alias list
served to the UI carries labels only.

Transport mirrors the CLI's exit-code semantics: ``COMPLETED`` and
``COMPLETED_WITH_ERRORS`` are HTTP 200 because the run happened; only ``ABORTED``
is non-2xx. **A test FAIL is not a transport failure** — a batch where every
assertion fails still returns 200, and the result document says so.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from tests.global_contract.catalogue import build_catalogue  # noqa: E402
from tests.global_contract.credentials import (  # noqa: E402
    CredentialResolutionError,
    credential_env_keys,
    resolve_credential,
)
from tests.global_contract.result_emitter import RunStatus  # noqa: E402
from tests.global_contract.run_manifest import (  # noqa: E402
    ManifestValidationError,
    registered_environments_from,
    validate_manifest,
)

HOST = "127.0.0.1"
PORT = 8765

#: Only a browser served from this harness may call it.
ALLOWED_ORIGINS = [f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"]

#: Loopback addresses. Binding anywhere else is refused outright.
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

UI_PATH = Path(__file__).with_name("ui.html")

app = FastAPI(
    title="Local Validation Harness (disposable)",
    description="Not the platform plugin. Proves the Sprint 1-4 contracts locally.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

#: Runs live here and nowhere else. Restarting the process discards them.
_RUNS: dict[str, dict[str, Any]] = {}
_CATALOGUE_CACHE: dict[str, Any] = {}


def assert_loopback(host: str) -> None:
    """Refuse any bind address that is not loopback."""
    if host not in LOOPBACK:
        raise RuntimeError(
            f"refusing to bind {host!r}: the harness holds UAT credentials and "
            f"binds loopback only (allowed: {sorted(LOOPBACK)})"
        )


def _runtime_config() -> dict[str, str]:
    import os

    from tests.auto_generated._api_test_helpers import load_runtime_config

    try:
        config = load_runtime_config()
    except Exception:
        config = {}
    return {**os.environ, **config}


def _catalogue(refresh: bool = False) -> dict[str, Any]:
    if refresh or "data" not in _CATALOGUE_CACHE:
        _CATALOGUE_CACHE["data"] = build_catalogue()
    return _CATALOGUE_CACHE["data"]


def _aborted(reason: str, run_id: str = "", detail: Any = None) -> dict[str, Any]:
    """An ABORTED result document. Returned as a body, never an empty response."""
    return {
        "runId": run_id or "unknown",
        "environment": "",
        "requestedTiers": [],
        "status": RunStatus.ABORTED,
        "statusReason": reason,
        "errors": detail or [],
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


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "harness": "disposable-local-validation",
        "bind": f"{HOST}:{PORT}",
        "runsHeld": len(_RUNS),
    }


@app.get("/catalogue")
def catalogue(refresh: bool = False) -> dict[str, Any]:
    """The Sprint 3 artifact. Regenerated on ``?refresh=true``."""
    return _catalogue(refresh=refresh)


@app.get("/aliases")
def aliases() -> dict[str, Any]:
    """Credential alias **labels**, plus whether each currently resolves.

    Deliberately reports resolvability as a boolean and never the value, the
    length, or a masked form. The UI needs to grey out an alias nobody has
    registered; it does not need to know what the secret is.
    """
    config = _runtime_config()
    found = []
    for alias in _catalogue().get("credentialAliases", []):
        label = str(alias).lower().replace("_", "-")
        try:
            resolved = resolve_credential(label, config) is not None
        except CredentialResolutionError:
            resolved = False
        code_key, _ = credential_env_keys(label)
        found.append({"alias": label, "registered": resolved, "envKey": code_key})
    return {"aliases": found}


@app.post("/run")
def start_run(payload: dict[str, Any]) -> JSONResponse:
    """Validate a manifest, run it through the CLI, return the result document.

    Synchronous on purpose: a validation rig that returns a job id and makes you
    poll adds a state machine nobody needs for a run that takes seconds.
    """
    run_id = f"harness-{uuid.uuid4().hex[:12]}"
    config = _runtime_config()

    if not isinstance(payload, dict) or not payload.get("apis"):
        document = _aborted("request body must be a manifest with a non-empty apis[]", run_id)
        return JSONResponse(status_code=400, content=document)

    manifest = dict(payload)
    manifest.setdefault("runId", run_id)

    # Validate here so an invalid manifest never reaches a subprocess, and the
    # caller gets the same path-named errors the CLI would print.
    try:
        validate_manifest(manifest, registered_environments_from(config))
    except ManifestValidationError as error:
        document = _aborted(
            "manifest rejected", manifest.get("runId", run_id), detail=error.errors
        )
        _RUNS[run_id] = document
        return JSONResponse(status_code=422, content=document)

    with tempfile.TemporaryDirectory() as tmp:
        manifest_path = Path(tmp) / "manifest.json"
        out_path = Path(tmp) / "result.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        # A subprocess, not pytest.main() in-process: the tier caches its
        # operation cases for the life of the interpreter, so a second in-process
        # run would replay the first run's manifest.
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.global_contract.run",
                str(manifest_path),
                "--out",
                str(out_path),
                "--quiet",
            ],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=900,
        )

        if not out_path.exists():
            document = _aborted(
                "the run produced no result document",
                manifest.get("runId", run_id),
                detail=[completed.stderr.strip()[-500:]] if completed.stderr else [],
            )
            _RUNS[run_id] = document
            return JSONResponse(status_code=500, content=document)

        document = json.loads(out_path.read_text(encoding="utf-8"))

    document["harnessRunId"] = run_id
    document["startedAt"] = datetime.now(timezone.utc).isoformat()
    _RUNS[run_id] = document

    # COMPLETED and COMPLETED_WITH_ERRORS are both 200: the run happened. Only a
    # run that could not start is a transport-level failure.
    status_code = 200 if document.get("status") != RunStatus.ABORTED else 422
    return JSONResponse(status_code=status_code, content=document)


@app.get("/run/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    document = _RUNS.get(run_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"no run held for {run_id!r}")
    return document


@app.get("/runs")
def list_runs() -> dict[str, Any]:
    return {
        "runs": [
            {
                "harnessRunId": key,
                "runId": doc.get("runId"),
                "status": doc.get("status"),
                "startedAt": doc.get("startedAt"),
                "passRate": doc.get("summary", {}).get("passRate"),
            }
            for key, doc in _RUNS.items()
        ]
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if not UI_PATH.exists():
        raise HTTPException(status_code=404, detail="ui.html not found")
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))

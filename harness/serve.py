"""Entry point for the disposable local validation harness.

    python -m harness.serve [--port 8765]

Binds loopback only and refuses anything else — see :func:`assert_loopback`.
"""

from __future__ import annotations

import argparse

import uvicorn

from harness.service import HOST, PORT, assert_loopback


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harness.serve",
        description="Local validation harness (disposable; not the platform plugin).",
    )
    parser.add_argument("--host", default=HOST, help="Bind address. Loopback only.")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)

    # Checked before uvicorn starts, so a bad --host fails loudly rather than
    # quietly exposing UAT credentials to the network.
    assert_loopback(args.host)

    print(f"Local validation harness (DISPOSABLE)  ->  http://{args.host}:{args.port}")
    print("Not the platform plugin. Runs are in memory and vanish on exit.\n")
    uvicorn.run("harness.service:app", host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

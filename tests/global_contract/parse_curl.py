"""CLI: a cURL command in, a manifest ``definition`` block out.

    python -m tests.global_contract.parse_curl <file>
    python -m tests.global_contract.parse_curl -        # read stdin

The engine owns cURL parsing. ``docs/platform-handoff/README.md`` used to tell
the platform to parse the upload itself, which would have meant a second parser
reimplementing -- or forgetting -- the one behaviour here that is not cosmetic:

**Authorization never survives the parse.** People paste working commands, and
working commands carry live tokens. ``Authorization``, ``Proxy-Authorization``,
``Cookie`` and ``-u/--user`` credentials are discarded at parse time. They do not
reach the definition, the stored ``cURL`` text, a warning, an error message, or
this command's output. The endpoint's *need* for auth survives as
``"Auth Type": "Bearer Token"``; the credential itself comes from the manifest's
``credentialAlias`` at run time.

A parser that gets this wrong leaks a token into whatever consumes its output,
which is why this is a CLI to shell out to rather than a spec to reimplement.

A leading block of ``#`` comment lines is ignored, so a saved command can carry
a note about where it came from. Scanning stops at the first non-comment line,
so a ``#`` inside a body or a URL fragment is never touched.

Exit codes
----------
``0`` parsed, ``2`` the command could not be parsed, ``3`` this tool broke.
Warnings go to stderr so stdout stays pipeable straight into a manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.global_contract.curl_adapter import (  # noqa: E402
    CurlParseError,
    curl_to_definition,
)
from tests.global_contract.run_manifest import (  # noqa: E402
    definition_to_manifest_block,
)

EXIT_OK = 0
EXIT_UNPARSEABLE = 2
EXIT_INTERNAL_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tests.global_contract.parse_curl",
        description=(
            "Parse a cURL command into a manifest 'definition' block. "
            "Authorization headers and -u credentials are discarded, never emitted."
        ),
    )
    parser.add_argument(
        "source",
        help="file containing the cURL command, or '-' to read stdin",
    )
    parser.add_argument("--api-id", default="", help="API ID for the definition")
    parser.add_argument("--name", default="", help="API / Feature Name")
    parser.add_argument("--module", default="", help="Module")
    parser.add_argument(
        "--entry",
        action="store_true",
        help=(
            "wrap the block as a complete manifest apis[] entry, so the output "
            "can be dropped straight in alongside a credentialAlias"
        ),
    )
    parser.add_argument(
        "--credential-alias",
        default="",
        help="credentialAlias to put on the --entry wrapper (a label, never a secret)",
    )
    parser.add_argument(
        "--auth-provider-api-id",
        default="",
        help="authProviderApiId to put on the --entry wrapper",
    )
    return parser


def _strip_header_comments(text: str) -> str:
    """Drop a leading block of ``#`` comment lines.

    A saved cURL command usually arrives with a note above it saying where it
    came from. Only the *leading* block is removed, and scanning stops at the
    first line that is neither blank nor a comment -- so a ``#`` inside a body,
    a URL fragment, or a quoted string further down is never touched.
    """
    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("#"):
            break
        index += 1
    return "".join(lines[index:])


def _read_command(source: str) -> str:
    if source == "-":
        return _strip_header_comments(sys.stdin.read())
    path = Path(source)
    if not path.is_file():
        raise CurlParseError(f"no such file: {source}")
    return _strip_header_comments(path.read_text(encoding="utf-8-sig"))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        command = _read_command(args.source)
    except CurlParseError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_UNPARSEABLE
    except OSError as error:
        # Only the filename and the errno reach stderr. The file's *contents*
        # are the thing that might carry a token, and they are never echoed.
        print(f"error: could not read {args.source}: {error.strerror}", file=sys.stderr)
        return EXIT_UNPARSEABLE

    try:
        definition, warnings = curl_to_definition(
            command, api_id=args.api_id, name=args.name, module=args.module
        )
    except CurlParseError as error:
        # curl_adapter guarantees this message names headers, never their
        # values, so it is safe to print.
        print(f"error: {error}", file=sys.stderr)
        return EXIT_UNPARSEABLE
    except Exception as error:  # pragma: no cover - defensive
        # Deliberately does not print the exception message: an unforeseen
        # failure deep in parsing could have interpolated part of the command,
        # and the command is the thing holding the token. The type is enough
        # to file a bug against.
        print(
            f"error: the parser failed with {type(error).__name__}; "
            "the command is not echoed",
            file=sys.stderr,
        )
        return EXIT_INTERNAL_ERROR

    block = definition_to_manifest_block(definition)

    if args.entry:
        entry: dict[str, object] = {"definition": block}
        if args.credential_alias:
            entry["credentialAlias"] = args.credential_alias
        if args.auth_provider_api_id:
            entry["authProviderApiId"] = args.auth_provider_api_id
        payload: object = entry
    else:
        payload = block

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

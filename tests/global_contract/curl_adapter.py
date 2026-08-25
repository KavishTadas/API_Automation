"""cURL upload -> API definition.

``scripts/generate-api-file.js`` already parses Postman and Bruno sources; cURL
is the new one. A pasted command is parsed into the same
:class:`~tests.global_contract.metadata_resolver.ApiDefinition` and the same
``API_File.json``-shaped request row the Excel adapter produces, so everything
downstream is source-agnostic.

A cURL-only API carries no test cases of its own — there is no template sheet
behind it — so it runs the global contract tier and nothing else.

Authorization is stripped, not stored
-------------------------------------
People paste working commands, and working commands carry live tokens. Any
``Authorization`` header (and any ``-u/--user`` credential pair) is discarded at
parse time: it never reaches the definition, the request row, a log, a report,
or an Allure attachment. Auth comes from the manifest's ``credentialAlias`` and
``authProviderApiId`` instead. The discarded header is reported by name only —
never by value.
"""

from __future__ import annotations

import json
import re
import shlex
from urllib.parse import urlsplit

from tests.global_contract.metadata_resolver import (
    DEFAULT_CONTENT_TYPE,
    ApiDefinition,
    PayloadType,
    SamplePayload,
    build_request_parameters,
    definition_to_inventory_row,
    error_trigger_rows,
)


__all__ = [
    "CurlParseError",
    "ParsedCurl",
    "definition_to_inventory_row",
    "error_trigger_rows",
    "parse_curl",
    "curl_to_inventory_row",
]


#: Headers that are dropped rather than carried into a definition.
_STRIPPED_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie"})

_BODY_FLAGS = frozenset(
    {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"}
)

#: Flags that take a value we do not model. Their argument must still be
#: consumed, or it would be mistaken for the URL.
_VALUE_FLAGS_IGNORED = frozenset(
    {
        "-o", "--output", "-A", "--user-agent", "-e", "--referer", "--connect-timeout",
        "-m", "--max-time", "--retry", "--cacert", "--cert", "--key", "--resolve",
        "-b", "--cookie", "-c", "--cookie-jar", "--proxy", "-x", "--url",
    }
)


class CurlParseError(ValueError):
    """A cURL command could not be parsed. Carries a message, not a traceback."""


class ParsedCurl:
    """The pieces of a cURL command this engine models."""

    def __init__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: str,
        query: dict[str, str],
        stripped_headers: tuple[str, ...],
    ) -> None:
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.query = query
        #: Names only. Values are discarded at parse time and never retained.
        self.stripped_headers = stripped_headers

    def __repr__(self) -> str:
        return (
            f"ParsedCurl(method={self.method!r}, url={self.url!r}, "
            f"headers={sorted(self.headers)}, has_body={bool(self.body)}, "
            f"stripped={list(self.stripped_headers)})"
        )


def _tokenize(command: str) -> list[str]:
    """Split a cURL command into shell tokens, tolerating line continuations."""
    text = str(command or "").strip()
    if not text:
        raise CurlParseError("cURL command is empty")

    # Shell (`\`), PowerShell (`` ` ``) and cmd (`^`) line continuations.
    text = re.sub(r"[\\`^]\s*\r?\n", " ", text)
    text = re.sub(r"\s*\r?\n\s*", " ", text)

    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as error:
        raise CurlParseError(
            f"cURL command could not be tokenized ({error}); check for an unclosed quote"
        ) from error

    if not tokens:
        raise CurlParseError("cURL command is empty")
    if tokens[0].lower() not in {"curl", "curl.exe"}:
        raise CurlParseError(
            f"expected the command to start with 'curl', got {tokens[0]!r}"
        )
    return tokens[1:]


def parse_curl(command: str) -> ParsedCurl:
    """Parse a cURL command. Raises :class:`CurlParseError` with a clear message."""
    tokens = _tokenize(command)

    method = ""
    url = ""
    headers: dict[str, str] = {}
    stripped: list[str] = []
    body_parts: list[str] = []

    index = 0
    while index < len(tokens):
        token = tokens[index]

        if token in {"-X", "--request"}:
            index += 1
            if index >= len(tokens):
                raise CurlParseError("-X/--request was given without a method")
            method = tokens[index].upper()

        elif token in {"-H", "--header"}:
            index += 1
            if index >= len(tokens):
                raise CurlParseError("-H/--header was given without a header")
            raw_header = tokens[index]
            if ":" not in raw_header:
                raise CurlParseError(
                    f"header {raw_header!r} is not in 'Name: value' form"
                )
            name, value = raw_header.split(":", 1)
            name = name.strip()
            if name.lower() in _STRIPPED_HEADERS:
                # Discarded here and never bound to a variable that outlives
                # this branch. Only the name is retained, for reporting.
                stripped.append(name)
            elif name:
                headers[name] = value.strip()

        elif token in _BODY_FLAGS:
            index += 1
            if index >= len(tokens):
                raise CurlParseError(f"{token} was given without a body")
            body_parts.append(tokens[index])

        elif token in {"-u", "--user"}:
            index += 1
            if index >= len(tokens):
                raise CurlParseError(f"{token} was given without a credential")
            # Basic-auth credentials are discarded exactly like Authorization.
            stripped.append("Authorization (from -u/--user)")

        elif token in _VALUE_FLAGS_IGNORED:
            index += 1  # consume the argument so it is not mistaken for the URL

        elif token.startswith("-"):
            pass  # a valueless switch such as -s, -k, -L, --compressed

        elif not url:
            url = token

        index += 1

    if not url:
        raise CurlParseError("no request URL found in the cURL command")

    split = urlsplit(url if "://" in url else f"https://{url}")
    if not split.netloc:
        raise CurlParseError(f"request URL {url!r} has no host")

    query: dict[str, str] = {}
    if split.query:
        for pair in split.query.split("&"):
            if not pair:
                continue
            key, _, value = pair.partition("=")
            if key:
                query[key] = value

    body = "&".join(body_parts) if body_parts else ""
    if not method:
        # cURL's own rule: a body implies POST unless -X says otherwise.
        method = "POST" if body else "GET"

    return ParsedCurl(
        method=method,
        url=f"{split.scheme}://{split.netloc}",
        headers=headers,
        body=body,
        query=query,
        stripped_headers=tuple(stripped),
    )


def _path_of(command_url: str, original: str) -> str:
    split = urlsplit(original if "://" in original else f"https://{original}")
    return split.path or "/"


def curl_to_definition(
    command: str,
    *,
    api_id: str = "",
    name: str = "",
    module: str = "",
) -> tuple[ApiDefinition, tuple[str, ...]]:
    """Parse a cURL command into a definition plus non-fatal warnings."""
    parsed = parse_curl(command)

    # Recover the path from the original URL text; parse_curl keeps only the
    # scheme and host on `url` so the base URL stays independently resolvable.
    tokens = _tokenize(command)
    original_url = next(
        (
            t
            for i, t in enumerate(tokens)
            if not t.startswith("-")
            and (i == 0 or tokens[i - 1] not in _VALUE_FLAGS_IGNORED | _BODY_FLAGS
                 | {"-X", "--request", "-H", "--header", "-u", "--user"})
        ),
        "",
    )
    path = _path_of(parsed.url, original_url or parsed.url)

    auth_type = "None"
    if any(h.lower() == "authorization" for h in parsed.stripped_headers) or any(
        h.startswith("Authorization") for h in parsed.stripped_headers
    ):
        # The command proved the endpoint is secured even though the value is
        # gone, so the definition still declares that it needs a bearer token.
        auth_type = "Bearer Token"

    payloads: list[SamplePayload] = []
    if parsed.body:
        payloads.append(
            SamplePayload(
                payload_type=PayloadType.REQUEST_BODY,
                response_status=None,
                sample_json=_body_value(parsed.body),
            )
        )

    warnings: list[str] = []
    if parsed.stripped_headers:
        warnings.append(
            "curl-authorization-stripped api_id="
            f"{api_id or path!r}: discarded {', '.join(sorted(set(parsed.stripped_headers)))} "
            "(value not retained); auth comes from credentialAlias instead"
        )

    definition = ApiDefinition(
        api_id=api_id,
        name=name or f"{parsed.method} {path}",
        module=module,
        method=parsed.method,
        path=path,
        base_url=parsed.url,
        auth_type=auth_type,
        curl=_redacted_curl(command),
        payloads=tuple(payloads),
    )
    return definition, tuple(warnings)


def _body_value(body: str):
    """Return the body as parsed JSON when it is JSON, else as raw text."""
    try:
        return json.loads(body)
    except (TypeError, ValueError):
        return body


def _redacted_curl(command: str) -> str:
    """Store the command with any Authorization/-u value replaced.

    The original text is never retained anywhere, so a definition that is later
    logged or attached to a report cannot leak the pasted token.
    """
    redacted = re.sub(
        r"(-H|--header)(\s+)(['\"]?)\s*(authorization|proxy-authorization|cookie)\s*:[^'\"]*\3",
        r"\1\2\3\4: <redacted>\3",
        str(command or ""),
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"(-u|--user)(\s+)(['\"]?)[^\s'\"]+\3",
        r"\1\2\3<redacted>\3",
        redacted,
        flags=re.IGNORECASE,
    )


def curl_to_inventory_row(
    command: str,
    *,
    api_id: str = "",
    name: str = "",
    module: str = "",
) -> tuple[dict, ApiDefinition, tuple[str, ...]]:
    """Parse a cURL command into ``(inventory_row, definition, warnings)``."""
    definition, warnings = curl_to_definition(
        command, api_id=api_id, name=name, module=module
    )
    parsed = parse_curl(command)

    row = definition_to_inventory_row(definition, source="uploaded/curl")

    headers = dict(parsed.headers)
    if definition.payloads and "Content-Type" not in headers:
        headers["Content-Type"] = DEFAULT_CONTENT_TYPE
    if str(definition.auth_type).lower().startswith("bearer"):
        headers["Authorization"] = "Bearer {{authToken}}"

    row["Request Parameters"] = build_request_parameters(
        headers=headers, query=parsed.query
    )
    return row, definition, warnings

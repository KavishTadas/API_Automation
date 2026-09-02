#!/usr/bin/env python3
"""Fail the build if a credential-shaped string is committed.

This repository is public and published a working password for months. The
cleanup that removed it is worth far less than this file, because this is the
part that stops the next one.

Two things are looked for:

  * a password/secret/token assignment whose value is a real value rather than
    a placeholder, and
  * a JWT whose payload actually base64-decodes to JSON -- a synthetic token
    like ``eyJhbGciOiJIUzI1NiJ9.FAKE0NOTAREAL.sig`` does not, which is what
    separates a planted fixture from a leaked credential without needing to
    know anything about the file it lives in.

Exemptions live in ``.credential-scan-allow`` next to this script's repo root,
one ``path # reason`` per line. They are deliberately data in the repository
rather than a rule in the code: an exemption nobody can see in a diff is an
exemption nobody reviews. The redaction regression tests need planted tokens to
have anything to redact, and that is a reason worth writing down.

Usage:  python scripts/scan-credentials.py [--staged]
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW_FILE = ROOT / ".credential-scan-allow"

# A value that is obviously a stand-in rather than a credential.
PLACEHOLDER = re.compile(
    r"^\s*(\$\{[^}]+\}|<[^>]+>|your_[a-z_]+|changeme|placeholder|redacted|xxx+|"
    # masked in a mock-up: asterisks, bullets, or middle dots
    r"[\*•·∙●]+|"
    r"\{\{[^}]+\}\}|null|none|empty|test|dummy|example)",
    re.IGNORECASE,
)

ASSIGNMENT = re.compile(
    # Not a property access and not a --css-var. Word characters are allowed
    # before the key so that EMP_PASSWORD= and empPassword: both match; the
    # code-shaped values those forms produce are rejected by CODE_LIKE below.
    r"(?<![.\-])"
    r"(?i:pass(?:word|wd)?|pwd|empPassword|secret|api[_-]?key|client[_-]?secret)"
    # an optional closing quote, so "password": "..." matches as well as password=...
    r"""["']?\s*[:=]\s*"""
    # the value: double-quoted, single-quoted, or bare
    r"""(?:"([^"\n]{6,})"|'([^'\n]{6,})'|([^\s"',;)\]}]{6,}))"""
)

# A value that is plainly code rather than a credential: a property access, a
# call, a variable, an interpolation, a CSS token, a colour.
CODE_LIKE = re.compile(
    r"""(?x)
      [()\[\]{}$<>] | ^-- | ^\# | ^[A-Z][A-Za-z0-9]*\. | \.\w
    | ^(?:process|os|self|this|config|env)
    | ^[A-Z0-9_]+$                                  # a constant or env-var NAME
    | ^[0-9a-fA-F]{6,8}$                            # a hex colour
    | \s
    """
)

# The shape of a credential: mixed classes, no whitespace, not a bare word.
def looks_like_secret(value: str) -> bool:
    if PLACEHOLDER.match(value) or CODE_LIKE.search(value):
        return False
    has_upper = any(c.isupper() for c in value)
    has_digit = any(c.isdigit() for c in value)
    # Underscore and hyphen are excluded deliberately: with them counted, every
    # snake_case variable passed as a value reads as a credential, and a
    # scanner that cries wolf is a scanner somebody switches off.
    has_symbol = any(not c.isalnum() and c not in "_-" for c in value)
    return has_symbol or (has_upper and has_digit)


JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.([A-Za-z0-9_-]{6,})\.[A-Za-z0-9_-]*")

# Binary and vendored trees are never worth scanning.
SKIP_SUFFIX = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".zip", ".gz",
    ".woff", ".woff2", ".ttf", ".eot", ".xlsx", ".docx", ".jar", ".class",
}
SKIP_PARTS = {"node_modules", ".venv", ".git", "allure-results", "allure-report"}


def load_allowlist() -> dict[str, str]:
    allowed: dict[str, str] = {}
    if not ALLOW_FILE.exists():
        return allowed
    for raw in ALLOW_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, _, reason = line.partition("#")
        allowed[path.strip().replace("\\", "/")] = reason.strip() or "(no reason given)"
    return allowed


def decodes_to_json(segment: str) -> bool:
    """A real JWT payload is base64url JSON. A planted one is rarely both."""
    padded = segment + "=" * (-len(segment) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
    except Exception:
        return False
    try:
        return isinstance(json.loads(raw), dict)
    except Exception:
        return False


def tracked_files(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"] if staged \
        else ["git", "ls-files"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def scan() -> int:
    staged = "--staged" in sys.argv
    allowed = load_allowlist()
    findings: list[tuple[str, int, str]] = []
    scanned = 0

    for rel in tracked_files(staged):
        path = ROOT / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in SKIP_SUFFIX or SKIP_PARTS & set(Path(rel).parts):
            continue
        if rel.replace("\\", "/") in allowed:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1

        for n, line in enumerate(text.splitlines(), 1):
            for groups in ASSIGNMENT.findall(line):
                value = next((g for g in groups if g), "")
                if not value or not looks_like_secret(value):
                    continue
                findings.append((rel, n, f"password-shaped literal: {value[:24]}"))
            for payload in JWT.findall(line):
                if decodes_to_json(payload):
                    findings.append((rel, n, "JWT with a decodable payload"))

    if not findings:
        print(f"No credential-shaped string in {scanned} tracked file(s).")
        if allowed:
            print(f"{len(allowed)} path(s) exempt via .credential-scan-allow.")
        return 0

    print(f"{len(findings)} credential-shaped string(s) found:\n")
    for rel, n, why in findings[:40]:
        print(f"  {rel}:{n}  {why}")
    if len(findings) > 40:
        print(f"  ... and {len(findings) - 40} more")
    print(
        "\nCommitting a credential to this repository is not reversible: it is "
        "public, and history rewriting does not un-publish anything already "
        "scraped. Replace the value with a ${PLACEHOLDER} read from .env, or "
        "add the path to .credential-scan-allow with a reason if it is a "
        "deliberately planted test fixture."
    )
    return 1


if __name__ == "__main__":
    sys.exit(scan())

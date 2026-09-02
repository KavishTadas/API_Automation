"""The one place a catalogue ref becomes a filesystem-safe endpoint slug.

Every consumer imports from here. A second implementation is how the two copies
drift, and a slug that drifts silently renames a directory that a human has been
authoring test cases into -- so there is exactly one.

Identity
--------
A catalogue ref is ``method|path|module|sub-module``. The slug deliberately keys
on the first *three* components only, because the fourth is the **test case**,
not the endpoint. ``POST /auth/token`` carries three cases (valid credentials,
invalid empCode, missing password); they are one endpoint with three cases, and
the case belongs under that endpoint's case directory rather than as three
sibling endpoint definitions. 45 catalogue rows resolve to 41 endpoints.

Failure modes are hard errors, never repairs
--------------------------------------------
Two things must stop generation rather than be worked around:

* **Collisions.** Silently overwriting means one endpoint's definition
  disappears and the authored cases beneath it are orphaned.
* **Over-length slugs.** Truncating or hashing produces a name nobody can read
  back to an endpoint, and the truncated forms collide with each other. The fix
  is an entry in ``api-endpoints/module-aliases.yaml``.

``MAX_SLUG_LENGTH`` is 85. The longest real slug today is 84
(``holiday_template_delete_api_attendance_holiday_templates_delete_by_holidaytemplateid``),
so the ceiling fails loudly on something genuinely new rather than on the
existing tree. It is not 60: the path alone accounts for 59 characters there, so
no module alias could ever satisfy 60 -- see PHASE2_REPORT.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


__all__ = [
    "MAX_SLUG_LENGTH",
    "ALIAS_PATH",
    "SlugCollisionError",
    "SlugTooLongError",
    "load_aliases",
    "slugify",
    "build_slug_map",
]

#: Ceiling for a generated slug. Exceeding it is a hard error; fix with an alias.
MAX_SLUG_LENGTH = 85

ROOT_DIR = Path(__file__).resolve().parents[2]
ALIAS_PATH = ROOT_DIR / "api-endpoints" / "module-aliases.yaml"

_PATH_PARAM = re.compile(r"\{([^}]+)\}")
_NOT_SLUG_SAFE = re.compile(r"[^a-z0-9_]")
_RUNS = re.compile(r"_+")


class SlugCollisionError(Exception):
    """Two distinct endpoints produced the same slug."""


class SlugTooLongError(Exception):
    """A slug exceeded MAX_SLUG_LENGTH. Add a module alias; never truncate."""


def load_aliases(path: Path | None = None) -> dict[str, str]:
    """Read the committed module alias map.

    Aliases apply to **slug derivation only**. They never touch ``canonicalRef``,
    which stays byte-identical to catalogue output -- misspellings included --
    because the ref is contract-visible and reminting it is a separate decision.
    """
    alias_path = path or ALIAS_PATH
    if not alias_path.exists():
        return {}
    loaded = yaml.safe_load(alias_path.read_text(encoding="utf-8")) or {}
    aliases = loaded.get("aliases") or {}
    return {str(k).strip().lower(): str(v).strip() for k, v in aliases.items()}


def slugify(module: str, method: str, path: str, aliases: Mapping[str, str]) -> str:
    """Derive the filesystem-safe slug for one endpoint.

    Length is *not* checked here -- ``build_slug_map`` enforces the ceiling once
    it can report every offender together, which is more useful than failing on
    whichever happened to be encountered first.
    """
    resolved = aliases.get(module.strip().lower(), module)
    # {holidayTemplateId} -> by_holidaytemplateid, so a path parameter reads as
    # one and does not collapse into an anonymous underscore run.
    expanded = _PATH_PARAM.sub(lambda m: f"by_{m.group(1).lower()}", path)
    raw = f"{resolved}__{method}_{expanded}".lower().replace("/", "_")
    # The "__" module separator does not survive: §4 also mandates collapsing
    # runs of "_", and collapse wins. Keeping it would add a character to every
    # slug and push the longest real one to exactly MAX_SLUG_LENGTH. The
    # module boundary is recoverable from api-docs/ref-to-slug.json, which
    # exists precisely so nobody has to reconstruct it by eye.
    return _RUNS.sub("_", _NOT_SLUG_SAFE.sub("_", raw)).strip("_")


def build_slug_map(
    rows: Iterable[Mapping[str, Any]],
    aliases: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Map every catalogue ref to its endpoint slug, or raise.

    Rows sharing a ``(module, method, path)`` map to the same slug by design --
    those are test cases on one endpoint. A collision is only a collision when
    two *different* endpoint keys collide.
    """
    resolved_aliases = dict(aliases if aliases is not None else load_aliases())

    ref_to_slug: dict[str, str] = {}
    slug_to_key: dict[str, tuple[str, str, str]] = {}
    collisions: list[str] = []

    for row in rows:
        module = str(row["module"])
        method = str(row["method"]).upper()
        path = str(row["path"])
        key = (module.strip().lower(), method, path)
        slug = slugify(module, method, path, resolved_aliases)

        existing = slug_to_key.get(slug)
        if existing is not None and existing != key:
            collisions.append(f"{slug}\n    {existing}\n    {key}")
        slug_to_key[slug] = key
        ref_to_slug[str(row["ref"])] = slug

    if collisions:
        raise SlugCollisionError(
            "distinct endpoints produced the same slug:\n  "
            + "\n  ".join(collisions)
        )

    too_long = sorted(
        ((len(s), s) for s in slug_to_key if len(s) > MAX_SLUG_LENGTH), reverse=True
    )
    if too_long:
        listed = "\n  ".join(f"{n} chars  {s}" for n, s in too_long)
        raise SlugTooLongError(
            f"{len(too_long)} slug(s) exceed {MAX_SLUG_LENGTH} characters:\n  "
            f"{listed}\n\nAdd a module alias in {ALIAS_PATH.name}. "
            "Never truncate and never hash."
        )

    return ref_to_slug

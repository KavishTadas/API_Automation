#!/usr/bin/env python3
"""Publish Bruno requests to the ui-console branch, rebuilding what they feed.

Saving a .bru in Bruno puts it on this machine and nowhere else. Until it is on
the branch, no teammate and no CI run can see it -- the console had an endpoint
for hours that existed only in one working copy. This is the step that ends
that, and it is a script rather than a note in a README because the order
matters: generate before committing, or the branch carries a .bru whose endpoint
is missing from the console committed beside it.

What it refuses to do, and why:

* **Push to main.** main is the finished branch. A Bruno request is work in
  progress by definition, so it goes to ui-console and reaches main through a
  pull request like anything else.
* **Push anything credential-shaped.** This repository published a working
  password once. scan-credentials.py runs before the commit, not after, so a
  pasted token in a .bru stops here rather than on GitHub.
* **Commit when nothing changed.** An empty commit per save would bury the
  history and retrigger CI for nothing.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "ui-console"

#: Run in this order. Each reads what the one before it wrote; a .bru committed
#: without them is a request the console does not know about.
GENERATORS = (
    ("node", "scripts/generate-api-file.js"),
    # Twice, and the first one is not redundant. generate-endpoint-yaml.py
    # decides what to prune and what to promote from the catalogue, and the
    # catalogue is read out of build/API_File.json -- which the *other*
    # generator writes. Left stale, it still lists an endpoint whose .bru was
    # just deleted, so the deletion took two runs to converge and a newly added
    # request was skipped as a duplicate of the endpoint that was on its way
    # out. Rebuilding first makes one run enough.
    (sys.executable, "scripts/generate-generic-tests.py"),
    (sys.executable, "scripts/generate-endpoint-yaml.py"),
    (sys.executable, "scripts/generate-generic-tests.py"),
    # A second pass. Pruning removes the definition, but the catalogue is read
    # from build/API_File.json, so the removal is only visible once that file
    # has been rewritten -- which the step above just did. Without this, a
    # deleted .bru left its definition behind until somebody happened to run
    # the generators again.
    (sys.executable, "scripts/generate-endpoint-yaml.py"),
    (sys.executable, "scripts/generate-generic-tests.py"),
    (sys.executable, "scripts/build_unified_console.py"),
)

#: Exactly what CI stages, plus the Bruno sources themselves. api-endpoints/
#: and build/ are tracked generated files: leave them out and the next run
#: rebuilds the console from a stale inventory and undoes this one.
STAGED = (
    "bruno/",
    "api-docs/API_File.json",
    "api-docs/API_File.csv",
    "api-endpoints/",
    "api-docs/ref-to-slug.json",
    "build/API_File.json",
    "build/auto_generated/",
    "docs/platform-ui/unified-console.html",
    "docs/platform-handoff/sample-catalogue.json",
    "test-cases/endpoint/",
)


def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=ROOT, text=True,
        capture_output=capture, check=False,
    )


def git(*args: str, capture: bool = True) -> str:
    proc = run(["git", *args], capture=capture)
    if proc.returncode != 0 and capture:
        raise SystemExit(f"git {' '.join(args)} failed:\n{proc.stderr}")
    return (proc.stdout or "").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/publish-bruno.py",
        description="Regenerate, then commit and push Bruno requests to ui-console.",
    )
    parser.add_argument("-m", "--message", default="", help="commit subject")
    parser.add_argument("--no-push", action="store_true",
                        help="commit only; leave pushing to you")
    args = parser.parse_args(argv)

    branch = git("branch", "--show-current")
    if branch != BRANCH:
        print(f"On '{branch}', not '{BRANCH}'.")
        print(f"Bruno work belongs on {BRANCH}; main is the finished branch.")
        print(f"  git switch {BRANCH}")
        return 2

    print(f"1/4  regenerating on {branch}")
    for cmd in GENERATORS:
        name = Path(cmd[1]).name
        proc = run(list(cmd), capture=True)
        if proc.returncode != 0:
            print(f"     {name} failed:\n{proc.stdout}\n{proc.stderr}")
            return 1
        for line in (proc.stdout or "").splitlines():
            keep = ("promoted", "PRUNED", "SKIPPED", "WARNING")
            if line.startswith(keep) or "refs ->" in line:
                print(f"     {line}")

    print("2/4  staging")
    git("add", "--", *STAGED)
    if not git("diff", "--cached", "--name-only"):
        print("     nothing changed - no commit made")
        return 0

    # Staged first, deliberately. The scanner walks `git ls-files` by default,
    # and a brand-new .bru is untracked until it is added -- so scanning before
    # staging is exactly blind to the file most likely to carry a pasted token.
    print("3/4  scanning what is staged")
    if run([sys.executable, "scripts/scan-credentials.py", "--staged"],
           capture=True).returncode != 0:
        run(["git", "reset", "--quiet", "HEAD", "--"], capture=True)
        print("     REFUSED: something credential-shaped is staged. Nothing committed.")
        print("     Use {{authToken}} / {{empPassword}}, never a literal value.")
        return 1
    print("     clean")

    print("    committing")

    added = [p for p in git("diff", "--cached", "--name-only").splitlines()
             if p.startswith("bruno/") and p.endswith(".bru")]
    subject = args.message or (
        f"Publish {len(added)} Bruno request(s) and the console they rebuild"
        if added else "Rebuild the console from the Bruno collection"
    )
    body = (
        "Generated by scripts/publish-bruno.py: the inventory, endpoint\n"
        "definitions, derived inventory and console are regenerated together, so\n"
        "the branch never carries a .bru whose endpoint is missing from the\n"
        "console committed beside it.\n"
    )
    if added:
        body += "\n" + "\n".join(f"  {p}" for p in added) + "\n"
    committed = run(["git", "commit", "-m", subject, "-m", body], capture=True)
    if committed.returncode != 0:
        print("     commit refused:")
        print((committed.stdout or "") + (committed.stderr or ""))
        return 1
    print(f"     {git('log', '-1', '--format=%h %s')}")

    if args.no_push:
        print("4/4  not pushing (--no-push)")
        return 0

    print(f"4/4  pushing to origin/{BRANCH}")
    proc = run(["git", "push", "-u", "origin", BRANCH], capture=True)
    if proc.returncode != 0:
        print(proc.stderr.strip())
        return 1
    print(f"     pushed. GitHub now has it on {BRANCH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

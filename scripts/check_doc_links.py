#!/usr/bin/env python3
"""Verify relative markdown links across git-tracked docs.

A link fails if its target is not tracked by git. This catches both genuinely
broken links and links to gitignored (private) files, which would 404 on
GitHub even though they exist locally.

Usage: poetry run python scripts/check_doc_links.py
Exit code 0 = all links resolve; 1 = failures (printed one per line).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return set(out.splitlines())


def main() -> int:
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
    os.chdir(root)
    tracked = tracked_files()
    tracked_dirs: set[str] = set()
    for path in tracked:
        parent = os.path.dirname(path)
        while parent:
            tracked_dirs.add(parent)
            parent = os.path.dirname(parent)
    failures: list[str] = []

    for md in sorted(p for p in tracked if p.endswith(".md")):
        text = Path(md).read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            raw = match.group(1)
            if raw.startswith(SKIP_PREFIXES):
                continue
            target = raw.split("#", 1)[0]
            if not target:
                continue
            base = "" if target.startswith("/") else os.path.dirname(md)
            norm = os.path.normpath(os.path.join(base, target.lstrip("/")))
            if norm not in tracked and norm not in tracked_dirs:
                failures.append(f"{md}: broken or untracked link -> {raw}")

    for failure in failures:
        print(failure)
    print(f"\n{len(failures)} bad link(s)." if failures else "All links OK.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Bump the project version across all files that embed it.

Usage:
    python scripts/bump_version.py 0.2.0
"""

import re
import sys
from pathlib import Path
from typing import Callable, List, Tuple, Union

REPO = Path(__file__).resolve().parent.parent

Sub = Tuple[str, Union[str, Callable]]


def _dotquad(v: str) -> str:
    """'1.2.3' → '1.2.3.0'  (Windows 4-part version string)"""
    return ".".join((v.split(".") + ["0", "0", "0"])[:4])


def _tuple4(v: str) -> str:
    """'1.2.3' → '(1, 2, 3, 0)'  (PyInstaller FixedFileInfo tuple)"""
    parts = (v.split(".") + ["0", "0", "0"])[:4]
    return "({})".format(", ".join(parts))


def _patch(path: Path, subs: List[Sub]) -> bool:
    text = path.read_text(encoding="utf-8")
    result = text
    for pattern, repl in subs:
        result = re.sub(pattern, repl, result, flags=re.MULTILINE)
    if result == text:
        return False
    path.write_text(result, encoding="utf-8")
    return True


def main() -> None:
    if len(sys.argv) != 2 or not re.match(r"^\d+\.\d+\.\d+$", sys.argv[1]):
        sys.exit("Usage: python scripts/bump_version.py <major>.<minor>.<patch>")

    v    = sys.argv[1]
    quad = _dotquad(v)
    tup  = _tuple4(v)

    targets: List[Tuple[Path, List[Sub]]] = [
        (
            REPO / "pyproject.toml",
            [(r'^(version\s*=\s*")[^"]+(")', rf'\g<1>{v}\g<2>')],
        ),
        (
            REPO / "valscanner/__init__.py",
            [(r'^(__version__\s*=\s*")[^"]+(")', rf'\g<1>{v}\g<2>')],
        ),
        (
            REPO / "valscanner.spec",
            [(r'^(VERSION\s*=\s*")[^"]+(")', rf'\g<1>{v}\g<2>')],
        ),
        (
            REPO / "scripts/build_app.sh",
            [(r'^(VERSION=")[^"]+(")$', rf'\g<1>{v}\g<2>')],
        ),
        (
            REPO / "scripts/build_app.ps1",
            [(r'^(\$Version\s*=\s*")[^"]+(")$', rf'\g<1>{v}\g<2>')],
        ),
        (
            REPO / "assets/windows_version_info.txt",
            [
                (
                    r'\b(filevers|prodvers)\s*=\s*\([^)]+\)',
                    lambda m: f'{m.group(1)}={tup}',
                ),
                (
                    r"(StringStruct\('(?:FileVersion|ProductVersion)',\s*')[^']+(')",
                    rf'\g<1>{quad}\g<2>',
                ),
            ],
        ),
    ]

    width = max(len(str(p.relative_to(REPO))) for p, _ in targets)
    updated_count = 0
    for path, subs in targets:
        rel = str(path.relative_to(REPO))
        ok = _patch(path, subs)
        status = "updated" if ok else "no change"
        print(f"  {status:9}  {rel}")
        if ok:
            updated_count += 1

    print(f"\n{updated_count}/{len(targets)} files updated → {v}")


if __name__ == "__main__":
    main()

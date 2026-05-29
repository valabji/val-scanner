#!/usr/bin/env python3
"""Bump the project version across all files that embed it.

Usage:
    python scripts/bump_version.py 0.2.0
    python scripts/bump_version.py 0.2.0 --no-notes   # skip release notes

After patching the version files, this also shells out to Claude Code
(`claude -p`) to draft `release-notes/vX.Y.Z.md` from the commits since the
previous tag and `release-notes/TEMPLATE.md`. The draft is a starting point —
review and edit it before publishing.
"""

import datetime
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

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


def _git(*args: str) -> str:
    """Run a read-only git command in the repo and return stdout (stripped)."""
    out = subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _previous_tag() -> Optional[str]:
    """Most recent reachable tag (the previous release), or None if untagged."""
    try:
        return _git("describe", "--tags", "--abbrev=0") or None
    except subprocess.CalledProcessError:
        return None


def _release_kind(prev: Optional[str], v: str) -> str:
    """Classify the bump prev → v for the template's Status line."""
    if prev is None:
        return "Minor release"
    old = re.sub(r"^v", "", prev).split(".")
    new = v.split(".")
    if len(old) < 3:
        return "Minor release"
    if old[0] != new[0]:
        return "Major release"
    if old[1] != new[1]:
        return "Minor release"
    return "Patch release"


# Paths whose diffs are noise for release notes (lockfiles, vendored assets,
# the version-bump churn itself, the notes dir). Excluded from the patch body.
_DIFF_EXCLUDE = [
    ":(exclude)*.lock",
    ":(exclude)*-lock.json",
    ":(exclude)*.lock.json",
    ":(exclude)release-notes/**",
]

# Cap the patch fed to the model so a huge release can't blow up the prompt.
_DIFF_CHAR_BUDGET = 200_000


def _collect_diff(prev: Optional[str]) -> str:
    """Full patch since `prev` with noise paths excluded, capped in size.

    The commit *subjects* in this repo are terse one-liners with no body, so the
    actual code diff is the only signal rich enough to enumerate every change.
    """
    if not prev:
        return "(no previous tag — diff omitted; rely on commit subjects)"
    patch = _git("diff", f"{prev}..HEAD", "--", *_DIFF_EXCLUDE)
    if not patch:
        return "(no code changes found)"
    if len(patch) > _DIFF_CHAR_BUDGET:
        patch = (patch[:_DIFF_CHAR_BUDGET]
                 + "\n\n[... diff truncated; see <diffstat> for the rest ...]")
    return patch


def _build_notes_prompt(v: str, prev: Optional[str]) -> str:
    template = (REPO / "release-notes" / "TEMPLATE.md").read_text(encoding="utf-8")
    today = datetime.date.today().isoformat()
    kind = _release_kind(prev, v)

    if prev:
        log = _git("log", f"{prev}..HEAD", "--no-merges", "--format=- %s%n%b")
        diffstat = _git("diff", f"{prev}..HEAD", "--stat")
        range_desc = f"since the previous release ({prev})"
    else:
        log = _git("log", "--no-merges", "--format=- %s%n%b")
        diffstat = _git("diff", "--stat", "HEAD")
        range_desc = "in this repository"
    log = log or "(no commits found)"
    diffstat = diffstat or "(no file changes found)"
    diff = _collect_diff(prev)

    return (
        f"You are drafting the release-notes file for ValScanner version {v}.\n\n"
        "Output ONLY the final Markdown content for "
        f"release-notes/v{v}.md. Do not wrap it in code fences and do not add "
        "any commentary before or after the document.\n\n"
        "Fill in this template exactly, replacing every {placeholder}. Drop "
        "optional sections (Upgrade notes, Fixes, Internal, Known issues) when "
        "there is nothing to put in them:\n\n"
        "<template>\n"
        f"{template}\n"
        "</template>\n\n"
        "Rules:\n"
        f"- Release date: {today}\n"
        f"- Status: {kind}\n"
        f"- The commit subjects below ({range_desc}) are terse one-liners — do "
        "NOT just paraphrase them. Read the full <diff> and enumerate EVERY "
        "distinct user-visible change you find there, even ones the subjects "
        "don't mention. A single commit often bundles several changes.\n"
        "- Lead with the most user-visible change; put bug fixes under Fixes "
        "and fold pure chores/CI/test/build commits into Internal.\n"
        "- Keep bullets concise and written for end users, not implementers.\n"
        "- Match the tone and structure of prior ValScanner release notes.\n\n"
        "<commits>\n"
        f"{log}\n"
        "</commits>\n\n"
        "<diff>\n"
        f"{diff}\n"
        "</diff>\n\n"
        "<diffstat>\n"
        f"{diffstat}\n"
        "</diffstat>\n"
    )


def _strip_fences(text: str) -> str:
    """Drop a leading/trailing ``` fence if the model wrapped its output."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip() + "\n"


def generate_release_notes(v: str) -> None:
    """Draft release-notes/vX.Y.Z.md via `claude -p`. Best-effort, non-fatal."""
    out_path = REPO / "release-notes" / f"v{v}.md"
    if out_path.exists():
        print(f"\nrelease notes: {out_path.name} already exists — skipping "
              "(delete it to regenerate)")
        return
    if shutil.which("claude") is None:
        print("\nrelease notes: 'claude' CLI not found on PATH — skipping")
        return

    prev = _previous_tag()
    print(f"\nrelease notes: drafting {out_path.name} via claude "
          f"(commits since {prev or 'repo start'}) …")
    try:
        prompt = _build_notes_prompt(v, prev)
        result = subprocess.run(
            ["claude", "-p", "--tools", "", "--no-session-persistence"],
            cwd=REPO,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        print("release notes: claude timed out — skipping (write the file by hand)")
        return
    except subprocess.CalledProcessError as exc:
        print(f"release notes: git failed gathering history — skipping ({exc})")
        return

    if result.returncode != 0 or not result.stdout.strip():
        print("release notes: claude returned no output — skipping")
        if result.stderr.strip():
            print(f"  stderr: {result.stderr.strip().splitlines()[-1]}")
        return

    out_path.write_text(_strip_fences(result.stdout), encoding="utf-8")
    print(f"release notes: wrote {out_path.name} — REVIEW AND EDIT before publishing")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--no-notes"]
    skip_notes = "--no-notes" in sys.argv[1:]
    if len(args) != 1 or not re.match(r"^\d+\.\d+\.\d+$", args[0]):
        sys.exit("Usage: python scripts/bump_version.py <major>.<minor>.<patch> "
                 "[--no-notes]")

    v    = args[0]
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
            REPO / "assets/installer.iss",
            [
                (r'^(AppVersion=).+$', rf'\g<1>{v}'),
                (r'^(OutputBaseFilename=ValScanner-)[^-]+(-setup)$', rf'\g<1>{v}\g<2>'),
            ],
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

    if skip_notes:
        print("\nrelease notes: skipped (--no-notes)")
    else:
        generate_release_notes(v)


if __name__ == "__main__":
    main()

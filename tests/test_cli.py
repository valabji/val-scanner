"""End-to-end coverage of the `valscanner` CLI entry point.

These tests drive `valscanner.cli.main()` with a monkeypatched ``sys.argv``
against tmp-path scans, so we exercise the real arg parser, scanner, export,
analysis, transfer, and summary code paths without spawning subprocesses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from valscanner import cli


def _build_tree(root: Path) -> None:
    """Create a tiny, deterministic file tree for the scanner to chew on."""
    (root / "docs").mkdir()
    (root / "media").mkdir()
    (root / "docs" / "readme.txt").write_text("hello world\n")
    (root / "docs" / "notes.md").write_text("# notes\n")
    (root / "media" / "song.mp3").write_bytes(b"\x00" * 1024)
    (root / ".hidden.cfg").write_text("secret\n")


@pytest.fixture
def cli_db(tmp_path):
    """Path to an empty SQLite DB that the CLI can populate."""
    return tmp_path / "cli.db"


def _run_cli(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["valscanner", *argv])
    cli.main()


# ─── tiny helpers ────────────────────────────────────────────────────────────

def test_export_stem_handles_plain_path():
    assert cli._export_stem("/tmp/foo.db") == "foo"
    assert cli._export_stem(None) == "scan"
    assert cli._export_stem("") == "scan"


def test_export_stem_strips_sqlalchemy_urls():
    """Must NEVER leak credentials from a URL into an output filename."""
    assert cli._export_stem("postgresql://u:secret@host/db") == "scan"
    assert cli._export_stem("sqlite:///foo.db") == "scan"


def test_make_scan_progress_cb_returns_none_when_disabled():
    assert cli._make_scan_progress_cb(False, 10, show_progress=False) is None


def test_make_transfer_progress_cb_emits(capsys):
    on_prog, on_stage = cli._make_transfer_progress_cb(show_progress=True)
    assert on_prog is not None
    assert on_stage is not None
    on_prog("hi")
    assert "hi" in capsys.readouterr().out


def test_make_transfer_progress_cb_stage_renders_bar(capsys):
    _, on_stage = cli._make_transfer_progress_cb(show_progress=True)
    on_stage("files", 50, 100)
    out = capsys.readouterr().out
    assert "files" in out
    assert "50/100" in out
    assert "50.0%" in out


def test_make_transfer_progress_cb_disabled_returns_plain_emitter():
    on_prog, on_stage = cli._make_transfer_progress_cb(show_progress=False)
    assert on_prog is not None
    assert on_stage is None


def test_make_analysis_progress_cb_disabled_returns_none():
    assert cli._make_analysis_progress_cb(show_progress=False) is None


def test_make_analysis_progress_cb_runs_without_error():
    cb = cli._make_analysis_progress_cb(show_progress=True)
    assert cb is not None
    cb(0, 0)  # total==0 path
    cb(1, 10)  # normal path; throttle window may swallow output — that's fine


# ─── full CLI flows ──────────────────────────────────────────────────────────

def test_cli_scan_basic(tmp_path, cli_db, monkeypatch, capsys):
    """Happy path: scan a tree and report success."""
    _build_tree(tmp_path)
    _run_cli(monkeypatch, str(tmp_path),
             "--db", str(cli_db),
             "--no-hash", "--no-precount", "--no-progress-bar")

    out = capsys.readouterr().out
    assert "Scanning" in out
    assert "Done" in out
    # Database now contains scan rows
    from valscanner.core.db import list_scans
    scans = list_scans(str(cli_db))
    assert len(scans) == 1
    assert scans[0]["file_count"] >= 4


def test_cli_scan_with_exports(tmp_path, cli_db, monkeypatch):
    """--export-csv / --export-json write files alongside the DB."""
    _build_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    _run_cli(monkeypatch, str(tmp_path),
             "--db", str(cli_db),
             "--no-hash", "--no-progress-bar", "--no-precount",
             "--export-csv", "--export-json", "--label", "trial")
    stem = cli_db.stem
    csv_p = tmp_path / f"{stem}.csv"
    json_p = tmp_path / f"{stem}.json"
    assert csv_p.exists() and csv_p.stat().st_size > 0
    assert json_p.exists()
    payload = json.loads(json_p.read_text())
    assert isinstance(payload, list) and len(payload) >= 4


def test_cli_list_scans_empty(cli_db, monkeypatch, capsys):
    """--list-scans on an empty DB prints a friendly message and exits 0."""
    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--list-scans", "--db", str(cli_db))
    assert e.value.code == 0
    assert "No scans" in capsys.readouterr().out


def test_cli_list_and_delete_scan_round_trip(tmp_path, cli_db, monkeypatch, capsys):
    _build_tree(tmp_path)
    _run_cli(monkeypatch, str(tmp_path),
             "--db", str(cli_db),
             "--no-hash", "--no-progress-bar", "--no-precount")
    capsys.readouterr()  # discard scan output

    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--list-scans", "--db", str(cli_db))
    assert e.value.code == 0
    listed = capsys.readouterr().out
    assert "[  1]" in listed

    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--delete-scan", "1", "--db", str(cli_db))
    assert e.value.code == 0
    assert "deleted" in capsys.readouterr().out


def test_cli_requires_path_or_action(cli_db, monkeypatch):
    """No path, no action → argparse errors out (SystemExit code 2)."""
    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--db", str(cli_db))
    assert e.value.code == 2


def test_cli_path_does_not_exist(tmp_path, cli_db, monkeypatch, capsys):
    bogus = tmp_path / "nope"
    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, str(bogus),
                 "--db", str(cli_db), "--no-progress-bar", "--no-precount")
    assert e.value.code == 1
    assert "does not exist" in capsys.readouterr().out


def test_cli_search_standalone(tmp_path, cli_db, monkeypatch, capsys):
    """--search runs without a path against the existing DB."""
    _build_tree(tmp_path)
    _run_cli(monkeypatch, str(tmp_path),
             "--db", str(cli_db),
             "--no-hash", "--no-progress-bar", "--no-precount")
    capsys.readouterr()

    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--db", str(cli_db), "--search", "readme")
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "Searching for: 'readme'" in out
    assert "readme.txt" in out


def test_cli_dump_to_sqlite_roundtrip(tmp_path, cli_db, monkeypatch, capsys):
    """--dump-to-sqlite then --load-from-sqlite preserves scan data."""
    _build_tree(tmp_path)
    _run_cli(monkeypatch, str(tmp_path),
             "--db", str(cli_db),
             "--no-hash", "--no-progress-bar", "--no-precount")
    capsys.readouterr()

    dump_path = tmp_path / "snapshot.db"
    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--db", str(cli_db),
                 "--dump-to-sqlite", str(dump_path))
    assert e.value.code == 0
    assert dump_path.exists()
    dumped = capsys.readouterr().out
    assert "Done" in dumped

    # Load into a brand-new DB
    fresh_db = tmp_path / "fresh.db"
    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--db", str(fresh_db),
                 "--load-from-sqlite", str(dump_path))
    assert e.value.code == 0

    from valscanner.core.db import list_scans
    assert len(list_scans(str(fresh_db))) == 1


def test_cli_load_from_sqlite_missing_file(tmp_path, cli_db, monkeypatch, capsys):
    bogus = tmp_path / "missing.db"
    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--db", str(cli_db),
                 "--load-from-sqlite", str(bogus))
    assert e.value.code == 1
    assert "file not found" in capsys.readouterr().out


def test_cli_scan_with_skip_flags(tmp_path, cli_db, monkeypatch):
    """All --skip-* flags should be accepted and reduce the indexed count."""
    _build_tree(tmp_path)
    _run_cli(monkeypatch, str(tmp_path),
             "--db", str(cli_db),
             "--no-hash", "--no-progress-bar", "--no-precount",
             "--skip-hidden-files", "--skip-hidden-dirs",
             "--skip-temp", "--skip-logs", "--skip-binaries",
             "--skip-vcs", "--skip-system", "--skip-caches",
             "--exclude", "*.md")

    from valscanner.core.db import repo_for
    rows = repo_for(str(cli_db)).list_files()
    names = {r["filename"] for r in rows}
    assert ".hidden.cfg" not in names  # skipped
    assert "notes.md" not in names      # excluded
    assert "readme.txt" in names


def test_cli_analyze_without_path(tmp_path, cli_db, monkeypatch, capsys):
    """--analyze with no path runs analysis on existing scans (and prints a banner)."""
    _build_tree(tmp_path)
    _run_cli(monkeypatch, str(tmp_path),
             "--db", str(cli_db),
             "--no-hash", "--no-progress-bar", "--no-precount")
    capsys.readouterr()

    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--db", str(cli_db),
                 "--analyze", "--min-files", "1", "--threshold", "0.0",
                 "--no-progress-bar")
    assert e.value.code == 0
    assert "Running similarity analysis" in capsys.readouterr().out


def test_cli_open_settings_invokes_platform_opener(tmp_path, cli_db, monkeypatch, capsys):
    """--open-settings shells out to the platform opener; we stub it."""
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: calls.append(list(a[0])))
    with pytest.raises(SystemExit) as e:
        _run_cli(monkeypatch, "--open-settings", "--db", str(cli_db))
    assert e.value.code == 0
    assert calls and isinstance(calls[0], list)
    # First argv element should be a platform opener command
    assert calls[0][0] in ("open", "start", "xdg-open")
    assert "Settings:" in capsys.readouterr().out

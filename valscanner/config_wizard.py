"""Interactive CLI wizard for configuring the ValScanner database backend.

Invoked from the CLI via `valscanner --configure`. Walks the user through
backend selection (SQLite or PostgreSQL), tests the connection, and writes
the result to settings.json (with the PostgreSQL password going to the OS
keyring when available).
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path
from urllib.parse import quote

from .core import app_settings as _as
from .core.app_settings import (
    CLI_DEFAULTS_BUILTIN,
    active_url,
    cli_defaults,
    mask_url,
    save_cli_defaults,
    settings_path,
)
from .core.db_config import make_engine, reset_engines
from .core.db import reset_repos


def _read_line(prompt: str) -> str | None:
    """Write *prompt* to stdout, flush, then read one line from stdin.

    Returns None on EOF. Bypasses input()/readline so terminal state left
    over from getpass or library calls doesn't suppress echo or swallow
    keystrokes — symptoms reported when the wizard was using input().
    """
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if line == "":
        return None
    return line.rstrip("\r\n")


def _prompt(label: str, default: str | None = None) -> str:
    hint = f" [{default}]" if default else ""
    line = _read_line(f"  {label}{hint}: ")
    if line is None:
        return default or ""
    val = line.strip()
    return val or (default or "")


def _prompt_password(label: str, default: str = "") -> str:
    hint = " (press Enter to keep current)" if default else ""
    try:
        val = getpass.getpass(f"  {label}{hint}: ")
    except EOFError:
        return default
    return val or default


def _confirm(label: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    line = _read_line(f"  {label}{suffix}: ")
    if line is None:
        return default
    val = line.strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def _ask_bool(label: str, default: bool) -> bool:
    return _confirm(label, default=default)


def _ask_int(label: str, default: int, minv: int | None = None, maxv: int | None = None) -> int:
    raw = _prompt(label, default=str(default))
    try:
        v = int(raw)
    except ValueError:
        print(f"    Invalid integer {raw!r}; keeping {default}.")
        return default
    if minv is not None and v < minv:
        print(f"    Must be >= {minv}; keeping {default}.")
        return default
    if maxv is not None and v > maxv:
        print(f"    Must be <= {maxv}; keeping {default}.")
        return default
    return v


def _ask_float(label: str, default: float, minv: float | None = None, maxv: float | None = None) -> float:
    raw = _prompt(label, default=str(default))
    try:
        v = float(raw)
    except ValueError:
        print(f"    Invalid number {raw!r}; keeping {default}.")
        return default
    if minv is not None and v < minv:
        print(f"    Must be >= {minv}; keeping {default}.")
        return default
    if maxv is not None and v > maxv:
        print(f"    Must be <= {maxv}; keeping {default}.")
        return default
    return v


def _ask_choice(label: str, choices: list[str], default: str) -> str:
    options = "/".join(choices)
    raw = _prompt(f"{label} ({options})", default=default).strip().upper()
    if raw in [c.upper() for c in choices]:
        return raw
    print(f"    Invalid choice {raw!r}; keeping {default}.")
    return default


def _build_url(backend: str, vals: dict) -> str:
    if backend == "postgresql":
        user = quote(vals.get("pg_user", "") or "", safe="")
        pw   = quote(vals.get("pg_password", "") or "", safe="")
        auth = f"{user}:{pw}@" if user else ""
        host = vals.get("pg_host") or "localhost"
        port = vals.get("pg_port") or 5432
        db   = vals.get("pg_database") or "valscanner"
        return f"postgresql://{auth}{host}:{port}/{db}"
    raw = vals.get("sqlite_path") or "~/valscanner.db"
    return f"sqlite:///{Path(raw).expanduser().as_posix()}"


def _test_connection(url: str) -> tuple[bool, str]:
    from sqlalchemy import text as sa_text
    try:
        engine = make_engine(url)
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
        engine.dispose()
        return True, "OK"
    except Exception as exc:  # noqa: BLE001
        first_line = str(exc).split("\n")[0]
        return False, mask_url(first_line)[:200]


def _configure_cli_defaults() -> int:
    """Walk through CLI default categories. Returns 0 on save, 1 on abort."""
    current = cli_defaults()
    new_vals: dict = {}

    def section(title: str) -> bool:
        print(f"\n— {title} —")
        try:
            return _confirm("Configure?", default=False)
        except KeyboardInterrupt:
            raise

    try:
        if section("Hashing"):
            new_vals["no_hash"] = _ask_bool(
                "Skip SHA-256 hashing by default?", current["no_hash"],
            )

        if section("Thumbnails"):
            new_vals["no_thumbnails"] = _ask_bool(
                "Skip thumbnail generation by default?", current["no_thumbnails"],
            )
            if not new_vals["no_thumbnails"]:
                new_vals["thumb_size"] = _ask_int(
                    "Thumbnail max dimension (px)", current["thumb_size"], minv=16, maxv=4096,
                )
                new_vals["thumb_quality"] = _ask_int(
                    "Thumbnail JPEG quality (40-95)", current["thumb_quality"], minv=40, maxv=95,
                )

        if section("Media samples (audio/video)"):
            new_vals["no_samples"] = _ask_bool(
                "Skip media sample generation by default?", current["no_samples"],
            )
            if not new_vals["no_samples"]:
                new_vals["sample_duration"] = _ask_int(
                    "Sample duration (seconds)", current["sample_duration"], minv=1, maxv=120,
                )

        if section("Skip filters"):
            for key, label in (
                ("skip_hidden_dirs",  "Skip hidden directories?"),
                ("skip_vcs",          "Skip version-control dirs (.git, .svn, …)?"),
                ("skip_system",       "Skip OS system dirs (Windows, Library, /proc, …)?"),
                ("skip_caches",       "Skip cache/build dirs (node_modules, __pycache__, …)?"),
                ("skip_hidden_files", "Skip hidden files?"),
                ("skip_binaries",     "Skip binary/compiled files (.exe, .dll, .pyc, …)?"),
                ("skip_temp",         "Skip temp/backup files (.tmp, .bak, .swp, …)?"),
                ("skip_logs",         "Skip log files (.log)?"),
            ):
                new_vals[key] = _ask_bool(label, current[key])

        if section("Performance"):
            new_vals["workers"] = _ask_int(
                "Parallel worker threads (1 = sequential)",
                current["workers"], minv=1, maxv=64,
            )
            new_vals["file_timeout"] = _ask_int(
                "Per-file timeout (seconds)",
                current["file_timeout"], minv=1, maxv=3600,
            )
            new_vals["no_precount"] = _ask_bool(
                "Skip pre-scan file count by default?", current["no_precount"],
            )
            new_vals["no_progress_bar"] = _ask_bool(
                "Disable progress bar by default?", current["no_progress_bar"],
            )
            new_vals["verbose"] = _ask_bool(
                "Verbose output (print each file) by default?", current["verbose"],
            )

        if section("Similarity analysis"):
            new_vals["min_files"] = _ask_int(
                "Minimum files per folder", current["min_files"], minv=1, maxv=10_000,
            )
            new_vals["threshold"] = _ask_float(
                "Similarity threshold (0–1)", current["threshold"], minv=0.0, maxv=1.0,
            )
            new_vals["analysis_results"] = _ask_int(
                "Max folder pairs to report", current["analysis_results"], minv=1, maxv=100_000,
            )

        if section("Logging"):
            new_vals["log_level"] = _ask_choice(
                "Log level",
                ["DEBUG", "INFO", "WARNING", "ERROR"],
                current["log_level"],
            )
            new_vals["log_max_size"] = _ask_int(
                "Max log file size (bytes) before rotation",
                current["log_max_size"], minv=1024, maxv=1_073_741_824,
            )
            new_vals["log_backup_count"] = _ask_int(
                "Number of rotated log files to keep",
                current["log_backup_count"], minv=0, maxv=100,
            )
            new_vals["log_no_console"] = _ask_bool(
                "Disable console logging by default?", current["log_no_console"],
            )
    except KeyboardInterrupt:
        print("\nAborted — CLI defaults not changed.")
        return 1

    if not new_vals:
        print("\n  (no categories changed)")
        return 0

    print()
    diffs = [(k, current[k], v) for k, v in new_vals.items() if current[k] != v]
    if not diffs:
        print("  (values match current defaults — nothing to save)")
        return 0

    print("Summary of changes:")
    for k, old, new in diffs:
        print(f"  {k}: {old!r} -> {new!r}")
    print()

    try:
        if not _confirm("Save CLI defaults?", default=True):
            print("Aborted — CLI defaults not changed.")
            return 1
    except KeyboardInterrupt:
        print("\nAborted — CLI defaults not changed.")
        return 1

    save_cli_defaults(new_vals)
    print(f"\n✓ CLI defaults saved to {settings_path()}")
    return 0


def _configure_telemetry() -> int:
    """Walk through telemetry/Sentry settings. Returns process-style exit code."""
    print()
    print("Telemetry & Sentry")
    print("  These also accept env-var overrides (env wins at runtime):")
    print("    VALSCANNER_DISABLE_TELEMETRY, VALSCANNER_SENTRY_DSN, VALSCANNER_SENTRY_ENV")
    print()

    try:
        current = _as.load()
    except Exception:  # noqa: BLE001
        current = {}

    try:
        disable = _ask_bool(
            "Disable error reporting (Sentry)?",
            default=bool(current.get("disable_telemetry", False)),
        )
        dsn = _prompt(
            "Custom Sentry DSN (blank = built-in default)",
            default=current.get("sentry_dsn", ""),
        )
        env_tag = _prompt(
            "Environment tag (blank = production)",
            default=current.get("sentry_env", ""),
        )
    except KeyboardInterrupt:
        print("\nAborted — telemetry settings unchanged.")
        return 1

    updates = {
        "disable_telemetry": disable,
        "sentry_dsn": dsn.strip(),
        "sentry_env": env_tag.strip(),
    }

    diff = {k: v for k, v in updates.items() if current.get(k, "") != v}
    if not diff:
        print("  No changes.")
        return 0

    print("\n  Changes:")
    for k, v in diff.items():
        old = current.get(k, "")
        print(f"    {k}: {old!r} → {v!r}")

    try:
        if not _confirm("Save telemetry settings?", default=True):
            print("  Aborted — telemetry settings unchanged.")
            return 1
    except KeyboardInterrupt:
        print("\nAborted — telemetry settings unchanged.")
        return 1

    merged = {**current, **updates}
    _as.save(merged)
    print(f"  ✓ Saved telemetry settings to {settings_path()}")
    return 0


def _reset_terminal_echo() -> None:
    """Force the controlling TTY back into a sane cooked mode.

    Belt-and-braces against any prior caller that left the terminal in raw
    mode — symptom: Enter sends `^M` (CR) instead of terminating a line,
    because the input flag ICRNL was cleared. We try `stty sane` (most
    thorough) and fall back to flipping the relevant termios flags directly.
    No-op when stdin isn't a TTY or termios/stty aren't available.
    """
    if not sys.stdin.isatty():
        return
    try:
        import subprocess
        subprocess.run(
            ["stty", "sane"],
            stdin=sys.stdin, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False,
        )
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        import termios
        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        attrs[0] |= termios.ICRNL | termios.BRKINT | termios.IXON
        attrs[1] |= termios.OPOST
        attrs[3] |= (
            termios.ECHO | termios.ECHOE | termios.ECHOK | termios.ECHONL
            | termios.ICANON | termios.ISIG
        )
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except Exception:  # noqa: BLE001
        pass


def run_wizard() -> int:
    """Run the interactive configuration wizard. Returns a process exit code."""
    if not sys.stdin.isatty():
        print(
            "valscanner --configure needs an interactive terminal, but stdin "
            "is not a TTY. Re-run from a shell directly (not piped, not via "
            "`nohup`/CI) or edit settings.json with --open-settings.",
            file=sys.stderr,
        )
        return 1

    _reset_terminal_echo()

    print()
    print("ValScanner configuration wizard")
    print(f"  Settings file: {settings_path()}")

    try:
        current = _as.load()
    except Exception as exc:  # noqa: BLE001
        print(f"  Could not load existing settings ({exc}); starting from defaults.")
        current = {}

    cur_backend = current.get("db_backend", "sqlite")
    print(f"  Current backend: {cur_backend}")
    print(f"  Current URL:     {mask_url(active_url())}")
    print()

    print("Choose database backend:")
    print("  1) SQLite     (default — single file, no setup)")
    print("  2) PostgreSQL (requires a running server)")
    default_choice = "2" if cur_backend == "postgresql" else "1"
    try:
        choice = _prompt("Selection [1/2]", default=default_choice)
    except KeyboardInterrupt:
        print("\nAborted.")
        return 1
    if choice not in ("1", "2"):
        print(f"Invalid choice {choice!r} — aborting.")
        return 1
    backend = "postgresql" if choice == "2" else "sqlite"

    new_vals = dict(current)
    new_vals["db_backend"] = backend

    print()
    try:
        if backend == "sqlite":
            new_vals["sqlite_path"] = _prompt(
                "SQLite file path",
                default=current.get("sqlite_path", "~/valscanner.db"),
            )
        else:
            new_vals["pg_host"] = _prompt(
                "Host", default=current.get("pg_host", "localhost"),
            )
            port_str = _prompt("Port", default=str(current.get("pg_port", 5432)))
            try:
                new_vals["pg_port"] = int(port_str)
            except ValueError:
                print(f"Invalid port {port_str!r} — aborting.")
                return 1
            new_vals["pg_database"] = _prompt(
                "Database", default=current.get("pg_database", "valscanner"),
            )
            new_vals["pg_user"] = _prompt(
                "User", default=current.get("pg_user", ""),
            )
            new_vals["pg_password"] = _prompt_password(
                "Password", default=current.get("pg_password", ""),
            )
    except KeyboardInterrupt:
        print("\nAborted.")
        return 1

    url = _build_url(backend, new_vals)
    print(f"\n  Resulting URL: {mask_url(url)}\n")

    try:
        do_test = _confirm("Test connection now?", default=True)
    except KeyboardInterrupt:
        print("\nAborted.")
        return 1

    if do_test:
        print("  Testing…", end=" ", flush=True)
        ok, msg = _test_connection(url)
        if ok:
            print("✓ connected.\n")
        else:
            print(f"✗ failed.\n    {msg}\n")
            try:
                if not _confirm("Save anyway?", default=False):
                    print("Aborted — settings not changed.")
                    return 1
            except KeyboardInterrupt:
                print("\nAborted.")
                return 1

    try:
        if not _confirm("Save these settings?", default=True):
            print("Aborted — settings not changed.")
            return 1
    except KeyboardInterrupt:
        print("\nAborted.")
        return 1

    _as.save(new_vals)
    reset_engines()
    reset_repos()
    print(f"\n✓ Saved to {settings_path()}")
    print(f"  Active URL: {mask_url(active_url())}")

    print()
    try:
        do_tel = _confirm("Also configure telemetry / Sentry?", default=False)
    except KeyboardInterrupt:
        print("\nDone.")
        return 0
    if do_tel:
        _configure_telemetry()

    print()
    try:
        do_cli = _confirm("Also configure CLI defaults (workers, skip filters, "
                          "thumbnails, etc.)?", default=False)
    except KeyboardInterrupt:
        print("\nDone.")
        return 0
    if do_cli:
        _configure_cli_defaults()

    print()
    return 0


if __name__ == "__main__":
    sys.exit(run_wizard())

from __future__ import annotations
import argparse
import ipaddress
import logging
import os
import sqlite3
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from valscanner import __version__ as VERSION
from .models import HealthResponse, ErrorResponse

log = logging.getLogger("valscanner.web")


def _open_db(db_path: str) -> None:
    """Initialize the DB connection's pragmas. Connection is per-request."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()
    finally:
        conn.close()


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(
        title="valscanner",
        version=VERSION,
        description="Local file-scan inspector",
    )
    app.state.db_path = db_path

    from .routers.scans import router as scans_router
    app.include_router(scans_router)

    from .routers.files import router as files_router
    from .routers.folders import router as folders_router
    app.include_router(files_router)
    app.include_router(folders_router)

    from .routers.media import router as media_router
    from .routers.export import router as export_router
    from .routers.reveal import router as reveal_router
    app.include_router(media_router)
    app.include_router(export_router)
    app.include_router(reveal_router)

    @app.exception_handler(HTTPException)
    async def http_exc_handler(_: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "error"
        code = detail.lower().replace(" ", "_") if exc.status_code != 500 else "internal_error"
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            code = exc.detail["error"]
            detail = exc.detail.get("detail", detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(error=code, detail=str(detail)).model_dump(),
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", db=app.state.db_path, version=VERSION)

    # API-404: any unmatched /api/* path returns JSON 404, not the SPA HTML.
    @app.get("/api/{rest:path}", include_in_schema=False)
    def _api_404(rest: str):
        raise HTTPException(status_code=404,
                            detail={"error": "not_found",
                                    "detail": f"unknown api route: /api/{rest}"})

    # SPA static mount (production). Skipped silently when dev mode is on
    # or when static assets have not been built yet.
    try:
        import sys
        if sys.version_info >= (3, 9):
            from importlib.resources import files as _pkg_files
            static_dir = _pkg_files("valscanner.web") / "static"
            static_path = str(static_dir)
        else:
            import importlib.resources as _pkg_resources
            static_path = _pkg_resources.path("valscanner.web", "static").__enter__()

        index_html = Path(static_path) / "index.html"
        if index_html.is_file():
            from fastapi.staticfiles import StaticFiles
            from fastapi.responses import FileResponse
            assets_dir = Path(static_path) / "assets"
            if assets_dir.is_dir():
                app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

            @app.get("/{spa_path:path}", include_in_schema=False)
            def _spa(spa_path: str):
                return FileResponse(str(index_html))
    except (ModuleNotFoundError, FileNotFoundError, AttributeError):
        pass

    return app


# Module-level app for uvicorn --reload smoke tests. Uses env var for DB.
app = create_app(os.environ.get("VALSCANNER_DB", "valscanner.db"))


def _is_loopback(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        return host in ("localhost",)


def _open_browser_when_ready(url: str, deadline: float = 10.0) -> None:
    import threading
    import time
    import urllib.request
    import webbrowser

    def _wait():
        start = time.time()
        while time.time() - start < deadline:
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=0.5) as r:
                    if r.status == 200:
                        webbrowser.open(url)
                        return
            except OSError:
                time.sleep(0.1)

    threading.Thread(target=_wait, daemon=True).start()


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="valscanner-web")
    parser.add_argument("--db", default="valscanner.db", help="SQLite DB path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7070)
    parser.add_argument("--dev", action="store_true", help="Skip static mount (Vite handles UI)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    # Bind safety: refuse non-loopback unless explicit env opt-in.
    if not _is_loopback(args.host) and os.environ.get("VALSCANNER_ALLOW_REMOTE") != "1":
        print(
            f"refusing to bind to non-loopback host {args.host!r}: "
            "set VALSCANNER_ALLOW_REMOTE=1 to override "
            "(the scan endpoint reads arbitrary filesystem paths)",
            file=sys.stderr,
        )
        sys.exit(2)

    db_path = str(Path(args.db).expanduser().resolve())
    _open_db(db_path)
    os.environ["VALSCANNER_DB"] = db_path  # so reload picks it up

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log.info("listening on http://%s:%d  (db=%s)", args.host, args.port, db_path)

    # Re-instantiate with the resolved db_path so app.state is right.
    application = create_app(db_path)

    if not args.no_browser:
        _open_browser_when_ready(f"http://{args.host}:{args.port}")

    uvicorn.run(application, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

from __future__ import annotations
import argparse
import ipaddress
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from valscanner import __version__ as VERSION
from valscanner.core.app_settings import active_url, mask_url
from valscanner.core.bootstrap import ensure_schema
from valscanner.core.db import repo_for
from .models import HealthResponse, ErrorResponse

log = logging.getLogger("valscanner.web")


def create_app(db_path_or_url: str) -> FastAPI:
    url = active_url(db_path_or_url)
    ensure_schema(url)
    repo = repo_for(url)

    app = FastAPI(
        title="valscanner",
        version=VERSION,
        description="Local file-scan inspector",
    )
    app.state.repo = repo
    app.state.db_url     = url        # internal — never logged raw
    app.state.db_display = mask_url(url)

    from .routers.scans import router as scans_router
    from .routers.files import router as files_router
    from .routers.folders import router as folders_router
    from .routers.media import router as media_router
    from .routers.export import router as export_router
    from .routers.reveal import router as reveal_router
    for r in (scans_router, files_router, folders_router,
              media_router, export_router, reveal_router):
        app.include_router(r)

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
        return HealthResponse(status="ok", db=app.state.db_display, version=VERSION)

    @app.get("/api/{rest:path}", include_in_schema=False)
    def _api_404(rest: str):
        raise HTTPException(status_code=404,
                            detail={"error": "not_found",
                                    "detail": f"unknown api route: /api/{rest}"})

    try:
        try:
            from importlib.resources import files as _pkg_files  # type: ignore[attr-defined]
            static_path = str(_pkg_files("valscanner.web") / "static")
        except ImportError:
            # Python 3.8 fallback — locate static/ relative to this module.
            static_path = str(Path(__file__).resolve().parent / "static")
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
    except (ImportError, ModuleNotFoundError, FileNotFoundError, AttributeError):
        pass

    return app


# Module-level app: only instantiated when VALSCANNER_DB is set (uvicorn
# --reload mode). Tests and subprocess invocations that don't set it get a
# placeholder FastAPI instance so module import doesn't trigger ensure_schema.
_startup_url = os.environ.get("VALSCANNER_DB", "")
if _startup_url:
    app = create_app(_startup_url)
else:
    app = FastAPI(title="valscanner", version=VERSION,
                  description="Local file-scan inspector")


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost",)


def _open_browser_when_ready(url: str, deadline: float = 10.0) -> None:
    import threading, time, urllib.request, webbrowser

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
    parser.add_argument("--db", default=None,
                        help="SQLite DB path or full SQLAlchemy URL "
                             "(defaults to active settings)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7070)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not _is_loopback(args.host) and os.environ.get("VALSCANNER_ALLOW_REMOTE") != "1":
        print(
            f"refusing to bind to non-loopback host {args.host!r}: "
            "set VALSCANNER_ALLOW_REMOTE=1 to override "
            "(the scan endpoint reads arbitrary filesystem paths)",
            file=sys.stderr,
        )
        sys.exit(2)

    url = active_url(args.db) if args.db else active_url()
    os.environ["VALSCANNER_DB"] = url

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log.info("listening on http://%s:%d  (db=%s)", args.host, args.port, mask_url(url))

    application = create_app(url)

    if not args.no_browser:
        _open_browser_when_ready(f"http://{args.host}:{args.port}")

    uvicorn.run(application, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

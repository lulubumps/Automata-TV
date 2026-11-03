"""Servidor web: API REST + WebSocket para la interfaz."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from . import __version__
from .engine import AppError, Engine
from .report import build_report

STATIC = Path(__file__).parent / "static"
OK = {"ok": True}


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def create_app(engine: Engine | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    engine = engine or Engine(os.environ.get("DATA_DIR", "./data"), os.environ.get("MEDIA_DIR", "/media"))
    clients: set[WebSocket] = set()

    async def push(targets=None) -> None:
        msg = json.dumps(engine.snapshot())
        for ws in list(targets or clients):
            try:
                await ws.send_text(msg)
            except Exception:
                clients.discard(ws)

    async def broadcaster() -> None:
        while True:
            await engine.changed.wait()
            engine.changed.clear()
            await push()
            await asyncio.sleep(0.1)  # máximo ~10 envíos por segundo

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await engine.start_background()
        task = asyncio.create_task(broadcaster())
        yield
        task.cancel()
        await engine.shutdown()

    app = FastAPI(title="Automata TV", version=__version__, lifespan=lifespan)
    app.state.engine = engine

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/health")
    async def health():
        return {"ok": True, "version": __version__, "obs": engine.connected}

    @app.get("/api/library")
    async def library():
        return engine.library

    @app.post("/api/start")
    async def start(request: Request):
        await engine.start((await _body(request)).get("id"))
        return OK

    @app.post("/api/stop")
    async def stop():
        await engine.stop()
        return OK

    @app.post("/api/skip")
    async def skip():
        await engine.skip()
        return OK

    @app.post("/api/skip-break")
    async def skip_break():
        engine.skip_break()
        return OK

    @app.post("/api/playlist/add")
    async def playlist_add(request: Request):
        engine.add_items((await _body(request)).get("items") or [])
        return OK

    @app.post("/api/playlist/remove")
    async def playlist_remove(request: Request):
        engine.remove_item((await _body(request)).get("id", ""))
        return OK

    @app.post("/api/playlist/move")
    async def playlist_move(request: Request):
        b = await _body(request)
        engine.move_item(b.get("id", ""), b.get("dir", ""))
        return OK

    @app.post("/api/playlist/clear")
    async def playlist_clear():
        engine.clear_playlist()
        return OK

    @app.post("/api/library/scan")
    async def library_scan():
        await engine.scan_library()
        return OK

    @app.post("/api/config")
    async def config(request: Request):
        await engine.update_config(await _body(request))
        return OK

    @app.post("/api/report")
    async def report(request: Request):
        return await build_report(engine, test=bool((await _body(request)).get("test")))

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        clients.add(ws)
        await push([ws])
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    return app


app = create_app()

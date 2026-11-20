"""Web panel for the local scheduling engine."""
import hmac
import json
import logging
import os
import subprocess
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from playout import Obs, Slot, make_block, run, save

MEDIA = Path(os.environ.get("MEDIA_DIR", "/media")).resolve()
DATA = Path(os.environ.get("DATA_DIR", "/data"))
ZONE = ZoneInfo(os.environ.get("CHANNEL_TZ", "America/Santiago"))
OBS_ROOT = os.environ.get("OBS_MEDIA_ROOT", "")
OBS_URL = os.environ.get("OBS_URL", "ws://host.docker.internal:4455")
PASSWORD = os.environ.get("PANEL_PASSWORD", "")
SCHEDULE = DATA / "parrilla.json"
auth = HTTPBasic()
lock = threading.Lock()
stop = threading.Event()
worker = None
slots = ()
fallback = ""
status = "Automatización detenida"
playing = None
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def protect(request: Request, credentials: HTTPBasicCredentials = Depends(auth)):
    valid = hmac.compare_digest(credentials.password.encode(), PASSWORD.encode())
    if credentials.username != "operador" or not valid:
        raise HTTPException(401, "Credenciales incorrectas", {"WWW-Authenticate": "Basic"})
    if request.method == "POST" and request.headers.get("X-Automata") != "1":
        raise HTTPException(403, "Solicitud fuera del panel")


def notify(message):
    global status
    with lock:
        status = message


def set_playback(slot, path, loop):
    global playing
    with lock:
        playing = (slot, path, loop) if path else None


def snapshot():
    with lock:
        return slots, fallback


@asynccontextmanager
async def lifespan(app):
    global slots, fallback
    if not PASSWORD or not OBS_ROOT:
        raise RuntimeError("Configura PANEL_PASSWORD y OBS_MEDIA_ROOT en .env.")
    DATA.mkdir(parents=True, exist_ok=True)
    if SCHEDULE.exists():
        saved = json.loads(SCHEDULE.read_text(encoding="utf-8"))
        slots = tuple(Slot(**item) for item in saved["slots"])
        fallback = saved["fallback"]
    yield
    stop.set()
    if worker:
        worker.join(timeout=12)


app = FastAPI(lifespan=lifespan, dependencies=[Depends(protect)],
              docs_url=None, redoc_url=None, openapi_url=None)


def mapped_path(path):
    parts = Path(path).relative_to(MEDIA).parts
    windows = PureWindowsPath(OBS_ROOT)
    root = windows if windows.drive else PurePosixPath(OBS_ROOT)
    return str(root.joinpath(*parts))


def file_path(name):
    path = (MEDIA / name).resolve()
    if not path.is_relative_to(MEDIA) or path.suffix.lower() != ".mp4" or not path.is_file():
        raise HTTPException(400, "Selecciona un MP4 disponible en la biblioteca.")
    return path


def duration(path):
    try:
        output = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ], text=True, timeout=15)
        return float(output)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise HTTPException(400, f"No se pudo medir la duración de {path.name}.") from None


def persist(schedule, continuity):
    global slots, fallback
    save(SCHEDULE, schedule, continuity)
    slots, fallback = tuple(schedule), continuity


@app.get("/")
def index():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/api/library")
def library():
    return sorted(str(path.relative_to(MEDIA)) for path in MEDIA.rglob("*")
                  if path.suffix.lower() == ".mp4" and path.is_file()
                  and path.resolve().is_relative_to(MEDIA))


@app.get("/api/preview")
def preview(path: str):
    return FileResponse(file_path(path), media_type="video/mp4")


@app.get("/api/state")
def state():
    with lock:
        running = bool(worker and worker.is_alive())
        now = datetime.now(ZONE)
        current = None
        if running and playing:
            slot, path, loop = playing
            current = {"name": Path(path).name, "kind": "Continuidad" if loop else slot.kind,
                       "id": slot.start if slot else None, "end": slot.end if slot else None}
        return {
            "now": now.isoformat(timespec="seconds"), "zone": ZONE.key,
            "epoch": now.timestamp(), "playing": current,
            "running": running, "stopping": running and stop.is_set(),
            "status": status if running else "Automatización detenida · control manual en OBS",
            "fallback": Path(fallback).name if fallback else "",
            "slots": [
                {"id": slot.start, "kind": slot.kind, "name": Path(slot.path).name,
                 "start": datetime.fromtimestamp(slot.start, ZONE).isoformat(timespec="seconds"),
                 "end": datetime.fromtimestamp(slot.end, ZONE).isoformat(timespec="seconds")}
                for slot in slots
            ],
        }


class Media(BaseModel):
    path: str


class Block(BaseModel):
    start: datetime
    kind: str
    paths: list[str] = Field(min_length=1, max_length=100)


class Removal(BaseModel):
    start: float


@app.post("/api/fallback")
def continuity(item: Media):
    path = file_path(item.path)
    with lock:
        persist(slots, str(path))


@app.post("/api/blocks")
def add(block: Block):
    local = block.start
    if local.tzinfo is not None or block.kind not in {"Episodio", "Comercial", "Identificación"}:
        raise HTTPException(400, "Ingresa una hora local y un tipo de evento válido.")
    start = local.replace(tzinfo=ZONE).timestamp()
    if (datetime.fromtimestamp(start, ZONE).replace(tzinfo=None) != local
            or local.replace(tzinfo=ZONE, fold=1).timestamp() != start):
        raise HTTPException(400, "Esa hora es ambigua o no existe por el cambio de hora.")
    media = [(path, duration(path)) for path in map(file_path, sorted(block.paths, key=str.casefold))]
    with lock:
        try:
            schedule = make_block(slots, start, media, block.kind)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        persist(schedule, fallback)


@app.post("/api/remove")
def remove(item: Removal):
    with lock:
        persist([slot for slot in slots if slot.start != item.start], fallback)


@app.post("/api/start")
def start():
    global worker, status, playing
    with lock:
        if worker and worker.is_alive():
            raise HTTPException(409, "La automatización ya está activa o se está deteniendo.")
        if not fallback or not Path(fallback).is_file():
            raise HTTPException(400, "Selecciona un MP4 de continuidad disponible.")
        obs = Obs(os.environ.get("OBS_PASSWORD", ""), os.environ.get("OBS_SCENE", "Automata TV"),
                  os.environ.get("OBS_SOURCE", "TV_PLAYER"), url=OBS_URL, media_path=mapped_path)
        playing = None
        stop.clear()
        status = "Conectando con OBS…"
        worker = threading.Thread(target=run, args=(obs, stop, snapshot, notify),
                                  kwargs={"playback": set_playback}, daemon=True)
        worker.start()


@app.post("/api/stop")
def halt():
    with lock:
        stop.set()

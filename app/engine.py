"""Motor del automatizador: biblioteca de videos, parrilla y control de OBS."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from pathlib import Path

import simpleobsws

from . import __version__

log = logging.getLogger("tv")

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".ts", ".wmv", ".mpg", ".mpeg"}
CATEGORIES = ("pelicula", "serie", "comercial")
# Películas y episodios cuentan como "programa": tras ellos entra la tanda de comerciales
KIND_OF = {"pelicula": "programa", "serie": "programa", "comercial": "comercial"}
MAX_DEPTH = 6

ACT_RESTART = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
ACT_STOP = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"
ST_ENDED = "OBS_MEDIA_STATE_ENDED"
ST_PLAYING = "OBS_MEDIA_STATE_PLAYING"
ST_IDLE = {"OBS_MEDIA_STATE_NONE", "OBS_MEDIA_STATE_STOPPED", "OBS_MEDIA_STATE_ERROR"}


class AppError(Exception):
    """Error pensado para mostrarse al usuario."""


# ---------------------------------------------------------------- biblioteca
def natural_key(name: str) -> list:
    """Orden natural: 'ep2' antes que 'ep10'."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name.casefold())]


def empty_node(name: str = "") -> dict:
    return {"name": name, "items": [], "folders": [], "count": 0}


def scan_tree(root: Path, category: str, rel: tuple = (), depth: int = 0) -> dict:
    """Árbol de una carpeta: cada nodo tiene sus videos (items) y subcarpetas (folders)."""
    node = empty_node(root.name)
    try:
        with os.scandir(root) as it:
            entries = sorted(it, key=lambda e: natural_key(e.name))
    except OSError:
        return node
    for e in entries:
        if e.name.startswith("."):  # ocultos y archivos "._" de macOS
            continue
        try:
            is_dir, is_file = e.is_dir(), e.is_file()
        except OSError:
            continue
        if is_dir and depth < MAX_DEPTH:
            child = scan_tree(Path(e.path), category, rel + (e.name,), depth + 1)
            if child["count"]:
                node["folders"].append(child)
        elif is_file:
            stem, ext = os.path.splitext(e.name)
            if ext.lower() in VIDEO_EXT:
                node["items"].append(
                    {
                        "kind": KIND_OF[category],
                        "category": category,
                        "title": stem,
                        "group": " / ".join(rel),
                        "path": e.path,
                    }
                )
    node["count"] = len(node["items"]) + sum(f["count"] for f in node["folders"])
    return node


def flatten(node: dict) -> list:
    return list(node["items"]) + [i for f in node["folders"] for i in flatten(f)]


def _uid() -> str:
    return secrets.token_hex(4)


def _env_int(env, key: str, default: int) -> int:
    try:
        return int(env.get(key, default))
    except (TypeError, ValueError):
        return default


# -------------------------------------------------------------------- motor
class Engine:
    def __init__(
        self,
        data_dir,
        media_root,
        env=None,
        *,
        tick_s: float = 1.0,
        min_play_s: float = 1.5,
        reconnect_s: float = 5.0,
        stall_s: float = 4.0,
    ):
        env = os.environ if env is None else env
        self.tick_s, self.min_play_s, self.reconnect_s, self.stall_s = tick_s, min_play_s, reconnect_s, stall_s

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "state.json"
        self.media_root = Path(os.path.abspath(media_root))

        saved = self._load()
        sc = saved.get("config") or {}
        self.config = {
            "obs": {
                "host": env.get("OBS_HOST", "127.0.0.1"),
                "port": _env_int(env, "OBS_PORT", 4455),
                "password": env.get("OBS_PASSWORD", ""),
                "input": env.get("OBS_INPUT", "TV_PLAYER"),
                "mediaRoot": env.get("OBS_MEDIA_ROOT", ""),
            },
            "folders": {"pelicula": "Peliculas", "serie": "Series", "comercial": "Comerciales"},
            "breakCount": 1,  # comerciales tras cada programa (0 = sin tandas)
            "loop": True,  # al terminar la parrilla vuelve a empezar (24/7)
        }
        self.config["obs"].update(sc.get("obs") or {})
        self.config["folders"].update(sc.get("folders") or {})
        for k in ("breakCount", "loop"):
            if k in sc:
                self.config[k] = sc[k]

        self.playlist: list[dict] = [
            {"group": "", "category": "comercial" if it.get("kind") == "comercial" else "pelicula", **it}
            for it in (saved.get("playlist") or [])
        ]

        self.client: simpleobsws.WebSocketClient | None = None
        self.connected = False
        self._connecting = False
        self._last_conn_error = None

        self.status = "stopped"  # "stopped" | "playing"
        self.index = -1
        self.current: dict | None = None
        self.break_queue: list[dict] = []
        self.commercial_cursor = 0
        self.started_at = 0.0
        self.cursor = 0
        self.duration = 0
        self._advancing = False
        self._saw_playing = False
        self._stalls = 0

        self.library = {c: empty_node() for c in CATEGORIES}
        self.commercials: list[dict] = []
        self.library_version = 0
        self.logs: deque[str] = deque(maxlen=100)
        self.changed = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------ utilidades
    def _load(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self) -> None:
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"config": self.config, "playlist": self.playlist}, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.state_file)
        except OSError as e:
            self.log(f"No se pudo guardar el estado: {e}")

    def log(self, msg: str) -> None:
        self.logs.append(f"{time.strftime('%H:%M:%S')}  {msg}")
        log.info(msg)
        self._changed()

    def _changed(self) -> None:
        self.changed.set()

    def _inside_media(self, p: Path) -> bool:
        return p == self.media_root or self.media_root in p.parents

    def _abs(self, value: str) -> Path:
        p = Path(value)
        return Path(os.path.normpath(p if p.is_absolute() else self.media_root / p))

    def to_obs_path(self, p: str) -> str:
        """Traduce una ruta del contenedor a la ruta que OBS ve en su equipo."""
        root = (self.config["obs"].get("mediaRoot") or "").strip()
        if not root:
            return p
        rel = os.path.relpath(p, self.media_root)
        win = bool(re.match(r"^[A-Za-z]:", root)) or "\\" in root
        sep = "\\" if win else "/"
        base = root.replace("/", sep) if win else root
        return base.rstrip("/\\") + sep + rel.replace(os.sep, sep)

    # --------------------------------------------------------------- arranque
    async def start_background(self) -> None:
        await self.scan_library()
        self._tasks = [asyncio.create_task(self._connect_loop()), asyncio.create_task(self._tick_loop())]

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._close_client()

    async def _connect_loop(self) -> None:
        while True:
            if not self.connected:
                await self.connect()
            await asyncio.sleep(self.reconnect_s)

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self.tick_s)
            try:
                await self.tick()
            except Exception as e:  # el bucle nunca debe morir
                log.exception("Error en tick: %s", e)

    async def _close_client(self) -> None:
        c, self.client = self.client, None
        if c:
            try:
                await c.disconnect()
            except Exception:
                pass

    async def connect(self) -> None:
        if self.connected or self._connecting:
            return
        self._connecting = True
        o = self.config["obs"]
        client = simpleobsws.WebSocketClient(url=f"ws://{o['host']}:{o['port']}", password=o.get("password") or "")
        try:
            await asyncio.wait_for(client.connect(), 5)
            if not await client.wait_until_identified(timeout=5):
                raise RuntimeError("OBS no aceptó la sesión (¿contraseña incorrecta?)")
            client.register_event_callback(self._on_media_ended, "MediaInputPlaybackEnded")
            await self._close_client()
            self.client, self.connected, self._last_conn_error = client, True, None
            self.log("Conectado a OBS")
            if self.status == "playing" and self.current:
                self.log("Reanudando el contenido que estaba al aire")
                await self.play(self.current)
        except Exception as e:
            self.connected = False
            try:
                await client.disconnect()
            except Exception:
                pass
            msg = f"No se pudo conectar a OBS en {o['host']}:{o['port']} ({e or type(e).__name__}). Reintentando cada {self.reconnect_s:g} s"
            if msg != self._last_conn_error:
                self.log(msg)
            self._last_conn_error = msg
        finally:
            self._connecting = False
            self._changed()

    async def reconnect(self) -> None:
        self.connected = False
        await self._close_client()
        await self.connect()

    async def _on_media_ended(self, data) -> None:
        if data and data.get("inputName") == self.config["obs"]["input"]:
            await self.on_ended()

    # -------------------------------------------------------------- biblioteca
    def _scan_all(self) -> dict:
        out = {}
        for cat in CATEGORIES:
            value = (self.config["folders"].get(cat) or "").strip()
            if not value:
                out[cat] = empty_node()
                continue
            p = self._abs(value)
            out[cat] = scan_tree(p, cat) if self._inside_media(p) else empty_node()
        return out

    async def scan_library(self) -> None:
        self.library = await asyncio.to_thread(self._scan_all)
        self.commercials = flatten(self.library["comercial"])
        self.library_version += 1
        self._changed()

    # ------------------------------------------------------------ reproducción
    async def _call(self, req_type: str, data: dict, timeout: float = 10):
        r = await self.client.call(simpleobsws.Request(req_type, data), timeout=timeout)
        if not r.ok():
            raise RuntimeError(r.requestStatus.comment or f"{req_type} falló (código {r.requestStatus.code})")
        return r.responseData or {}

    async def play(self, item: dict) -> bool:
        if not self.connected or not self.client:
            self.log("OBS no está conectado")
            return False
        if not os.path.isfile(item["path"]):
            self.log(f"No se encuentra el archivo: {item['path']}")
            return False
        inp = self.config["obs"]["input"]
        try:
            await self._call(
                "SetInputSettings",
                {"inputName": inp, "inputSettings": {"local_file": self.to_obs_path(item["path"]), "is_local_file": True, "looping": False}},
            )
            await self._call("TriggerMediaInputAction", {"inputName": inp, "mediaAction": ACT_RESTART})
        except Exception as e:
            self.log(f'Error de OBS (revisa que exista la fuente "{inp}"): {e}')
            return False
        self.current = item
        self.started_at = time.monotonic()
        self.cursor = self.duration = 0
        self._saw_playing = False
        self.status = "playing"
        self.log(f"Al aire: {item['title']} ({item['kind']})")
        return True

    async def next(self) -> None:
        if self._advancing:
            return
        self._advancing = True
        try:
            tries = 0
            while True:
                if self.break_queue:
                    item = self.break_queue.pop(0)
                else:
                    if not self.playlist:
                        return await self.stop("La parrilla está vacía")
                    i = self.index + 1
                    if i >= len(self.playlist):
                        if not self.config["loop"]:
                            return await self.stop("Terminó la parrilla")
                        i = 0
                    self.index = i
                    item = self.playlist[i]
                tries += 1
                if await self.play(item):
                    return
                if not self.connected or tries > len(self.playlist) + 5:
                    return await self.stop("No se pudo reproducir ningún archivo")
        finally:
            self._advancing = False
            self._changed()

    def queue_break(self) -> None:
        n, pool = self.config["breakCount"], self.commercials
        if not n or not pool:
            return
        for _ in range(n):
            self.break_queue.append({**pool[self.commercial_cursor % len(pool)], "id": _uid()})
            self.commercial_cursor += 1
        self.log(f"Tanda de {n} comercial(es) en cola")

    async def on_ended(self, force: bool = False) -> None:
        if self.status != "playing" or self._advancing:
            return
        if not force and time.monotonic() - self.started_at < self.min_play_s:
            return  # evita avances dobles (evento + consulta periódica)
        if self.current and self.current["kind"] == "programa":
            self.queue_break()
        await self.next()

    async def start(self, item_id: str | None = None) -> None:
        self.break_queue = []
        i = next((k for k, p in enumerate(self.playlist) if p["id"] == item_id), 0) if item_id else 0
        self.index = i - 1
        self._stalls = 0
        await self.next()

    async def stop(self, reason: str | None = None) -> None:
        self.status = "stopped"
        self.current = None
        self.break_queue = []
        self.cursor = self.duration = 0
        if self.connected and self.client:
            try:
                await self._call("TriggerMediaInputAction", {"inputName": self.config["obs"]["input"], "mediaAction": ACT_STOP})
            except Exception:
                pass
        self.log(reason or "Detenido")

    async def skip(self) -> None:
        if self.status == "playing":
            await self.on_ended(force=True)

    def skip_break(self) -> None:
        if self.break_queue:
            self.break_queue = []
            self.log("Tanda descartada")

    async def tick(self) -> None:
        if self.connected and not (self.client and self.client.ws_open and self.client.is_identified()):
            self.connected = False
            self.log("Se perdió la conexión con OBS. Reintentando…")
        if self.connected and self.status == "playing" and not self._advancing and self.current:
            try:
                d = await self._call("GetMediaInputStatus", {"inputName": self.config["obs"]["input"]}, timeout=5)
            except Exception:
                d = None
            if d:
                self.cursor = d.get("mediaCursor") or 0
                self.duration = d.get("mediaDuration") or 0
                state = d.get("mediaState")
                if state == ST_PLAYING:
                    self._saw_playing, self._stalls = True, 0
                if state == ST_ENDED:
                    await self.on_ended()
                elif state in ST_IDLE and not self._saw_playing and time.monotonic() - self.started_at > self.stall_s:
                    await self._on_stall()
        self._changed()

    async def _on_stall(self) -> None:
        """OBS no arrancó el video: ruta de OBS mal configurada o escena fuera del aire."""
        self._stalls += 1
        inp = self.config["obs"]["input"]
        self.log(
            f'OBS no está reproduciendo "{self.current["title"]}". Revisa que la escena con "{inp}" esté al aire '
            f'y que OBS vea esta ruta: {self.to_obs_path(self.current["path"])}'
        )
        if self._stalls >= 3:
            self._stalls = 0
            await self.stop("Detenido: OBS no reproduce los archivos (revisa la carpeta de videos vista desde OBS y la escena)")
        else:
            await self.on_ended(force=True)

    # ------------------------------------------------------------------ parrilla
    def add_items(self, items: list) -> None:
        new = []
        for it in items or []:
            if not isinstance(it, dict) or it.get("category") not in CATEGORIES or not it.get("path"):
                raise AppError("Ítem inválido")
            p = self._abs(str(it["path"]))
            if not self._inside_media(p):
                raise AppError(f"El video debe estar dentro de {self.media_root}")
            if not p.is_file():
                raise AppError(f"No existe el archivo: {p}")
            cat = it["category"]
            new.append(
                {
                    "id": _uid(),
                    "kind": KIND_OF[cat],
                    "category": cat,
                    "group": str(it.get("group") or ""),
                    "title": str(it.get("title") or p.stem),
                    "path": str(p),
                }
            )
        self.playlist.extend(new)
        self.save()
        self._changed()

    def remove_item(self, item_id: str) -> None:
        i = next((k for k, p in enumerate(self.playlist) if p["id"] == item_id), -1)
        if i < 0:
            return
        del self.playlist[i]
        if i <= self.index:
            self.index -= 1
        self.save()
        self._changed()

    def move_item(self, item_id: str, direction: str) -> None:
        i = next((k for k, p in enumerate(self.playlist) if p["id"] == item_id), -1)
        j = i - 1 if direction == "up" else i + 1
        if i < 0 or j < 0 or j >= len(self.playlist):
            return
        self.playlist[i], self.playlist[j] = self.playlist[j], self.playlist[i]
        if self.index == i:
            self.index = j
        elif self.index == j:
            self.index = i
        self.save()
        self._changed()

    def clear_playlist(self) -> None:
        self.playlist, self.index = [], -1
        self.save()
        self._changed()

    # ------------------------------------------------------------------- ajustes
    async def update_config(self, c: dict) -> None:
        o, f = c.get("obs") or {}, c.get("folders") or {}
        for cat in CATEGORIES:  # validar antes de tocar nada
            if isinstance(f.get(cat), str) and f[cat].strip():
                if not self._inside_media(self._abs(f[cat].strip())):
                    raise AppError(f'La carpeta "{f[cat]}" debe estar dentro de {self.media_root}')
        before_conn = tuple(self.config["obs"][k] for k in ("host", "port", "password"))
        before_dirs = json.dumps(self.config["folders"], sort_keys=True)

        obs = self.config["obs"]
        if o.get("host"):
            obs["host"] = str(o["host"]).strip()
        if o.get("port"):
            try:
                obs["port"] = int(o["port"])
            except (TypeError, ValueError):
                raise AppError("El puerto debe ser un número")
        if o.get("input"):
            obs["input"] = str(o["input"]).strip()
        if isinstance(o.get("password"), str) and o["password"] != "":
            obs["password"] = o["password"]
        if isinstance(o.get("mediaRoot"), str):
            obs["mediaRoot"] = o["mediaRoot"].strip()
        for cat in CATEGORIES:
            if isinstance(f.get(cat), str):
                self.config["folders"][cat] = f[cat].strip()
        if c.get("breakCount") is not None:
            try:
                self.config["breakCount"] = max(0, min(20, int(c["breakCount"])))
            except (TypeError, ValueError):
                raise AppError("La cantidad de comerciales debe ser un número")
        if isinstance(c.get("loop"), bool):
            self.config["loop"] = c["loop"]
        self.save()

        if json.dumps(self.config["folders"], sort_keys=True) != before_dirs:
            await self.scan_library()
        if tuple(obs[k] for k in ("host", "port", "password")) != before_conn:
            asyncio.create_task(self.reconnect())
        self._changed()

    # ------------------------------------------------------------ estado para la UI
    def peek_next(self) -> dict | None:
        if self.status != "playing":
            return None
        if self.break_queue:
            return self.break_queue[0]
        if self.current and self.current["kind"] == "programa" and self.config["breakCount"] and self.commercials:
            return self.commercials[self.commercial_cursor % len(self.commercials)]
        if not self.playlist:
            return None
        i = self.index + 1
        if i >= len(self.playlist):
            if not self.config["loop"]:
                return None
            i = 0
        return self.playlist[i]

    def snapshot(self) -> dict:
        o = self.config["obs"]
        return {
            "version": __version__,
            "connected": self.connected,
            "status": self.status,
            "index": self.index,
            "current": self.current,
            "next": self.peek_next(),
            "breakLeft": len(self.break_queue),
            "cursor": self.cursor,
            "duration": self.duration,
            "playlist": self.playlist,
            "libraryVersion": self.library_version,
            "mediaRoot": str(self.media_root),
            "config": {
                "folders": self.config["folders"],
                "breakCount": self.config["breakCount"],
                "loop": self.config["loop"],
                "obs": {"host": o["host"], "port": o["port"], "input": o["input"], "mediaRoot": o.get("mediaRoot", ""), "hasPassword": bool(o.get("password"))},
            },
            "logs": list(self.logs)[-40:],
        }

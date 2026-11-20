"""Wall-clock scheduling and OBS WebSocket v5 transport."""
import base64
import hashlib
import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from websockets.sync.client import connect

LOG = logging.getLogger("automata")


@dataclass(frozen=True)
class Slot:
    start: float
    duration: float
    path: str
    kind: str

    @property
    def end(self):
        return self.start + self.duration


def make_block(schedule, start, media, kind):
    block = []
    for path, duration in media:
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("La duración debe ser mayor que cero.")
        slot = Slot(start, duration, str(path), kind)
        if any(slot.start < existing.end and existing.start < slot.end
               for existing in schedule):
            raise ValueError(f"El bloque se cruza con otro evento: {path.name}")
        block.append(slot)
        start = slot.end
    return sorted([*schedule, *block], key=lambda slot: slot.start)


def save(path, slots, fallback):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "slots": [asdict(slot) for slot in slots],
        "fallback": fallback,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Obs:
    def __init__(self, password, scene, source, *,
                 url="ws://127.0.0.1:4455", media_path=str):
        self.url = url
        self.media_path = media_path
        self.password = password
        self.scene = scene
        self.source = source
        self.socket = None
        self.serial = 0

    def open(self):
        self.socket = connect(self.url, open_timeout=3,
                              close_timeout=1, proxy=None)
        hello = self.receive(0)
        identify = {"rpcVersion": 1, "eventSubscriptions": 0}
        if "authentication" in hello:
            auth = hello["authentication"]
            secret = self.digest(self.password + auth["salt"])
            identify["authentication"] = self.digest(secret + auth["challenge"])
        self.socket.send(json.dumps({"op": 1, "d": identify}))
        self.receive(2)
        scenes = self.request("GetSceneList")["scenes"]
        if not any(scene["sceneName"] == self.scene for scene in scenes):
            raise ValueError("La escena indicada no existe en OBS.")
        source = self.request("GetInputSettings", inputName=self.source)
        if source["inputKind"] != "ffmpeg_source":
            raise ValueError("La fuente indicada debe ser una Fuente multimedia.")
        items = self.request("GetSceneItemList", sceneName=self.scene)["sceneItems"]
        if not any(item["sourceName"] == self.source and item["sceneItemEnabled"]
                   for item in items):
            raise ValueError("La fuente debe estar visible directamente en la escena.")

    @staticmethod
    def digest(value):
        return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()

    def receive(self, opcode):
        message = json.loads(self.socket.recv(timeout=3))
        if message["op"] != opcode:
            raise RuntimeError("Respuesta inesperada de OBS.")
        return message["d"]

    def request(self, name, **data):
        self.serial += 1
        request_id = str(self.serial)
        self.socket.send(json.dumps({"op": 6, "d": {
            "requestType": name, "requestId": request_id, "requestData": data,
        }}))
        reply = self.receive(7)
        if reply["requestId"] != request_id:
            raise RuntimeError("La respuesta de OBS no coincide con la solicitud.")
        status = reply["requestStatus"]
        if not status["result"]:
            raise RuntimeError(f"{name}: {status.get('comment', status['code'])}")
        return reply.get("responseData", {})

    def status(self):
        return self.request("GetMediaInputStatus", inputName=self.source)

    def play(self, path, loop, start=None):
        self.request("SetInputSettings", inputName=self.source, overlay=True,
                     inputSettings={"is_local_file": True, "local_file": self.media_path(path),
                                    "loop": loop, "restart_on_activate": False,
                                    "close_when_inactive": False})
        self.request("SetCurrentProgramScene", sceneName=self.scene)
        self.request("TriggerMediaInputAction", inputName=self.source,
                     mediaAction="OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART")
        for _ in range(12):
            status = self.status()
            if status["mediaState"] == "OBS_MEDIA_STATE_PLAYING":
                if start is not None and time.time() - start >= 2:
                    duration = status.get("mediaDuration")
                    if not duration:
                        time.sleep(0.2)
                        continue
                    cursor = min(max(0, int((time.time() - start) * 1000)), duration - 1)
                    self.request("SetMediaInputCursor", inputName=self.source,
                                 mediaCursor=cursor)
                return
            time.sleep(0.2)
        raise RuntimeError("OBS no confirmó la reproducción del MP4.")

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None


def run(obs, stop, snapshot, notify, *, playback=None):
    current = None
    while not stop.is_set():
        try:
            if obs.socket is None:
                obs.open()
                notify("OBS conectado · automatización activa")
            slots, fallback = snapshot()
            now = time.time()
            slot = next((item for item in slots if item.start <= now < item.end), None)
            available = slot is not None and Path(slot.path).is_file()
            if slot and not available:
                message = f"Falta {Path(slot.path).name}"
            else:
                message = "Sin evento programado"
            path = slot.path if available else fallback
            loop = not available
            target = (None if loop else slot, path)
            if target != current:
                if playback:
                    playback(None, None, False)
                if path:
                    if not Path(path).is_file():
                        raise FileNotFoundError(f"No se encuentra {Path(path).name}")
                    obs.play(path, loop, None if loop else slot.start)
                    if playback:
                        playback(slot if not loop else None, path, loop)
                    notify(f"{'Continuidad' if loop else slot.kind} · {Path(path).name}")
                    LOG.info("OBS reproduciendo %s (%s)", path, "continuidad" if loop else slot.kind)
                else:
                    notify(message)
                current = target
            else:
                status = obs.status()
                state = status["mediaState"]
                if path and (state in {"OBS_MEDIA_STATE_ERROR", "OBS_MEDIA_STATE_STOPPED"}
                             or (loop and state == "OBS_MEDIA_STATE_ENDED")):
                    raise RuntimeError(f"La fuente de OBS informó {state}.")
            stop.wait(0.5)
        except Exception as exc:
            if playback:
                playback(None, None, False)
            LOG.warning("OBS: %s", exc)
            notify(f"Reintentando · {exc}")
            obs.close()
            current = None
            stop.wait(3)
    obs.close()

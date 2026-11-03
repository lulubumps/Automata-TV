"""OBS simulado (obs-websocket v5, msgpack) para probar sin abrir OBS."""
import asyncio
import time

import msgpack
from websockets.asyncio.server import serve


class MockObs:
    def __init__(self, duration: float = 0.3, silent: bool = False, platform: str = "windows", input_exists: bool = True, active: bool = True):
        self.duration = duration
        self.platform, self.input_exists, self.active = platform, input_exists, active
        self.local_file = ""
        self.silent = silent  # True: nunca reproduce (simula escena fuera del aire / ruta mala)
        self.played: list[str] = []
        self.file = ""
        self.started = 0.0
        self.server = None
        self.port = 0

    async def _handler(self, ws):
        pack = msgpack.packb
        await ws.send(pack({"op": 0, "d": {"obsWebSocketVersion": "5.3.0", "rpcVersion": 1}}))
        async for raw in ws:
            m = msgpack.unpackb(raw)
            if m["op"] == 1:
                await ws.send(pack({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
                continue
            if m["op"] != 6:
                continue
            d = m["d"]
            kind, data, out = d["requestType"], d.get("requestData") or {}, {}
            status = {"result": True, "code": 100}
            if kind == "SetInputSettings":
                self.file = self.local_file = data["inputSettings"]["local_file"]
            elif kind == "GetVersion":
                out = {"obsVersion": "31.0.0", "obsWebSocketVersion": "5.5.0", "platform": self.platform, "platformDescription": "mock"}
            elif kind == "GetInputList":
                out = {"inputs": [{"inputName": "TV_PLAYER", "inputKind": "ffmpeg_source"}] if self.input_exists else [{"inputName": "Otra", "inputKind": "ffmpeg_source"}]}
            elif kind == "GetInputSettings":
                if not self.input_exists:
                    status = {"result": False, "code": 600, "comment": "No input was found with the name: " + data["inputName"]}
                else:
                    out = {"inputKind": "ffmpeg_source", "inputSettings": {"local_file": self.local_file, "looping": False}}
            elif kind == "GetSourceActive":
                out = {"videoActive": self.active, "videoShowing": self.active}
            elif kind == "GetCurrentProgramScene":
                out = {"currentProgramSceneName": "TV"}
            elif kind == "GetStudioModeEnabled":
                out = {"studioModeEnabled": False}
            elif kind == "GetSceneItemId":
                out = {"sceneItemId": 1}
            elif kind == "GetSceneItemEnabled":
                out = {"sceneItemEnabled": True}
            elif kind == "TriggerMediaInputAction" and data["mediaAction"].endswith("RESTART"):
                self.started = time.monotonic()
                self.played.append(self.file)
            elif kind == "GetMediaInputStatus":
                el = time.monotonic() - self.started
                if self.silent:
                    out = {"mediaState": "OBS_MEDIA_STATE_NONE", "mediaDuration": None, "mediaCursor": None}
                else:
                    ended = el >= self.duration
                    out = {
                        "mediaState": "OBS_MEDIA_STATE_ENDED" if ended else "OBS_MEDIA_STATE_PLAYING",
                        "mediaDuration": int(self.duration * 1000),
                        "mediaCursor": int(min(el, self.duration) * 1000),
                    }
            await ws.send(
                pack({"op": 7, "d": {"requestType": kind, "requestId": d["requestId"], "requestStatus": status, "responseData": out}})
            )

    async def start(self, port: int = 0):
        self.server = await serve(self._handler, "127.0.0.1", port, subprotocols=["obswebsocket.msgpack"])
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    @property
    def names(self) -> list[str]:
        return [f.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0] for f in self.played]


if __name__ == "__main__":  # python -m tests.mock_obs  → OBS simulado en el puerto 4455
    async def main():
        m = await MockObs(duration=5).start(4455)
        print(f"OBS simulado en ws://127.0.0.1:{m.port}")
        await asyncio.Future()

    asyncio.run(main())

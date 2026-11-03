from fastapi.testclient import TestClient

from app import __version__
from app.engine import Engine
from app.main import create_app


def test_api_and_websocket(tmp_path, media):
    engine = Engine(tmp_path / "data", media)
    with TestClient(create_app(engine)) as c:
        health = c.get("/api/health").json()
        assert health["ok"] is True and health["version"] == __version__
        assert "<title>Automata TV" in c.get("/").text

        lib = c.get("/api/library").json()
        assert lib["serie"]["folders"][0]["name"] == "Serie X"

        items = lib["serie"]["folders"][0]["folders"][0]["items"]
        assert c.post("/api/playlist/add", json={"items": items}).json() == {"ok": True}
        bad = c.post("/api/playlist/add", json={"items": [{"category": "pelicula", "path": "/etc/passwd"}]})
        assert bad.status_code == 400 and "error" in bad.json()

        with c.websocket_connect("/ws") as ws:
            snap = ws.receive_json()
            assert [p["title"] for p in snap["playlist"]] == ["ep01", "ep02", "ep10"]
            assert snap["status"] == "stopped" and snap["config"]["folders"]["serie"] == "Series"

        first = snap["playlist"][0]["id"]
        c.post("/api/playlist/move", json={"id": first, "dir": "down"})
        titles = [p["title"] for p in engine.snapshot()["playlist"]]
        assert titles == ["ep02", "ep01", "ep10"]
        c.post("/api/playlist/clear")
        assert engine.snapshot()["playlist"] == []

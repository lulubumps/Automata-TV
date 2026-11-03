import asyncio
import os

from app.engine import Engine
from tests.conftest import fast_engine, wait_for
from tests.mock_obs import MockObs


def test_library_tree_and_natural_order(tmp_path, media):
    async def run():
        e = Engine(tmp_path / "data", media)
        await e.scan_library()
        serie = e.library["serie"]["folders"][0]
        assert serie["name"] == "Serie X"
        temp = serie["folders"][0]
        assert [i["title"] for i in temp["items"]] == ["ep01", "ep02", "ep10"]  # ep2 antes que ep10; sin ._ ni .txt
        assert temp["items"][0]["group"] == "Serie X / Temporada 1"
        assert e.library["serie"]["count"] == 3
        assert len(e.commercials) == 1

    asyncio.run(run())


def test_air_order_with_breaks(tmp_path, media):
    async def run():
        mock = await MockObs(duration=0.3).start()
        e = fast_engine(tmp_path, media, mock.port)
        await e.start_background()
        try:
            serie = e.library["serie"]["folders"][0]["folders"][0]["items"]
            peli = e.library["pelicula"]["folders"][0]["items"][0]
            e.add_items([peli, *serie])
            await wait_for(lambda: e.connected, what="conexión a OBS")
            await e.start()
            await wait_for(lambda: len(mock.names) >= 8, what="8 reproducciones")
            assert mock.names[:8] == ["Pelicula Uno", "Spot1", "ep01", "Spot1", "ep02", "Spot1", "ep10", "Spot1"]
            assert e.snapshot()["status"] == "playing"
        finally:
            await e.stop()
            await e.shutdown()
            await mock.stop()

    asyncio.run(run())


def test_path_mapping_to_obs(tmp_path, media):
    e = Engine(tmp_path / "data", media)
    p = str(media / "Series" / "Serie X" / "Temporada 1" / "ep01.mp4")
    e.config["obs"]["mediaRoot"] = "C:/TV"
    assert e.to_obs_path(p) == "C:\\TV\\Series\\Serie X\\Temporada 1\\ep01.mp4"
    e.config["obs"]["mediaRoot"] = "/home/yo/TV/"
    assert e.to_obs_path(p) == "/home/yo/TV/Series/Serie X/Temporada 1/ep01.mp4"
    e.config["obs"]["mediaRoot"] = ""
    assert e.to_obs_path(p) == p


def test_obs_receives_mapped_path(tmp_path, media):
    async def run():
        mock = await MockObs(duration=5).start()
        e = fast_engine(tmp_path, media, mock.port)
        e.config["obs"]["mediaRoot"] = "D:\\Videos"
        await e.start_background()
        try:
            e.add_items([e.library["pelicula"]["folders"][0]["items"][0]])
            await wait_for(lambda: e.connected, what="conexión")
            await e.start()
            await wait_for(lambda: mock.played, what="reproducción")
            assert mock.played[0] == "D:\\Videos\\Peliculas\\Accion\\Pelicula Uno.mp4"
        finally:
            await e.shutdown()
            await mock.stop()

    asyncio.run(run())


def test_stops_when_obs_never_plays(tmp_path, media):
    """Si OBS no reproduce (escena fuera del aire o ruta mala), no quema toda la parrilla: se detiene."""
    async def run():
        mock = await MockObs(silent=True).start()
        e = fast_engine(tmp_path, media, mock.port)
        await e.start_background()
        try:
            serie = e.library["serie"]["folders"][0]["folders"][0]["items"]
            e.add_items(serie * 3)
            await wait_for(lambda: e.connected, what="conexión")
            await e.start()
            await wait_for(lambda: e.status == "stopped", timeout=10, what="detención por falla")
            assert any("no reproduce" in l for l in e.logs)
            assert len(mock.played) <= 3
        finally:
            await e.shutdown()
            await mock.stop()

    asyncio.run(run())


def test_rejects_paths_outside_media(tmp_path, media):
    async def run():
        e = Engine(tmp_path / "data", media)
        for bad in ("/etc/passwd", "../outside.mp4"):
            try:
                e.add_items([{"category": "pelicula", "path": bad}])
            except Exception as ex:
                assert "dentro de" in str(ex) or "No existe" in str(ex)
            else:
                raise AssertionError("debió rechazar " + bad)
        try:
            await e.update_config({"folders": {"pelicula": "/etc"}})
        except Exception as ex:
            assert "dentro de" in str(ex)
        else:
            raise AssertionError("debió rechazar la carpeta")

    asyncio.run(run())


def test_state_persists(tmp_path, media):
    async def run():
        e = Engine(tmp_path / "data", media)
        await e.scan_library()
        e.add_items(e.library["serie"]["folders"][0]["folders"][0]["items"])
        await e.update_config({"breakCount": 3, "loop": False})
        e2 = Engine(tmp_path / "data", media)
        assert [p["title"] for p in e2.playlist] == ["ep01", "ep02", "ep10"]
        assert e2.config["breakCount"] == 3 and e2.config["loop"] is False

    asyncio.run(run())

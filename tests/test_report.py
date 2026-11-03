import asyncio

from fastapi.testclient import TestClient

from app.engine import Engine
from app.main import create_app
from app.report import build_report
from tests.conftest import fast_engine, wait_for
from tests.mock_obs import MockObs


async def _with_obs(tmp_path, media, mock_kwargs, setup=None, test=True):
    mock = await MockObs(duration=5, **mock_kwargs).start()
    e = fast_engine(tmp_path, media, mock.port)
    if setup:
        setup(e)
    await e.start_background()
    try:
        await wait_for(lambda: e.connected, what="conexión")
        return (await build_report(e, test=test, test_timeout=1.5))["text"]
    finally:
        await e.shutdown()
        await mock.stop()


def test_report_without_obs(tmp_path, media):
    async def run():
        e = Engine(tmp_path / "data", media)
        await e.scan_library()
        r = await build_report(e)
        assert "[PROBLEMA] OBS no está conectado" in r["text"] and r["problems"] >= 1
        assert "Peliculas" in r["text"] and "ep01" in r["text"]

    asyncio.run(run())


def test_report_detects_windows_obs_with_container_paths(tmp_path, media):
    text = asyncio.run(_with_obs(tmp_path, media, {"platform": "windows"}))
    assert "[PROBLEMA] OBS corre en Windows pero recibió una ruta de Linux/contenedor" in text
    assert "== PRUEBA DE REPRODUCCIÓN ==" in text


def test_report_ok_with_mapped_path(tmp_path, media):
    def setup(e):
        e.config["obs"]["mediaRoot"] = "C:\\TV"

    text = asyncio.run(_with_obs(tmp_path, media, {"platform": "windows"}, setup))
    assert "[PROBLEMA]" not in text
    assert "[OK] La prueba de reproducción funcionó" in text
    assert "C:\\TV\\Peliculas\\Accion\\Pelicula Uno.mp4" in text


def test_report_missing_input(tmp_path, media):
    text = asyncio.run(_with_obs(tmp_path, media, {"input_exists": False}, test=False))
    assert 'no existe una fuente llamada "TV_PLAYER"' in text and "Otra" in text


def test_report_inactive_source(tmp_path, media):
    text = asyncio.run(_with_obs(tmp_path, media, {"active": False}, test=False))
    assert "La fuente no está activa en OBS" in text and "Escena al aire: TV" in text


def test_report_test_failure_when_obs_never_plays(tmp_path, media):
    def setup(e):
        e.config["obs"]["mediaRoot"] = "C:\\TV"

    text = asyncio.run(_with_obs(tmp_path, media, {"silent": True}, setup))
    assert "OBS no reprodujo el video de prueba" in text


def test_report_endpoint_hides_password(tmp_path, media):
    engine = Engine(tmp_path / "data", media)
    engine.config["obs"]["password"] = "secreto123"
    with TestClient(create_app(engine)) as c:
        r = c.post("/api/report", json={}).json()
        assert "INFORME DE AUTOMATA TV" in r["text"]
        assert "secreto123" not in r["text"] and "contraseña=definida" in r["text"]
        assert isinstance(r["problems"], int)

import asyncio
import time

import pytest

from app.engine import Engine
from tests.mock_obs import MockObs


def make_media(root):
    """Crea una biblioteca de prueba con películas, una serie y comerciales."""
    for rel in [
        "Peliculas/Accion/Pelicula Uno.mp4",
        "Series/Serie X/Temporada 1/ep02.mp4",
        "Series/Serie X/Temporada 1/ep10.mp4",
        "Series/Serie X/Temporada 1/ep01.mp4",
        "Series/Serie X/Temporada 1/notas.txt",
        "Series/Serie X/Temporada 1/._ep01.mp4",
        "Comerciales/Spot1.mp4",
    ]:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"")
    return root


@pytest.fixture
def media(tmp_path):
    return make_media(tmp_path / "media")


def fast_engine(tmp_path, media, port, **kw):
    env = {"OBS_HOST": "127.0.0.1", "OBS_PORT": str(port)}
    return Engine(tmp_path / "data", media, env=env, tick_s=0.1, min_play_s=0.1, reconnect_s=0.2, stall_s=0.4, **kw)


async def wait_for(cond, timeout=10, what="condición"):
    t = time.monotonic()
    while not cond():
        if time.monotonic() - t > timeout:
            raise AssertionError(f"Tiempo agotado esperando: {what}")
        await asyncio.sleep(0.05)

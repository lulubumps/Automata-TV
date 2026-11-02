# Automata TV - automatizador de television 24/7 sobre OBS
# Copyright (C) 2026 Lulubumps
#
# Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo
# los terminos de la Licencia Publica General de GNU, version 3, publicada por
# la Free Software Foundation.
#
# Se distribuye con la esperanza de que sea util, pero SIN NINGUNA GARANTIA;
# ni siquiera la garantia implicita de COMERCIABILIDAD o IDONEIDAD PARA UN
# PROPOSITO PARTICULAR. Consulta el archivo LICENSE para mas detalles.

from pathlib import Path

from . import __version__

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .engine import Engine
from .obs_link import ObsLink, ObsRequestError, ObsUnavailable

app = FastAPI(title="Automata TV", version=__version__)
engine = Engine(ObsLink(settings.obs_host, settings.obs_port, settings.obs_password), settings)


class PlayBody(BaseModel):
    path: str


def guarded(fn, *args):
    try:
        fn(*args)
        return {"ok": True}
    except ObsUnavailable as e:
        raise HTTPException(503, f"OBS no responde: {e}")
    except ObsRequestError as e:
        raise HTTPException(502, f"OBS rechazó la acción: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/status")
def status():
    return {**engine.status(), "version": __version__}


@app.get("/api/library")
def library():
    return engine.library()


@app.post("/api/setup")
def setup():
    return guarded(engine.setup)


@app.post("/api/play")
def play(body: PlayBody):
    return guarded(engine.play, body.path)


@app.post("/api/stop")
def stop():
    return guarded(engine.stop)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")

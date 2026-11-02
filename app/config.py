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

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    obs_host: str = "host.docker.internal"
    obs_port: int = 4455
    obs_password: str = ""

    media_dir: str = "/media"   # ruta dentro del contenedor
    obs_media_dir: str = ""     # misma carpeta vista desde OBS (host)

    scene_name: str = "TV-A"
    source_name: str = "TV-A-media"


settings = Settings()

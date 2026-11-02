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

"""Conexión a OBS (obs-websocket v5) con reconexión automática."""
import threading
import time

import obsws_python as obs
from obsws_python.error import OBSSDKRequestError


class ObsUnavailable(Exception):
    """OBS no responde (apagado, puerto o contraseña incorrectos)."""


class ObsRequestError(Exception):
    """OBS respondió, pero rechazó la petición."""


class ObsLink:
    def __init__(self, host: str, port: int, password: str):
        self.host, self.port, self.password = host, port, password
        self.error: str | None = None
        self._client = None
        self._lock = threading.Lock()
        self._last_attempt = 0.0

    def _connect(self):
        if time.monotonic() - self._last_attempt < 3:  # no martillar a OBS
            return
        self._last_attempt = time.monotonic()
        try:
            self._client = obs.ReqClient(
                host=self.host, port=self.port, password=self.password, timeout=3
            )
            self.error = None
        except Exception as e:
            self._client = None
            self.error = str(e) or e.__class__.__name__

    def _drop(self):
        try:
            if self._client:
                self._client.disconnect()
        except Exception:
            pass
        self._client = None

    def call(self, fn):
        """Ejecuta fn(cliente). Reconecta si hace falta."""
        with self._lock:
            if self._client is None:
                self._connect()
            if self._client is None:
                raise ObsUnavailable(self.error or "Sin conexión con OBS")
            try:
                return fn(self._client)
            except OBSSDKRequestError as e:
                raise ObsRequestError(str(e)) from e
            except Exception as e:
                self._drop()
                self.error = str(e) or e.__class__.__name__
                raise ObsUnavailable(self.error) from e

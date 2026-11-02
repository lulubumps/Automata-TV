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

"""Motor de reproducción (Fase 1): una escena con una fuente de medios."""
import re
from pathlib import Path

from .config import Settings
from .obs_link import ObsLink, ObsRequestError, ObsUnavailable

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts", ".mpg", ".mpeg", ".flv"}
ACTION = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_"


class Engine:
    def __init__(self, link: ObsLink, cfg: Settings):
        self.link, self.cfg = link, cfg

    # ---------- biblioteca ----------
    def library(self) -> list[dict]:
        root = Path(self.cfg.media_dir)
        if not root.is_dir():
            return []
        items = []
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in VIDEO_EXT:
                rel = p.relative_to(root)
                items.append({
                    "path": rel.as_posix(),
                    "name": p.stem,
                    "category": rel.parts[0] if len(rel.parts) > 1 else "sin carpeta",
                })
        items.sort(key=lambda i: (i["category"].lower(), i["path"].lower()))
        return items

    def _resolve(self, rel: str) -> str:
        root = Path(self.cfg.media_dir).resolve()
        p = (root / rel).resolve()
        if root not in p.parents or not p.is_file():
            raise ValueError("El archivo no existe o está fuera de la biblioteca")
        return p.relative_to(root).as_posix()

    def _host_path(self, rel: str) -> str:
        base = self.cfg.obs_media_dir or self.cfg.media_dir
        sep = "\\" if "\\" in base else "/"
        return base.rstrip("/\\") + sep + rel.replace("/", sep)

    # ---------- OBS ----------
    def _ensure(self, c):
        cfg = self.cfg
        if cfg.scene_name not in [s["sceneName"] for s in c.get_scene_list().scenes]:
            c.create_scene(cfg.scene_name)
        if cfg.source_name not in [i["inputName"] for i in c.get_input_list().inputs]:
            c.create_input(
                cfg.scene_name, cfg.source_name, "ffmpeg_source",
                {"is_local_file": True, "local_file": "",
                 "close_when_inactive": False, "restart_on_activate": False},
                True,
            )

    def setup(self):
        self.link.call(self._ensure)

    def play(self, rel: str):
        host_path = self._host_path(self._resolve(rel))
        cfg = self.cfg

        def run(c):
            self._ensure(c)
            c.set_input_settings(
                cfg.source_name,
                {"is_local_file": True, "local_file": host_path,
                 "close_when_inactive": False, "restart_on_activate": False},
                True,
            )
            c.set_current_program_scene(cfg.scene_name)
            c.trigger_media_input_action(cfg.source_name, ACTION + "RESTART")

        self.link.call(run)

    def stop(self):
        self.link.call(lambda c: c.trigger_media_input_action(self.cfg.source_name, ACTION + "STOP"))

    def status(self) -> dict:
        cfg = self.cfg
        out = {"connected": False, "error": None, "obs_version": None,
               "program_scene": None, "scene": cfg.scene_name, "ready": False, "media": None}

        def run(c):
            res = {"obs_version": c.get_version().obs_version}
            r = c.get_current_program_scene()
            res["program_scene"] = (getattr(r, "current_program_scene_name", None)
                                    or getattr(r, "scene_name", None))
            scenes = [s["sceneName"] for s in c.get_scene_list().scenes]
            inputs = [i["inputName"] for i in c.get_input_list().inputs]
            res["ready"] = cfg.scene_name in scenes and cfg.source_name in inputs
            if res["ready"]:
                st = c.get_media_input_status(cfg.source_name)
                f = c.get_input_settings(cfg.source_name).input_settings.get("local_file", "")
                res["media"] = {
                    "state": st.media_state,
                    "duration_ms": st.media_duration,
                    "cursor_ms": st.media_cursor,
                    "file": re.split(r"[\\/]", f)[-1] if f else "",
                }
            return res

        try:
            out.update(self.link.call(run))
            out["connected"] = True
        except ObsUnavailable as e:
            out["error"] = str(e)
        except ObsRequestError as e:
            out["connected"] = True
            out["error"] = str(e)
        return out

"""Informe de diagnóstico: reúne en un texto todo lo necesario para ver por qué no se reproduce un video."""
from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
from datetime import datetime
from importlib import metadata

from . import __version__
from .engine import ACT_RESTART, ACT_STOP, CATEGORIES, ST_ENDED, ST_PLAYING, flatten

STARTED = time.time()


def _ver(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except Exception:
        return "?"


async def _safe(e, kind: str, data: dict | None = None, timeout: float = 5) -> dict:
    try:
        return await e._call(kind, data or {}, timeout=timeout)
    except Exception as ex:
        return {"_error": str(ex) or type(ex).__name__}


# ------------------------------------------------------------------ recolección
async def _obs_info(e) -> dict:
    o = e.config["obs"]
    inp = o["input"]
    info: dict = {"connected": e.connected, "host": f"{o['host']}:{o['port']}", "last_error": e._last_conn_error, "input_name": inp}
    if not e.connected:
        return info

    v = await _safe(e, "GetVersion")
    info["version"] = v if "_error" in v else {k: v.get(k) for k in ("obsVersion", "obsWebSocketVersion", "platform", "platformDescription")}

    lst = await _safe(e, "GetInputList")
    if "_error" not in lst:
        inputs = lst.get("inputs", [])
        info["media_inputs"] = [i["inputName"] for i in inputs if i.get("inputKind") == "ffmpeg_source"]
        info["inputs_total"] = len(inputs)

    s = await _safe(e, "GetInputSettings", {"inputName": inp})
    if "_error" in s:
        info["input"] = {"exists": False, "error": s["_error"]}
    else:
        st = s.get("inputSettings") or {}
        info["input"] = {
            "exists": True,
            "kind": s.get("inputKind"),
            "local_file": st.get("local_file"),
            "looping": st.get("looping"),
            "close_when_inactive": st.get("close_when_inactive"),
            "restart_on_activate": st.get("restart_on_activate"),
        }
        a = await _safe(e, "GetSourceActive", {"sourceName": inp})
        info["active"] = a if "_error" in a else {"videoActive": a.get("videoActive"), "videoShowing": a.get("videoShowing")}
        m = await _safe(e, "GetMediaInputStatus", {"inputName": inp})
        info["media"] = m if "_error" in m else {"state": m.get("mediaState"), "cursor_ms": m.get("mediaCursor"), "duration_ms": m.get("mediaDuration")}

    sc = await _safe(e, "GetCurrentProgramScene")
    scene = None if "_error" in sc else (sc.get("currentProgramSceneName") or sc.get("sceneName"))
    info["program_scene"] = scene
    sm = await _safe(e, "GetStudioModeEnabled")
    info["studio_mode"] = None if "_error" in sm else sm.get("studioModeEnabled")

    if scene and info["input"].get("exists"):
        it = await _safe(e, "GetSceneItemId", {"sceneName": scene, "sourceName": inp})
        if "_error" in it:
            info["in_program_scene"] = False  # puede estar dentro de una escena anidada
        else:
            info["in_program_scene"] = True
            en = await _safe(e, "GetSceneItemEnabled", {"sceneName": scene, "sceneItemId": it.get("sceneItemId")})
            info["scene_item_enabled"] = None if "_error" in en else en.get("sceneItemEnabled")
    return info


def _library_info(e) -> dict:
    root = e.media_root
    info: dict = {"media_root": str(root), "exists": root.is_dir(), "in_docker": os.path.exists("/.dockerenv")}
    try:
        info["top_level"] = sorted(os.listdir(root))[:30]
    except OSError as ex:
        info["top_level_error"] = str(ex)
    cats = {}
    for cat in CATEGORIES:
        value = (e.config["folders"].get(cat) or "").strip()
        c: dict = {"configured": value or "(vacío)"}
        if value:
            p = e._abs(value)
            c["resolved"], c["exists"] = str(p), p.is_dir()
        node = e.library[cat]
        c["videos"] = node["count"]
        c["samples"] = [i["path"] for i in flatten(node)[:3]]
        cats[cat] = c
    info["categories"] = cats
    sample = next((i for cat in CATEGORIES for i in flatten(e.library[cat])), None)
    if sample:
        info["sample_translation"] = {"container": sample["path"], "obs": e.to_obs_path(sample["path"])}
    return info


async def _selftest(e, timeout: float) -> dict:
    """Carga un video en OBS y comprueba si llega a reproducirse. Interrumpe lo que esté al aire."""
    r: dict = {"ran": False}
    if not e.connected:
        return {**r, "skipped": "OBS no está conectado"}
    if e.status == "playing":
        return {**r, "skipped": "La emisión está en marcha; detenla antes de hacer la prueba"}
    item = next((i for cat in ("pelicula", "serie") for i in flatten(e.library[cat])), None) or (e.commercials[0] if e.commercials else None)
    if not item:
        return {**r, "skipped": "No hay videos en la biblioteca"}
    inp = e.config["obs"]["input"]
    r.update(ran=True, container_path=item["path"], obs_path=e.to_obs_path(item["path"]))
    try:
        await e._call("SetInputSettings", {"inputName": inp, "inputSettings": {"local_file": r["obs_path"], "is_local_file": True, "looping": False}})
        await e._call("TriggerMediaInputAction", {"inputName": inp, "mediaAction": ACT_RESTART})
    except Exception as ex:
        r["error"] = str(ex)
        return r
    seen: list[str] = []
    t0, state = time.monotonic(), None
    while time.monotonic() - t0 < timeout:
        await asyncio.sleep(0.5)
        m = await _safe(e, "GetMediaInputStatus", {"inputName": inp})
        state = (m.get("mediaState") or "?").replace("OBS_MEDIA_STATE_", "") if "_error" not in m else "ERROR"
        if not seen or seen[-1] != state:
            seen.append(state)
        if state in ("PLAYING", "ENDED"):
            break
    r["states"], r["played"] = seen, state in ("PLAYING", "ENDED")
    a = await _safe(e, "GetSourceActive", {"sourceName": inp})
    r["source_active"] = a.get("videoActive") if "_error" not in a else None
    await _safe(e, "TriggerMediaInputAction", {"inputName": inp, "mediaAction": ACT_STOP})
    return r


# --------------------------------------------------------------------- hallazgos
def _findings(d: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    add = lambda lvl, msg: out.append((lvl, msg))
    obs, lib, cfg = d["obs"], d["library"], d["config"]

    if not obs["connected"]:
        add("PROBLEMA", f"OBS no está conectado ({obs['host']}). Último error: {obs.get('last_error') or 'sin intentos registrados'}. "
                        "Revisa servidor WebSocket, puerto, contraseña y el servidor configurado (con Docker: host.docker.internal).")
    else:
        inp = obs.get("input", {})
        name = obs["input_name"]
        if not inp.get("exists"):
            media = obs.get("media_inputs") or []
            add("PROBLEMA", f'En OBS no existe una fuente llamada "{name}" ({inp.get("error")}). '
                            f"Fuentes de medios que sí existen: {', '.join(media) if media else 'ninguna'}.")
        else:
            if inp.get("kind") != "ffmpeg_source":
                add("PROBLEMA", f'La fuente "{name}" es de tipo {inp.get("kind")}; debe ser una "Fuente de medios" (ffmpeg_source).')
            if inp.get("looping"):
                add("AVISO", 'La fuente tiene "Repetir" activado: el video nunca terminará y no pasará al siguiente.')
            act = obs.get("active") or {}
            if act.get("videoActive") is False:
                add("PROBLEMA", f'La fuente no está activa en OBS: no está visible en la escena al aire (escena: {obs.get("program_scene")}, '
                                f'modo estudio: {obs.get("studio_mode")}). Una fuente de medios no reproduce si no está al aire.')
            if obs.get("in_program_scene") is True and obs.get("scene_item_enabled") is False:
                add("PROBLEMA", "La fuente está en la escena al aire pero con el ojito apagado.")
            lf = inp.get("local_file") or ""
            plat = ((obs.get("version") or {}).get("platform") or "").lower()
            sample = (d["library"].get("sample_translation") or {}).get("obs") or ""
            probe = lf or sample  # lo cargado en OBS o, si no hay nada, lo que se enviaría
            what = "cargada en OBS" if lf else "que se enviaría a OBS"
            path_problem = False
            if probe:
                if plat == "windows" and (probe.startswith("/") or "/media/" in probe):
                    path_problem = True
                    add("PROBLEMA", f"OBS corre en Windows pero recibió una ruta de Linux/contenedor ({what}): {probe}. "
                                    "Configura la carpeta de videos vista desde OBS (OBS_MEDIA_ROOT), por ejemplo C:\\TV.")
                elif plat in ("linux", "ubuntu", "macos") and (":" in probe[:3] or "\\" in probe):
                    path_problem = True
                    add("PROBLEMA", f"OBS corre en {plat} pero recibió una ruta de Windows ({what}): {probe}.")
            root = (cfg["obs"].get("mediaRoot") or "").strip().replace("\\", "/").rstrip("/").lower()
            if lf and root and not lf.replace("\\", "/").lower().startswith(root):
                add("AVISO", f"El archivo cargado en OBS ({lf}) no está dentro de la carpeta configurada vista desde OBS ({cfg['obs']['mediaRoot']}).")
            if not lf and not path_problem:
                add("AVISO", "OBS no tiene ningún archivo cargado en la fuente: el automatizador aún no ha enviado ninguno.")
            if d["engine"]["status"] == "playing":
                st = (obs.get("media") or {}).get("state")
                if st and st != ST_PLAYING:
                    add("PROBLEMA", f"El automatizador cree que hay algo al aire, pero OBS reporta el estado {st}.")

    if lib["in_docker"] and not (cfg["obs"].get("mediaRoot") or "").strip():
        add("AVISO", "Estás en Docker y OBS_MEDIA_ROOT está vacío: OBS recibirá rutas del contenedor (/media/...) que no existen en su equipo.")
    if not lib["exists"] or not lib.get("top_level"):
        add("PROBLEMA", f"La carpeta de videos {lib['media_root']} está vacía o no existe. Revisa MEDIA_DIR (ruta absoluta) y, en Docker Desktop, "
                        "que la unidad esté compartida.")
    else:
        for cat, c in lib["categories"].items():
            if c.get("resolved") and not c.get("exists"):
                add("PROBLEMA", f"La carpeta de {cat}s ({c['resolved']}) no existe. Carpetas encontradas: {', '.join(lib['top_level'])}.")
            elif c.get("resolved") and c["videos"] == 0:
                add("AVISO", f"La carpeta de {cat}s existe pero no tiene videos reconocibles.")

    t = d.get("test")
    if t and t.get("ran"):
        if t.get("error"):
            add("PROBLEMA", f"La prueba de reproducción falló al hablar con OBS: {t['error']}")
        elif t.get("played"):
            add("OK", f"La prueba de reproducción funcionó (estados: {' > '.join(t['states'])}).")
        else:
            add("PROBLEMA", f"OBS no reprodujo el video de prueba (estados: {' > '.join(t.get('states') or ['?'])}). Ruta enviada: {t['obs_path']}")
    elif t and t.get("skipped"):
        add("AVISO", f"No se hizo la prueba de reproducción: {t['skipped']}.")

    if not any(l in ("PROBLEMA", "AVISO") for l, _ in out):
        add("OK", "No se detectaron problemas evidentes en la configuración.")
    return out


# ------------------------------------------------------------------------ salida
def _render(d: dict) -> str:
    L: list[str] = []
    a = d["app"]
    L += ["INFORME DE AUTOMATA TV", f"Generado: {a['generated']}",
          f"Versión {a['version']} | Python {a['python']} | simpleobsws {a['simpleobsws']} | {a['system']} | Docker: {'sí' if d['library']['in_docker'] else 'no'}",
          f"Activo hace: {a['uptime']}", ""]
    L.append("== RESUMEN ==")
    L += [f"[{lvl}] {msg}" for lvl, msg in d["findings"]]

    o = d["obs"]
    L += ["", "== OBS ==", f"Conectado: {o['connected']}  ({o['host']})", f"Fuente configurada: {o['input_name']}"]
    if o.get("version"):
        v = o["version"]
        L.append(f"OBS {v.get('obsVersion')} | obs-websocket {v.get('obsWebSocketVersion')} | plataforma: {v.get('platform')} ({v.get('platformDescription')})")
    if o.get("media_inputs") is not None:
        L.append(f"Fuentes de medios en OBS: {', '.join(o['media_inputs']) or 'ninguna'}")
    if o.get("input"):
        L.append("Fuente: " + ", ".join(f"{k}={v}" for k, v in o["input"].items()))
    for k, label in (("active", "Activa en el aire"), ("media", "Estado de reproducción")):
        if o.get(k):
            L.append(f"{label}: " + ", ".join(f"{kk}={vv}" for kk, vv in o[k].items()))
    if "program_scene" in o:
        L.append(f"Escena al aire: {o.get('program_scene')} | Modo estudio: {o.get('studio_mode')} | En esa escena: {o.get('in_program_scene')} | Visible: {o.get('scene_item_enabled')}")

    lib = d["library"]
    L += ["", "== VIDEOS ==", f"Carpeta de videos (vista por el programa): {lib['media_root']}  existe={lib['exists']}",
          f"Contenido de primer nivel: {', '.join(lib.get('top_level', [])) or lib.get('top_level_error', '(vacío)')}"]
    for cat, c in lib["categories"].items():
        L.append(f"- {cat}: configurada='{c['configured']}' resuelta={c.get('resolved', '-')} existe={c.get('exists', '-')} videos={c['videos']}")
        L += [f"    ej: {s}" for s in c["samples"]]
    if lib.get("sample_translation"):
        s = lib["sample_translation"]
        L += ["Traducción de ruta (ejemplo):", f"    contenedor: {s['container']}", f"    enviada a OBS: {s['obs']}"]

    c = d["config"]
    L += ["", "== AJUSTES (sin contraseñas) ==",
          f"OBS: {c['obs']['host']}:{c['obs']['port']} fuente={c['obs']['input']} carpeta_vista_desde_OBS='{c['obs']['mediaRoot']}' contraseña={'definida' if c['obs']['hasPassword'] else 'vacía'}",
          f"Tandas: {c['breakCount']} comercial(es) tras cada programa | Repetir parrilla: {c['loop']}",
          f"Variables de entorno: {d['env']}"]

    e = d["engine"]
    L += ["", "== EMISIÓN ==", f"Estado: {e['status']} | Al aire: {e['current'] or '-'} | Parrilla: {e['playlist_len']} ítems (posición {e['index']})"]
    if d.get("test"):
        t = d["test"]
        L += ["", "== PRUEBA DE REPRODUCCIÓN =="]
        L += [f"{k}: {v}" for k, v in t.items()]
    L += ["", "== REGISTRO (más reciente al final) =="] + (d["logs"] or ["(sin entradas)"])
    return "\n".join(L)


async def build_report(e, test: bool = False, test_timeout: float = 6.0) -> dict:
    d: dict = {
        "app": {
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": __version__,
            "python": sys.version.split()[0],
            "simpleobsws": _ver("simpleobsws"),
            "system": f"{platform.system()} {platform.release()}",
            "uptime": f"{int(time.time() - STARTED) // 60} min",
        },
        "config": e.snapshot()["config"],
        "env": {k: os.environ[k] for k in ("OBS_HOST", "OBS_PORT", "OBS_INPUT", "OBS_MEDIA_ROOT", "MEDIA_DIR", "DATA_DIR", "TZ") if k in os.environ},
        "obs": await _obs_info(e),
        "library": _library_info(e),
        "engine": {"status": e.status, "index": e.index, "current": e.current["title"] if e.current else None, "playlist_len": len(e.playlist)},
        "logs": list(e.logs)[-40:],
    }
    if test:
        d["test"] = await _selftest(e, test_timeout)
    d["findings"] = _findings(d)
    return {
        "text": _render(d),
        "problems": sum(1 for l, _ in d["findings"] if l == "PROBLEMA"),
        "warnings": sum(1 for l, _ in d["findings"] if l == "AVISO"),
    }

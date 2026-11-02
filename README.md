# Automata TV

Automatizador de televisión 24/7 sobre OBS, con videos locales y salida a cualquier RTMP.

**Versión 0.10.0 · Fase 1:** conexión a OBS y reproducción. Historial de cambios en [CHANGELOG.md](CHANGELOG.md).

## Requisitos
- OBS Studio 28 o superior (trae obs-websocket v5)
- Docker y Docker Compose

## Puesta en marcha
1. En OBS: **Herramientas → Ajustes del servidor WebSocket**, activa el servidor y define una contraseña (puerto 4455).
2. Copia `.env.example` a `.env` y completa:
   - `OBS_PASSWORD`: la contraseña del paso anterior.
   - `MEDIA_HOST_DIR`: carpeta de videos de tu equipo. En Windows usa barras normales (`D:/Videos`).
3. Ordena los videos en subcarpetas (`peliculas/`, `series/`, `comerciales/`).
4. Levanta el contenedor: `docker compose up --build`
   (para dejarlo en segundo plano: `docker compose up -d --build`)
5. Abre http://localhost:8000

Al reproducir el primer video, la app crea en OBS la escena `TV-A` con la fuente `TV-A-media`. Configura tu salida RTMP en OBS como siempre.

## Solución de problemas
- **«OBS sin conexión»**: confirma que OBS está abierto, que el servidor WebSocket está activo y que `OBS_PASSWORD` coincide.
- **OBS no encuentra el archivo**: revisa que `MEDIA_HOST_DIR` sea la ruta real de tu equipo.
- **Linux**: el `docker-compose.yml` ya incluye `host.docker.internal`; si no conecta, revisa el firewall del puerto 4455.

## Estructura
```
VERSION
CHANGELOG.md
docker-compose.yml
Dockerfile
app/
  main.py      API (FastAPI) y servidor de la interfaz
  engine.py    biblioteca y reproducción
  obs_link.py  conexión a OBS con reconexión automática
  config.py    variables de entorno
  static/      interfaz web
```

## Fases
1. Conexión a OBS y reproducción (esta)
2. Motor A/B con Fade y detección de fin de video
3. Biblioteca (SQLite, ffprobe), cola y modo AUTO
4. Parrilla 24/7 y publicidad
5. As-Run, emergencia y pulido

## Desarrollo sin Docker
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
OBS_HOST=localhost MEDIA_DIR=./media uvicorn app.main:app --reload
```

## Contribuir
Automata TV es software libre (GPL-3.0) y recibe aportes. Lee [CONTRIBUTING.md](CONTRIBUTING.md), abre un issue con tu idea o envía un Pull Request.

## Licencia
[GPL-3.0](LICENSE) © 2026 Lulubumps

Puedes usar, estudiar, modificar y compartir Automata TV. Si distribuyes una versión modificada, debe publicarse también bajo GPL-3.0 con su código fuente.

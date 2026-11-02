# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado semántico.

## [0.10.0] - 2026-11-02

Primera versión (Fase 1: conexión a OBS y reproducción). Aún sin probar contra un OBS real.

### Añadido
- Conexión a OBS por obs-websocket v5, con reconexión automática.
- Creación automática de la escena `TV-A` y la fuente `TV-A-media`.
- Biblioteca de videos desde carpeta local, con filtro por subcarpeta y búsqueda.
- Reproducir y detener desde la interfaz web, con timecode y barra de progreso.
- Protección contra rutas fuera de la carpeta de videos.
- Empaquetado con Docker y Docker Compose.
- Licencia GPL-3.0, guía de contribución y plantillas de issues y Pull Requests.

# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado semántico.

## [0.10.1] - 2026-11-03

### Agregado
- **Informe de diagnóstico**: botón *Informe* en la interfaz que genera un texto sin contraseñas con el estado de OBS (versión, sistema, conexión), la fuente `TV_PLAYER` (existe, tipo, archivo cargado, si está al aire), la biblioteca de videos, la traducción de rutas hacia OBS, los ajustes y el registro. Incluye un resumen de problemas y avisos detectados. Se puede copiar o descargar como `.txt`.
- **Prueba de reproducción** opcional dentro del informe: carga un video en OBS y comprueba si arranca (no se ejecuta con la emisión en marcha).
- Endpoint `POST /api/report`.
- La versión se muestra en la interfaz y en `GET /api/health`.
- Pruebas del informe (`tests/test_report.py`) y de coherencia de versión (`tests/test_release.py`).
- Workflow `release.yml`: al subir una etiqueta `vX.Y.Z` crea el release en GitHub con las notas de este archivo.

### Cambiado
- La imagen de Docker declara su versión y licencia (etiquetas OCI).
- El OBS simulado de las pruebas responde más solicitudes del protocolo.

Versiones anteriores: ver el historial de commits.

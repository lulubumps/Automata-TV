# Automata TV para Esperanza TV

Automata TV programa episodios, comerciales e identificaciones a partir de MP4 y controla su reproducción en OBS Studio. El panel web muestra la biblioteca, la parrilla, el video en reproducción y el próximo evento.

## Empezar

1. Entra en `desktop` y copia [`.env.example`](desktop/.env.example) como `.env`.
2. Configura `MEDIA_PATH` con la carpeta de videos que ve Docker y `OBS_MEDIA_ROOT` con la ruta que usa OBS. Define las contraseñas del panel y de OBS.
3. Desde `desktop`, ejecuta `docker compose up -d --build`.
4. Abre <http://localhost:8000> e ingresa con el usuario `operador`.

Consulta la [guía de configuración de Docker y OBS](desktop/README.md#docker-con-panel-web) para instalar o actualizar una instalación existente. La [guía de escritorio](desktop/README.md#instalación-en-windows) describe la ejecución local en Windows.

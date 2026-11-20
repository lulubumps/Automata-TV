# Automata TV para Esperanza TV

App de escritorio para programar MP4 locales y reproducirlos en OBS según el reloj del PC. Prueba primero con una colección de escenas de ensayo y con la salida de streaming apagada. Al activar el automatizador, la escena de Automata TV toma la salida de programa de OBS.

## Instalación en Windows

1. Instala Python 3.10 o posterior con Tcl/Tk y FFmpeg con `ffprobe` disponible en el PATH. Comprueba con `ffprobe -version`.
2. En OBS Studio 28 o posterior, activa el servidor WebSocket desde **Herramientas → Ajustes del servidor WebSocket**. Usa el puerto 4455 y configura una contraseña.
3. Crea una escena llamada **Automata TV** con una **Fuente multimedia** visible llamada **TV_PLAYER**, directamente en la escena. Ajusta su encuadre y audio en OBS. Puedes usar otros nombres e ingresarlos en la app.
4. Desde la carpeta del proyecto, ejecuta en PowerShell:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r desktop\requirements.txt
   .\.venv\Scripts\python.exe desktop\automata.py
   ```

Si descargaste solamente la carpeta `desktop`, ejecuta los comandos dentro de esa carpeta y usa `requirements.txt` y `automata.py` sin el prefijo `desktop\`.

## Programación

1. Selecciona un **MP4 de continuidad**. Se reproduce en bucle durante los huecos y cuando falta el archivo del evento programado.
2. Escribe la fecha y hora local, elige el tipo y selecciona uno o varios MP4. Los archivos de una selección se agregan en orden alfabético, uno a continuación del otro. Numéralos con ceros iniciales para controlar el orden.
3. Agrega los comerciales como otro bloque. Para una pausa dentro de un episodio, programa el episodio como dos archivos MP4 separados y ubica los spots entre ambos.
4. Ingresa la contraseña del servidor WebSocket y pulsa **Activar automatización**. Si la activas o reconectas durante un evento, la app intenta situar el video según el tiempo transcurrido.
5. Pulsa **Ceder control a OBS** para volver a operar manualmente. La fuente conserva el último archivo cargado. La transmisión se inicia y finaliza en OBS.

La parrilla se guarda en `%LOCALAPPDATA%\AutomataTV\parrilla.json`. El registro rotativo queda en `emision.log` en la misma carpeta. La contraseña se ingresa en cada sesión.

Esta primera versión usa eventos por fecha, una sola salida OBS y cortes por reloj con comprobación cada medio segundo. Las transiciones dependen de la apertura y decodificación del archivo en OBS. La parrilla recurrente, las tandas por reglas, la gestión de directos y la recuperación de salida 24/7 quedan para las siguientes versiones.

## Docker con panel web

Docker ejecuta Automata TV, su panel y `ffprobe`. OBS Studio sigue abierto en el PC que reproduce los archivos. El contenedor usa la hora del host Docker y la muestra en la zona `CHANNEL_TZ` (`America/Santiago` por defecto).

1. Prepara la escena y la fuente en OBS como se indica arriba.
2. En la carpeta `desktop`, copia `.env.example` a `.env` (PowerShell: `Copy-Item .env.example .env`; Linux: `cp .env.example .env`). Completa `PANEL_PASSWORD` y `OBS_PASSWORD`. El panel usa el usuario `operador`. Mantén las claves fuera de Git.
3. Ajusta las rutas y la conexión según el montaje:

   | Ajuste | Docker y OBS en el mismo PC Windows | Docker en un servidor Linux y OBS en Windows |
   |---|---|---|
   | `MEDIA_PATH` | `C:/TV` | `/mnt/tv`, carpeta compartida ya montada en el servidor |
   | `OBS_MEDIA_ROOT` | `C:/TV` | `C:/TV`, o la ruta equivalente desde el PC de OBS |
   | `OBS_URL` | `ws://host.docker.internal:4455` | `ws://IP_DEL_PC_OBS:4455` |

   En ambos equipos debe verse la misma estructura de archivos bajo esas raíces. El montaje en Docker es de solo lectura. Si están en equipos distintos, permite el acceso al puerto WebSocket de OBS desde el servidor en la red privada.

4. Desde `desktop`, levanta el servicio:

   ```sh
   docker compose up -d --build
   ```

5. Abre <http://localhost:8000> en el host Docker. Para administrarlo desde otro equipo, mantén el puerto local y accede por un túnel SSH, o publícalo detrás de un proxy HTTPS. Ejemplo de túnel: `ssh -L 8000:127.0.0.1:8000 usuario@servidor`. La autenticación HTTP Basic requiere una conexión protegida para enviar credenciales fuera del host.
6. Elige el MP4 de continuidad, agrega programas y comerciales a la parrilla, y pulsa **Activar automatización**.

Usa `docker compose logs -f automata` para revisar eventos y errores. La parrilla y el video de continuidad seleccionado se guardan en el volumen `automata-data` y se conservan al recrear el contenedor. Tras reiniciar el servicio, la automatización se activa manualmente desde el panel. OBS controla el inicio y el fin de la transmisión.

### Actualizar el panel web

Para conservar la biblioteca y la parrilla, extrae el contenido de la carpeta `desktop` del ZIP encima de tu carpeta `desktop` actual y conserva tu archivo `.env`. En esa misma carpeta ejecuta `docker compose up -d --build`. Haz la actualización fuera de una emisión automática si necesitas que el servicio siga controlando OBS durante el cambio.

El panel muestra los MP4 de la carpeta montada con búsqueda y filtro por subcarpeta. Selecciona un archivo para previsualizarlo en el navegador. La previsualización depende del códec admitido por el navegador y funciona de forma independiente de OBS. La tarjeta de reproducción muestra el archivo que OBS confirmó para la automatización y la tarjeta siguiente muestra el próximo evento de la parrilla.

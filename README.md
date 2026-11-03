# Automata TV

Automata TV es un automatizador de televisión 24/7 que controla **OBS** desde una interfaz web: emite películas, series y comerciales en secuencia. Hecho en Python (FastAPI) y empaquetado con Docker, así que corre igual en Windows, Linux y macOS.

Los GCs los manejas tú directamente en OBS: este programa solo cambia el video de una fuente de medios.

## Cómo encaja Docker
OBS sigue corriendo en tu equipo (necesita pantalla y GPU). El contenedor solo corre el automatizador, que habla con OBS por WebSocket y lee tus videos en modo solo lectura.

```
 Tu equipo                                   Contenedor
┌────────────────────────┐   WebSocket    ┌──────────────────────┐
│ OBS  (fuente TV_PLAYER)│◄──────────────►│ Automata TV          │
│ videos en C:\TV        │  ruta del video│ videos en /media (ro)│
└────────────────────────┘                └──────────────────────┘
```
Como OBS abre los archivos en *su* equipo, el automatizador traduce la ruta del contenedor (`/media/...`) a la ruta que OBS ve (`C:\TV\...`). Por eso se configura `MEDIA_DIR` (para Docker) y, si hace falta, `OBS_MEDIA_ROOT` (para OBS).

## Requisitos
- Docker con Compose (Docker Desktop en Windows/macOS)
- OBS Studio 28 o superior (trae el servidor WebSocket incluido)

## 1. Preparar OBS (una sola vez)
1. Herramientas → Ajustes del servidor WebSocket → activar, puerto 4455 y una contraseña.
2. Crear una **Fuente de medios** llamada `TV_PLAYER` en la escena que sale al aire, con "Repetir" desmarcado.
3. Poner tus GCs sobre esa fuente y configurar la salida RTMP como siempre.

## 2. Organizar los videos
Una carpeta con tres subcarpetas. Para series, una carpeta por serie y dentro sus temporadas:

```
TV/
├── Peliculas/
│   └── Accion/
│       └── Pelicula Uno.mp4
├── Series/
│   └── Serie X/
│       ├── Temporada 1/
│       │   ├── 01 - Piloto.mp4
│       │   └── 02 - Segundo.mp4
│       └── Temporada 2/
└── Comerciales/
    ├── Spot A.mp4
    └── Spot B.mp4
```
Los episodios se ordenan en orden natural (`ep2` antes que `ep10`), pero conviene numerarlos igual. Los videos nunca se copian ni se modifican.

## 3. Levantar el automatizador
```bash
git clone <URL de tu repositorio>
cd <carpeta del repositorio>
cp .env.example .env        # en Windows: copy .env.example .env
# edita .env: MEDIA_DIR (ruta absoluta de tu carpeta TV) y OBS_PASSWORD
docker compose up -d --build
```
Abre http://localhost:8000, agrega videos a la parrilla desde la **Biblioteca** (puedes agregar una temporada completa con "Agregar carpeta") y presiona **Iniciar emisión**.

Ejemplos de `MEDIA_DIR`: `C:/TV` (Windows), `/home/yo/TV` (Linux), `/Users/yo/TV` (macOS).

### Si OBS está en otro equipo o contenedor
Define `OBS_HOST` (su IP) y `OBS_MEDIA_ROOT` con la misma carpeta de videos tal como la ve ese OBS, por ejemplo `OBS_MEDIA_ROOT=D:\Videos`. También se cambian desde **Ajustes**.

### Comandos útiles
```bash
docker compose logs -f tv       # ver el registro
docker compose restart tv       # reiniciar
docker compose down             # detener (la parrilla se conserva)
docker compose up -d --build    # actualizar tras un git pull
```
La parrilla y los ajustes se guardan en el volumen `tvdata`. Los valores de `.env` son los iniciales; lo que guardes en **Ajustes** tiene prioridad.

## Informe de diagnóstico
Si algo no funciona, abre **Informe** (arriba a la derecha) y copia el resultado. Es un texto sin contraseñas que reúne lo necesario para encontrar el problema:

- Estado de la conexión con OBS, su versión y su sistema operativo.
- Si existe la fuente `TV_PLAYER`, de qué tipo es, qué archivo tiene cargado y si está al aire (escena activa, modo estudio, ojito).
- Qué ve el programa en tu carpeta de videos y cómo traduce una ruta de ejemplo para OBS.
- Los ajustes, el estado de la emisión y las últimas líneas del registro.
- Un **resumen** al inicio con los problemas y avisos detectados.

Con la casilla **Incluir prueba de reproducción** carga un video en OBS y comprueba si realmente arranca. Interrumpe lo que esté al aire y no se ejecuta si la emisión está en marcha.

## Cómo funciona
- Cada video se carga en `TV_PLAYER` y al terminar pasa el siguiente (evento de OBS más un respaldo que consulta el estado cada segundo).
- Tras cada película o episodio entra una tanda de N comerciales, en rotación.
- Al terminar la parrilla vuelve a empezar (se puede desactivar).
- Si OBS se cierra, reintenta cada 5 s y retoma lo que estaba al aire.
- Si falta un archivo, lo salta. Si OBS no llega a reproducir tres videos seguidos (escena fuera del aire o ruta de OBS mal configurada), se detiene y lo dice en el registro, en vez de recorrer toda la parrilla.

## Solución de problemas
| Síntoma | Qué revisar |
|---|---|
| "Buscando OBS…" | Servidor WebSocket activo, puerto 4455, contraseña. En Windows, que el firewall permita OBS. |
| No reproduce nada | Genera el **Informe** (con la prueba de reproducción) y revisa el resumen. |
| "OBS no está reproduciendo…" | La escena con `TV_PLAYER` debe estar al aire, y **Carpeta de videos vista desde OBS** debe ser la ruta real en el equipo de OBS. |
| La biblioteca sale vacía | `MEDIA_DIR` debe ser ruta absoluta y tener `Peliculas/`, `Series/`, `Comerciales/` (o cambia los nombres en Ajustes). |
| Error de permisos en Linux | El usuario del contenedor (uid 10001) debe poder leer los videos: `chmod -R a+rX TV`. |

## Sin Docker
```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
MEDIA_DIR=~/TV DATA_DIR=./data uvicorn app.main:app --port 8000
```
Sin Docker, OBS ve las mismas rutas que el programa, así que no hace falta `OBS_MEDIA_ROOT`.

## Estructura
```
app/engine.py        Conexión a OBS, biblioteca, parrilla y reproducción
app/report.py        Informe de diagnóstico
app/main.py          API REST + WebSocket para la interfaz
app/static/          Interfaz web
tests/               OBS simulado y pruebas (python -m pytest)
CHANGELOG.md          Historial de cambios
Dockerfile, compose.yaml, .env.example
```

## Pruebas
```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
Levantan un OBS simulado y verifican el orden de emisión, las tandas, la traducción de rutas y el corte por falla. El CI de GitHub las corre en Windows, Linux y macOS, y además construye la imagen Docker.

## Seguridad
El puerto se publica solo en `127.0.0.1` y la interfaz no tiene login. No lo expongas a internet; si lo abres a tu red local, hazlo solo en una red de confianza. La contraseña de OBS se guarda en texto plano en el volumen de datos.

## Versiones y actualizaciones
La versión vive en `app/__init__.py` y se ve en la interfaz. Para publicar una nueva:

1. Sube `__version__` en `app/__init__.py` y el `ARG VERSION` del `Dockerfile` (debe ser el mismo número).
2. Agrega su sección `## [X.Y.Z] - fecha` al `CHANGELOG.md`.
3. `python -m pytest -q` (comprueba que versión, CHANGELOG y Docker coinciden).
4. Commit, etiqueta y subida:
   ```bash
   git add -A && git commit -m "Versión X.Y.Z"
   git tag -a vX.Y.Z -m "Versión X.Y.Z"
   git push origin main --tags
   ```
5. GitHub Actions crea el release con las notas del CHANGELOG (workflow `release.yml`).

Para actualizar tu instalación: `git pull && docker compose up -d --build`.

## Pendiente
Parrilla por horarios, tandas por hora o minutos, rellenos cuando no hay contenido.

## Licencia
GPL-3.0. Consulta el archivo `LICENSE`. Se aceptan aportes: abre un issue o un pull request.

# Cómo contribuir a Automata TV

¡Gracias por querer mejorar el proyecto! Automata TV es software libre (licencia GPL-3.0) y recibe aportes de la comunidad.

## Antes de empezar
- Revisa los [issues](../../issues) abiertos para no duplicar trabajo.
- Si el cambio es grande, abre primero un issue y cuéntanos la idea.

## Flujo de trabajo
1. Haz un fork y crea una rama desde `main`: `git checkout -b mi-mejora`
2. Haz tus cambios en commits pequeños y con mensajes claros.
3. Prueba que el servidor arranca y que la interfaz carga:
   ```
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   OBS_HOST=localhost MEDIA_DIR=./media uvicorn app.main:app --reload
   ```
4. Si el cambio afecta a quien usa la app, agrega una línea en `CHANGELOG.md`.
5. Abre un Pull Request describiendo qué cambia y cómo lo probaste con OBS.

## Criterios
- Código en Python 3.12, con nombres claros y sin dependencias nuevas si no son necesarias.
- La interfaz, en español y en minúsculas de oración.
- Nunca subas contraseñas, archivos `.env` ni videos.
- Los aportes se publican bajo la misma licencia GPL-3.0 del proyecto. Al enviar un Pull Request aceptas que tu aporte se distribuya bajo esa licencia.
- Los archivos `.py` nuevos llevan el mismo encabezado de licencia que los existentes.

## Versionado
Se usa versionado semántico (`MAYOR.MENOR.PARCHE`). El número vigente está en el archivo `VERSION`.

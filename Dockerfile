FROM python:3.12-slim

# Debe coincidir con app/__init__.py (lo comprueba tests/test_release.py)
ARG VERSION=0.10.1
LABEL org.opencontainers.image.title="Automata TV" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="GPL-3.0-only"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    MEDIA_DIR=/media

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Usuario sin privilegios; /data guarda la parrilla y los ajustes
RUN useradd --create-home --uid 10001 tv && mkdir -p /data /media && chown tv /data
USER tv
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

# Un solo proceso: el estado de la emisión vive en memoria
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY web/requirements.txt ./requirements-web.txt
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt
COPY playout.py web/panel.py web/index.html ./
RUN useradd --system --uid 10001 automata && mkdir /data && chown automata /data
USER automata
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "panel:app", "--host", "0.0.0.0", "--port", "8000"]

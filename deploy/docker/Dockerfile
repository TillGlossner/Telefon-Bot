# Container fuer den Telefonbot. Modelle liegen als Volume daneben,
# damit das Abbild klein bleibt und ohne Internetzugang startet.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg wird nur fuer Werkzeuge gebraucht, nicht im Gespraechspfad.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/telefonbot

COPY pyproject.toml README.md ./
COPY src ./src
# Extras nach Bedarf: .[asr,tts] fuer den vollen Betrieb, sonst nur der Kern.
ARG EXTRAS=".[asr,tts]"
RUN pip install --no-cache-dir "${EXTRAS}"

COPY config ./config
COPY scripts ./scripts

RUN useradd --system --create-home --uid 10001 telefonbot \
    && mkdir -p /opt/telefonbot/var /opt/telefonbot/models \
    && chown -R telefonbot:telefonbot /opt/telefonbot
USER telefonbot

EXPOSE 8090 8091
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8091/health',timeout=3)"

ENTRYPOINT ["telefonbot"]
CMD ["start", "-c", "config/config.yaml"]

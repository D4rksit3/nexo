FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEXO_DATA=/data

RUN useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin nexo \
 && mkdir -p /data && chown nexo:nexo /data && chmod 700 /data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY nexo_server ./nexo_server

USER nexo
VOLUME ["/data"]
EXPOSE 2222 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)" || exit 1

CMD ["python", "-m", "nexo_server"]

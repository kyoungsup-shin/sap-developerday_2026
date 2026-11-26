# Gateway image. The same image also runs the internal Team Agent server.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/demo/backend \
    ALLOW_WRITE_TOOLS=false

WORKDIR /app/demo/backend

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && addgroup --system app \
    && adduser --system --ingroup app app

COPY . /app/demo/backend
RUN mkdir -p /app/demo/backend/data/harness_state /app/demo/backend/data/evaluations \
    && chown -R app:app /app/demo/backend

USER app
EXPOSE 8080 8091

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/healthz', timeout=3)"

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8080"]

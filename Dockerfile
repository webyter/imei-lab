FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "exec python3 imei_server.py --host 0.0.0.0 --port ${PORT:-8000}"]

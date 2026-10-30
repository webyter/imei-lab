FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY . .

# The TAC csv is not committed: fetch and verify a copy into the image.
RUN python3 refresh_db.py

EXPOSE 8000

CMD ["sh", "-c", "exec python3 imei_server.py --host 0.0.0.0 --port ${PORT:-8000}"]

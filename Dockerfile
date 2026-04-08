# Dockerfile — single image that can run either the scanner loop or
# the FastAPI backend. The React dashboard has its own image (see
# dashboard/Dockerfile) built against nginx.

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/fareradar_v2.db

RUN mkdir -p /app/data

# Default: run the scanner loop. docker-compose overrides this for
# the API service.
CMD ["python", "src/scanner.py"]

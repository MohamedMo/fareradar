FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    httpx \
    aiohttp \
    aiosqlite \
    pydantic \
    python-telegram-bot \
    apscheduler

COPY src/ ./src/
COPY requirements.txt .

RUN mkdir -p /app/data

CMD ["python", "src/scanner.py"]

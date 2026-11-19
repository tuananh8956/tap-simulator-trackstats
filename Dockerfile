FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=3883 \
    TRACKSTATS_DB_PATH=/data/trackstats.db

WORKDIR /app

RUN mkdir -p /data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY tools ./tools
COPY run.py ./run.py

EXPOSE 3883

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-3883} --proxy-headers --forwarded-allow-ips=*"]

FROM python:3.12-slim

WORKDIR /app

# CA certificates (for HTTPS ICS feeds) and tzdata (for zoneinfo).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# config.yaml is intentionally NOT copied: it is machine-managed and holds
# private calendar URLs. The app bootstraps from config.demo.yaml on first run
# and writes config.yaml into the data volume below.
COPY . .

EXPOSE 8080

# Keep all mutable state (config.yaml, cache/) in one directory so a single
# volume mount preserves everything across image updates.
ENV FAMILY_CALENDAR_CONFIG=/app/data/config.yaml

CMD ["python", "run.py"]

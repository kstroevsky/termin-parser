FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STATE_PATH=/data/state.json

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

# Install the app, then the matching Chromium + its OS libraries.
RUN pip install . && playwright install --with-deps chromium

VOLUME ["/data"]

# Long-running loop: checks every INTERVAL_MINUTES inside the daily window.
CMD ["clinic-monitor", "loop"]

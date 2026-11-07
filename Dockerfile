# Saint Scernding in a container (used by Krasnodar on kraken; see compose.yaml and deploy/krasnodar.yaml).
# Python 3.11 to match the PC it ran on before.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SANTA_DATA_DIR=/data \
    SANTA_ASSETS_DIR=/data/assets \
    SANTA_LOG_STDOUT=1

# DejaVu fonts for the Santa letter (the PC used Windows fonts; without any, Pillow's plain default font is used)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-dejavu-extra \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 santa \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin santa \
    && mkdir /data && chown 10001:10001 /data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what the bot needs at runtime. No supervisor.py: Docker's restart policy does that job.
COPY bot.py healthcheck.py ./
COPY santa/ santa/

USER 10001:10001
CMD ["python", "bot.py"]

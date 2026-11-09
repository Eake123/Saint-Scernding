# Saint Scernding in a container (used by Krasnodar on kraken; see compose.yaml and deploy/krasnodar.yaml).
# Everything is pinned so a rebuild (including a rollback's) produces the same image:
# - base: Python 3.11.18 on Debian 13 (trixie), by digest. It's the exact base the bot ran on when this was pinned.
#   To bump: pick a newer supported tag, then `docker buildx imagetools inspect python:<tag>` for its digest.
# - Python packages: requirements.lock (exact versions + hashes); apt packages: exact versions below.
FROM python:3.11.18-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SANTA_DATA_DIR=/data \
    SANTA_ASSETS_DIR=/data/assets \
    SANTA_LOG_STDOUT=1

# DejaVu fonts for the Santa letter (the PC used Windows fonts; without any, Pillow's plain default font is used)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core=2.37-8 fonts-dejavu-extra=2.37-8 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 santa \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin santa \
    && mkdir /data && chown 10001:10001 /data

WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock

# Only what the bot needs at runtime. No supervisor.py: Docker's restart policy does that job.
COPY bot.py healthcheck.py ./
COPY santa/ santa/

USER 10001:10001
CMD ["python", "bot.py"]

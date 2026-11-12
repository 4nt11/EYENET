# EYENET base runtime image — every core service runs from this one image with a
# per-service command override (see deploy/docker/compose.yaml). Build context is
# the repo root: `docker build -f deploy/docker/Dockerfile -t eyenet:base .`
#
# Python 3.12 — requires-python is >=3.12 and the dev venv is 3.12; keeping the
# image on 3.12 also keeps the classifier extract-venv ABI-matched.
#
# Multi-stage: the builder has a C toolchain (tgcrypto and friends are C
# extensions with no wheel for this platform); the runtime ships only the built
# venv, so the final image has no compilers.

# ---- builder: compile deps into a self-contained venv ----------------------
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential python3-dev \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app
# DEPS LAYER: install dependencies + the spaCy model from pyproject ALONE, so a source
# edit does not reinstall the world (the slow part: telethon/spacy wheels + the ~13MB
# model). A stub eyenet/ package satisfies hatchling (packages=["eyenet"]) enough to build
# the wheel; the real source replaces it below. Cached until pyproject changes.
COPY pyproject.toml README.md ./
RUN mkdir -p eyenet && : > eyenet/__init__.py && pip install . && rm -rf eyenet
# Pre-bake the Spanish spaCy model so the sensor's first run needs no network. In the deps
# layer so it is cached across source edits (depends only on spacy, installed above).
RUN python -m spacy download es_core_news_sm

# SOURCE LAYER: the real package, deps already present. --no-deps + --force-reinstall
# rebuilds just eyenet from source in seconds (no downloads, no dependency resolution).
COPY eyenet/ ./eyenet/
RUN pip install --no-deps --force-reinstall .

# ---- runtime: slim, no compilers -------------------------------------------
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    EYENET_DATA_DIR=/var/lib/eyenet

# libmagic1: python-magic byte-sniffing (classifier). libolm3: matrix-nio[e2e]
# runtime bindings (the matrix collector imports python-olm on load).
# ca-certificates: outbound TLS. libglib2.0-0: PyQt5.QtCore needs libgthread/glib,
# and opentele parses a bought-account tdata via Qt's QDataStream on the tdata
# import path (eyenet.identity_pool._tdata). QtCore only, so no GUI/X11 libs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 libolm3 ca-certificates libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -r -u 10001 -m -d /home/eyenet -s /usr/sbin/nologin eyenet

# The whole app + deps + spaCy model ride in the venv.
COPY --from=builder /opt/venv /opt/venv

# Data volume mount point, owned by the service account BEFORE it becomes a named
# volume so the first `compose up` inherits eyenet ownership (not root).
RUN install -d -o eyenet -g eyenet /var/lib/eyenet

# Neutral runtime cwd (no ./eyenet source to shadow the installed package).
WORKDIR /home/eyenet
USER eyenet
# Version baked as a standard OCI label. deploy/docker/deploy.sh reads it off the running
# container as the source of truth for "what is running". `dev` for a plain hand build.
ARG EYENET_VERSION=dev
LABEL org.opencontainers.image.version=$EYENET_VERSION
ENTRYPOINT ["eyenet"]
CMD ["version"]

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
# Only what hatchling needs to build the wheel; readme = PLAN.md (pyproject).
COPY pyproject.toml PLAN.md ./
COPY eyenet/ ./eyenet/
RUN pip install .
# Pre-bake the Spanish spaCy model so the sensor's first run needs no network.
RUN python -m spacy download es_core_news_sm

# ---- runtime: slim, no compilers -------------------------------------------
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    EYENET_DATA_DIR=/var/lib/eyenet

# libmagic1: python-magic byte-sniffing (classifier). libolm3: matrix-nio[e2e]
# runtime bindings (the matrix collector imports python-olm on load).
# ca-certificates: outbound TLS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 libolm3 ca-certificates \
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
ENTRYPOINT ["eyenet"]
CMD ["version"]

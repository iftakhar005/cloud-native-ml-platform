# syntax=docker/dockerfile:1
#
# Build:   docker build -t thikana-api --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
# Run:     docker run --rm -p 8000:8000 thikana-api
# See docs/docker.md.

# Pinned by DIGEST, not just by tag: a tag can be re-pointed underneath you, a digest
# cannot. Updating the base image is therefore a visible commit, not a silent change.
# (python:3.12-slim = Python 3.12.15 on Debian 13 at the time of pinning.)
ARG PYTHON_IMAGE=python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704


# ---- stage 1: install the pinned packages into a virtualenv --------------------------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

# Only the requirements file is copied first. Docker caches each layer, and this layer
# is rebuilt only when serve.txt changes - NOT every time the code changes. That is the
# difference between a 3-second rebuild and a 60-second one.
COPY requirements/serve.txt .

# --only-binary=:all: fails the build if any package would need compiling. This stage
# has no compiler, so a source-only dependency should be loud, not a silent slowdown.
# The venv is created WITHOUT pip and filled by the builder's pip (--python): a second
# copy of pip inside the venv is 13 MB that nothing at runtime needs.
# (Honest limit: the BASE image still ships its own system pip, apt and a shell. The
# real protection is that the process is unprivileged, the code is root-owned and
# read-only, and it runs with no capabilities: verified in docs/docker.md.)
RUN python -m venv --without-pip /opt/venv \
 && pip --python /opt/venv/bin/python install --only-binary=:all: --no-compile -r serve.txt


# ---- stage 2: the image that actually ships -------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG GIT_SHA=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    THIKANA_MODEL_PATH=/app/models/crf_all_district_memory_vocab.crfsuite \
    THIKANA_GIT_SHA=${GIT_SHA}

# A fixed, unprivileged identity with no home directory and no login shell.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

# Only the finished virtualenv comes across: no pip cache, no build tools, no requirements.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# The code and the model stay owned by ROOT and are not writable. The process runs as
# 'app' (below), so even a compromised process cannot modify the code it is running.
# The model is baked in: model version == image tag == git commit, and rolling back
# the model is just running the previous image.
#
# a=rX : read for everyone; execute ONLY on directories. A plain --chmod=0644 applies to
# directories too, and a directory without the execute bit cannot be entered by anyone
# but root: the app user then cannot see its own code ("No module named 'thikana.api'").
# Found by running the first build as the non-root user.
#
# ORDER = least to most frequently changing. Docker rebuilds a layer whenever anything
# BEFORE it changed, so the model (retrained rarely) comes first, the core modules next,
# and the API code (edited constantly) last: a code edit then rebuilds one small layer.
COPY --chmod=a=rX models/crf_all_district_memory_vocab.crfsuite models/crf_all_district_memory_vocab.json models/
COPY --chmod=a=rX thikana/__init__.py thikana/schema.py thikana/text.py thikana/features.py thikana/model.py thikana/
COPY --chmod=a=rX thikana/api/ thikana/api/
# The web page (four static files). Served by the API process itself, so there is no second
# container or host, and no CORS.
COPY --chmod=a=rX thikana/web/ thikana/web/

USER 10001:10001
EXPOSE 8000

LABEL org.opencontainers.image.title="thikana-api" \
      org.opencontainers.image.description="Bangladeshi address parser (prototype)" \
      org.opencontainers.image.revision="${GIT_SHA}"

# For `docker run` and Compose. Kubernetes ignores HEALTHCHECK and uses its own probes.
# /readyz, not /healthz: "container is healthy" here means "able to answer", which needs
# the model. Python's own urllib, because the slim image has no curl to install.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2).status == 200 else 1)"]

# One process. To handle more traffic you run more containers (replicas), not more
# workers: that is what Kubernetes and a load balancer are for.
# --no-access-log: the app writes ONE structured JSON line per request (id, route, status,
#   latency, counts). uvicorn's own plain-text access line would duplicate it.
# --no-server-header: do not announce which server software this is.
# --no-proxy-headers: uvicorn otherwise TRUSTS X-Forwarded-For from any peer on 127.0.0.1 and
#   rewrites the client address before the app sees it. That is a second, hidden mechanism next to
#   the app's own rate limiter (THIKANA_TRUSTED_PROXY_HOPS), and it let a forged header buy a new
#   allowance (found by scripts/check_public.py). With it off, exactly one mechanism decides.
# Exec form (a JSON array), so uvicorn is PID 1 and receives SIGTERM directly: that is
# what makes `docker stop` and Kubernetes rolling updates shut down gracefully.
CMD ["uvicorn", "thikana.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--no-access-log", "--no-proxy-headers"]

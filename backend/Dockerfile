FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# uv comprend [tool.uv.sources] (dépendance locale harpocrate) — pip ne le comprend pas
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY vendor ./vendor
COPY src ./src
RUN uv pip install --system --no-cache ./vendor/*.whl \
    && sed -i '/^\[tool\.uv\.sources\]/d; /^harpocrate = { path/d' pyproject.toml \
    && uv pip install --system --no-cache .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src /app/src
COPY migrations /app/migrations
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "agflow.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ──────────────────────────────────────────────────────────────────────────────
# Stage `dev` : image runtime + pytest + tests pour les tests d'intégration
# lancés depuis le LXC (cf. scripts/test-create-lxc.sh, docs/test.md).
# - Hérite de `runtime` : même Python, même site-packages (agflow + sdk),
#   même PYTHONPATH, même CMD (uvicorn) → comportement uvicorn identique
# - Ajoute uv + pytest + pytest-asyncio dans le site-packages global
# - Copie pyproject.toml (pour les options pytest : pythonpath, asyncio_mode…)
# - Copie tests/ dans /app/tests
#
# Build par défaut (dev-deploy.sh) : `docker build .` → cible `dev`.
# Build prod (scripts/deploy.sh) : `docker build --target runtime .` → lean.
# ──────────────────────────────────────────────────────────────────────────────
FROM runtime AS dev
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache pytest pytest-asyncio
COPY pyproject.toml /app/pyproject.toml
COPY tests /app/tests

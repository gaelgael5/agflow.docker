# agflow.docker Phase 0 — Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the `agflow.docker` monorepo with a working FastAPI backend + Vite/React frontend skeleton, DB migration infrastructure, simple admin auth (JWT), and deployable docker-compose stacks — all verified via tests and a smoke-test on LXC 201 (192.168.10.82).

**Architecture:** Monorepo (`backend/` FastAPI+asyncpg+structlog, `frontend/` Vite+React+TS strict+i18n) with PostgreSQL 16 (pgcrypto) and Redis 7 as shared infra. Backend reads raw SQL migrations from `backend/migrations/`. Frontend is a SPA served by nginx in prod. Simple bearer-token JWT auth for admin panel.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, pydantic-settings, structlog, PyJWT, bcrypt, pytest+pytest-asyncio, httpx (TestClient), ruff ; Node 20+, React 18, Vite 5, TypeScript strict, react-router-dom v6, @tanstack/react-query, axios, tailwindcss, i18next+react-i18next, Vitest, React Testing Library ; PostgreSQL 16, Redis 7, Caddy, Docker, docker compose.

---

## Context

`agflow.docker` is a **new** platform for instantiating AI CLI agents (claude-code, aider, codex, gemini, goose, mistral, open-code) packaged as Docker images. The full product spec is in `specs/home.md` (541 lines, 7 admin modules M0–M6). This plan covers **only Phase 0 — bootstrap**. Subsequent phases (M0 Secrets, M2 Roles, M1 Dockerfiles, …, Vertical E2E, CI/CD) will each get their own dedicated plan written **after** Phase 0 lands and is validated.

### Validated decisions (from prior brainstorming)

| Item | Choice |
|---|---|
| Repo layout | Monorepo : `backend/` + `frontend/` |
| Backend | FastAPI + asyncpg (no SQLAlchemy), structlog JSON |
| Frontend | Vite + React 18 + TypeScript strict (SPA, no SSR) |
| DB | PostgreSQL 16 + pgcrypto extension |
| MOM (later phase) | Redis Streams |
| Docker runtime | aiodocker (when needed from Phase 3+) |
| Admin auth | Simple JWT, seed admin via env |
| Dev env | Local Windows for code/tests, LXC 201 for integration |
| MVP slice | Vertical e2e on 1 agent (claude-code) — future phases |
| MCP registry | `mcp.yoops.org` (already in production) |

### Plan decomposition (scope)

Per the **scope check** rule of the `superpowers:writing-plans` skill, the full agflow.docker scope is too large for a single plan. It is split as follows:

- **This plan** → Phase 0 — Bootstrap
- Phase 1 plan → Module 0 (Secrets) — *to be written*
- Phase 2 plan → Module 2 (Roles) — *to be written*
- Phase 3 plan → Module 1 (Dockerfiles) — *to be written*
- Phase 4 plan → Module 3 (Catalogs MCP+Skills) — *to be written*
- Phase 5 plan → Module 4 (Composition + UX mockups) — *to be written*
- Phase 6 plan → Module 5 (Public API + MOM) — *to be written*
- Phase 7 plan → Module 6 (Supervision) — *to be written*
- Phase 8 plan → Vertical E2E on claude-code — *to be written*
- Phase 9 plan → Deploy LXC 201 + CI — *to be written*

Each future plan will reuse the structure below and will be committed under `docs/superpowers/plans/` once produced.

### Plan file location caveat

Claude Code plan mode stores plan files at `~/.claude/plans/<slug>.md` by default. Per user preference, **this plan should live in the repo** once approved — the agreed location is `docs/superpowers/plans/2026-04-10-phase0-bootstrap.md`. Current file (`C:\Users\g.beard\.claude\plans\dapper-crafting-narwhal.md`) is temporary and will be moved as the very first action after exiting plan mode.

---

## File Structure

### Files created in Phase 0

**Monorepo root:**
- `.env.example` — template env vars (no secrets)
- `docker-compose.yml` — dev local : postgres + redis only (backend/frontend run on host)
- `docker-compose.prod.yml` — prod LXC 201 : postgres + redis + backend + frontend + caddy
- `scripts/deploy.sh` — SCP + SSH deploy to LXC 201
- `CLAUDE.md` — **rewritten** for agflow.docker (replaces LandGraph version)
- `LESSONS.md` — emptied (keep header only)

**Backend (`backend/`):**
- `pyproject.toml` — python 3.12, deps, pytest config, ruff config
- `src/agflow/__init__.py`
- `src/agflow/main.py` — FastAPI app factory + lifespan (db pool, redis)
- `src/agflow/config.py` — Pydantic Settings (reads `.env`)
- `src/agflow/logging_setup.py` — structlog JSON configurator
- `src/agflow/db/__init__.py`
- `src/agflow/db/pool.py` — `get_pool()`, `fetch_one`, `fetch_all`, `execute`
- `src/agflow/db/migrations.py` — `run_migrations()` — reads `migrations/*.sql` ordered and applies in transaction
- `src/agflow/auth/__init__.py`
- `src/agflow/auth/jwt.py` — `encode_token(sub) -> str`, `decode_token(token) -> dict`
- `src/agflow/auth/dependencies.py` — `require_admin()` FastAPI dep
- `src/agflow/api/__init__.py`
- `src/agflow/api/health.py` — `GET /health`
- `src/agflow/api/admin/__init__.py`
- `src/agflow/api/admin/auth.py` — `POST /api/admin/auth/login`, `GET /api/admin/auth/me`
- `src/agflow/schemas/__init__.py`
- `src/agflow/schemas/auth.py` — `LoginRequest`, `LoginResponse`, `Me`
- `migrations/001_init.sql` — extensions + `schema_migrations` table
- `Dockerfile` — prod backend image (python:3.12-slim + uvicorn)
- `.dockerignore`
- `tests/__init__.py`
- `tests/conftest.py` — `client` fixture, `admin_token` fixture
- `tests/test_health.py`
- `tests/test_config.py`
- `tests/test_db_pool.py`
- `tests/test_migrations.py`
- `tests/test_auth_jwt.py`
- `tests/test_auth_endpoint.py`

**Frontend (`frontend/`):**
- `package.json`
- `vite.config.ts` — dev proxy `/api` → `http://localhost:8000`
- `tsconfig.json` — `strict: true`, `noUncheckedIndexedAccess: true`
- `tsconfig.node.json`
- `index.html`
- `.eslintrc.cjs`
- `.prettierrc`
- `src/main.tsx` — React root
- `src/App.tsx` — Router + QueryClientProvider + i18n
- `src/vite-env.d.ts`
- `src/lib/api.ts` — axios instance with Bearer interceptor
- `src/lib/i18n.ts` — i18next init
- `src/i18n/fr.json`
- `src/i18n/en.json`
- `src/pages/LoginPage.tsx`
- `src/pages/HomePage.tsx` — placeholder dashboard
- `src/components/ProtectedRoute.tsx`
- `src/components/StatusIndicator.tsx` — 🔴🟠🟢 component
- `src/hooks/useAuth.ts`
- `Dockerfile` — multi-stage node build → nginx static
- `nginx.conf` — SPA fallback
- `.dockerignore`
- `vitest.config.ts`
- `tests/setup.ts`
- `tests/components/StatusIndicator.test.tsx`
- `tests/pages/LoginPage.test.tsx`
- `tests/hooks/useAuth.test.tsx`

### Files deleted in Phase 0

- `docs/Admin/` (LandGraph admin specs)
- `docs/Hitl/` (LandGraph HITL specs)
- `docs/superpowers/` (LandGraph plans)
- `docs/architecture.md`, `docs/agents.md`, `docs/gateway-api.md`, `docs/channels.md`
- `docs/llm-providers.md`, `docs/mcp.md`, `docs/env-vars.md`, `docs/hitl.md`
- `docs/changelog.md`, `docs/project-lifecycle.md`
- `docs/workflow-model.md`, `docs/workflow-specs.md`
- `scripts/infra/03-setup-cron.sh` (mcp-manager leftover)

### Files kept as-is (project-agnostic)

- `docs/patterns/*.md` — 19 design patterns docs
- `docs/python-dev-rules.md` — Python SOLID rules
- `docs/tests-python.md` — test coverage conventions
- `docs/sonarQube.md` — quality gate setup
- `scripts/infra/00-create-lxc.sh`, `01-install-docker.sh`, `02-prepare-existing-lxc4Docker.sh`
- `.gitignore`, `LICENSE`, `README.md`
- `specs/home.md`

---

## Tasks

### Task 1: Clean up LandGraph docs and create monorepo layout

**Files:**
- Delete: see "Files deleted" list above
- Create: `backend/`, `frontend/`, `specs/plans/`, `docs/superpowers/plans/` directory trees

- [ ] **Step 1: Check current working tree**

Run: `cd /e/srcs/agflow.docker && git status --short`
Expected: Shows any uncommitted deletions from prior session. Record what's pending.

- [ ] **Step 2: Restore accidentally-deleted docs/patterns/**

Run:
```bash
git restore docs/patterns/
ls docs/patterns/ | wc -l
```
Expected: 19 files present.

- [ ] **Step 3: Delete LandGraph-specific docs**

Run:
```bash
git rm -rf docs/Admin docs/Hitl docs/superpowers 2>/dev/null || rm -rf docs/Admin docs/Hitl docs/superpowers
git rm -f docs/architecture.md docs/agents.md docs/gateway-api.md docs/channels.md \
  docs/llm-providers.md docs/mcp.md docs/env-vars.md docs/hitl.md \
  docs/changelog.md docs/project-lifecycle.md docs/workflow-model.md docs/workflow-specs.md \
  scripts/infra/03-setup-cron.sh 2>/dev/null || true
```

- [ ] **Step 4: Create monorepo directory tree**

Run:
```bash
mkdir -p backend/src/agflow/api/admin \
         backend/src/agflow/auth \
         backend/src/agflow/db \
         backend/src/agflow/schemas \
         backend/migrations \
         backend/tests \
         frontend/src/pages \
         frontend/src/components \
         frontend/src/hooks \
         frontend/src/lib \
         frontend/src/i18n \
         frontend/tests/pages \
         frontend/tests/components \
         frontend/tests/hooks \
         specs/plans \
         docs/superpowers/plans
```

- [ ] **Step 5: Empty LESSONS.md (keep header only)**

Edit `LESSONS.md` — overwrite with:
```markdown
# LESSONS — agflow.docker

Lessons learned from corrections and successful patterns during development.
Format: `- [module] short description of the lesson`
Keep under 50 lines. Consolidate similar lessons.
```

- [ ] **Step 6: Commit cleanup + layout**

Run:
```bash
git add -A
git status
git commit -m "chore(phase0): cleanup landgraph docs and create monorepo layout"
```
Expected: Commit created with deletions + new empty dirs + LESSONS.md reset.

---

### Task 2: Rewrite CLAUDE.md for agflow.docker

**Files:**
- Modify: `CLAUDE.md` (complete rewrite)

- [ ] **Step 1: Read the current (LandGraph) CLAUDE.md to understand structure**

Run: `wc -l CLAUDE.md && head -20 CLAUDE.md`
Expected: ~220 lines, header "LandGraph — Instructions Claude Code".

- [ ] **Step 2: Replace content with agflow.docker version**

Overwrite `CLAUDE.md` with the following content:

```markdown
# agflow.docker — Instructions Claude Code

## Projet

Plateforme d'instanciation d'agents IA packagés en Docker (claude-code, aider, codex, gemini, goose, mistral, open-code). Panneau d'administration en 7 modules (M0 Secrets, M1 Dockerfiles, M2 Rôles, M3 Catalogues MCP+Skills, M4 Composition, M5 API publique, M6 Supervision). Spec complète : `specs/home.md`.

**Standard de qualité** : code propre et bien fait, jamais la rapidité au détriment de la rigueur. Pas de raccourcis, pas de "c'est pas grave", pas de "on simplifiera plus tard".

## Stack technique

- **Backend** : Python 3.12 + FastAPI + asyncpg (**pas SQLAlchemy**) + structlog JSON + pytest
- **Frontend** : Vite + React 18 + TypeScript strict + react-router-dom + TanStack Query + Tailwind + shadcn/ui + i18next + Vitest
- **BDD** : PostgreSQL 16 + pgcrypto (secrets) — source de vérité unique
- **MOM** : Redis Streams (`redis.asyncio`) avec consumer groups — bus central de toutes les comms agents
- **Docker runtime** : aiodocker (pas de subprocess)
- **Reverse proxy prod** : Caddy (SSL géré par Cloudflare Tunnel en front)
- **Registre externe MCP** : `https://mcp.yoops.org/api/v1`

## Commandes essentielles

```bash
# Dev local (Windows)
docker compose up -d                              # Infra dépendances (postgres + redis)
cd backend && uv run uvicorn agflow.main:app --reload   # Backend :8000
cd frontend && npm run dev                        # Frontend :5173

# Tests
cd backend && uv run pytest -v                    # Tests Python
cd frontend && npm test                           # Tests Vitest
cd frontend && npx tsc --noEmit                   # TS strict check

# Lint/format
cd backend && uv run ruff check src/ tests/       # Lint Python
cd backend && uv run ruff format src/ tests/      # Format Python
cd frontend && npm run lint                       # ESLint
cd frontend && npm run format                     # Prettier

# Migrations DB
cd backend && uv run python -m agflow.db.migrations    # Applique migrations en attente

# Déploiement LXC 201
./scripts/deploy.sh                               # Build images + SSH + compose up -d
```

## Layout du code

```
agflow.docker/
├── backend/
│   ├── src/agflow/
│   │   ├── main.py              # FastAPI app + lifespan
│   │   ├── config.py            # Pydantic Settings
│   │   ├── logging_setup.py     # structlog JSON
│   │   ├── api/                 # Routers FastAPI
│   │   │   ├── health.py
│   │   │   ├── admin/           # Endpoints /api/admin/*
│   │   │   └── public/          # Endpoints /api/v1/*   (phases futures)
│   │   ├── auth/                # JWT + dépendances FastAPI
│   │   ├── db/                  # asyncpg pool + migrations runner
│   │   ├── docker/              # aiodocker wrappers           (phases futures)
│   │   ├── mom/                 # Redis Streams producer/consumer (phases futures)
│   │   ├── services/            # Logique métier                (phases futures)
│   │   └── schemas/             # DTOs Pydantic
│   ├── migrations/              # SQL bruts numérotés (001_*.sql, 002_*.sql…)
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/               # 1 page par module admin
│       ├── components/          # Composants réutilisables
│       ├── hooks/
│       ├── lib/                 # api client, i18n
│       └── i18n/                # fr.json, en.json
├── docs/                        # Documentation projet
│   ├── patterns/                # Design patterns (ref transversale)
│   ├── python-dev-rules.md      # Règles Python SOLID
│   ├── tests-python.md          # Couverture tests
│   └── sonarQube.md             # Qualité code
├── specs/
│   ├── home.md                  # Spec produit complète
│   └── plans/                   # Plans de dev (copies des plans exécutés)
├── scripts/
│   ├── infra/                   # LXC Proxmox setup
│   └── deploy.sh                # Déploiement LXC 201
├── docker-compose.yml           # Dev local : postgres + redis
└── docker-compose.prod.yml      # Prod LXC 201 : stack complète
```

## Conventions de code

### Python (backend)
- Python 3.12+, async/await partout
- **Pas de SQLAlchemy** — asyncpg direct avec helpers `fetch_one` / `fetch_all` / `execute`
- Pydantic v2 pour les DTOs, Pydantic Settings pour la config
- Logs structurés via `structlog.get_logger(__name__)` — **jamais** `print()`
- `type` hints partout, `from __future__ import annotations` en tête de fichier
- Fichiers max 300 lignes ; classes SRP ; méthodes 5-15 lignes
- Règles détaillées : `@docs/python-dev-rules.md`
- Règles tests : `@docs/tests-python.md`

### TypeScript (frontend)
- `strict: true`, `noUncheckedIndexedAccess: true`
- Composants fonctionnels + hooks, pas de classes
- React Query pour tout appel API, pas de `useEffect + fetch` direct
- i18n sur **tous** les labels affichés — `useTranslation()`, jamais de string brute
- Fichiers max 300 lignes
- Props typées via `interface`, exports nommés

### Base de données
- Migrations = fichiers SQL numérotés dans `backend/migrations/` (ex: `001_init.sql`, `002_secrets.sql`)
- Schéma géré en SQL brut, pas d'ORM
- Extensions requises : `pgcrypto` (secrets), `uuid-ossp` (ids)
- Toute nouvelle table → migration SQL + test de migration

### Tests
- Backend : pytest + pytest-asyncio ; fixture `client` (TestClient httpx)
- Frontend : Vitest + React Testing Library ; `describe`/`it`, pas de `test`
- Couverture minimale par zone : voir `docs/tests-python.md`

## Règles de workflow

### Cycle de l'architecte
**Cadrer → Comprendre → Planifier → Agir.** L'utilisateur est architecte. Une question n'est pas une commande d'exécution. Une discussion n'est pas un feu vert. Ne JAMAIS sauter d'étape.

### Livraison
- Ne livre **jamais** le code ni en test ni sur git sans demande explicite
- Ne modifie pas `.env` sauf si demandé
- Commit messages en français, format conventionnel (`feat:`, `fix:`, `chore:`…)

### Vérification avant validation
Avant de déclarer une tâche terminée, **toutes** ces étapes sont obligatoires :
1. Le code s'exécute sans erreur (lint + build)
2. Le cas nominal fonctionne (test unitaire ou manuel)
3. Les imports ajoutés existent réellement
4. Pas de régression sur les fichiers modifiés
5. Si modification frontend : la page charge sans erreur console

### Discipline d'exécution
- Exécute directement, ne décris pas ce que tu vas faire — fais-le
- N'explique pas les étapes intermédiaires. Rapporte uniquement le résultat final
- Termine TOUTES les étapes d'un plan avant de faire un résumé
- Pas de raccourci "pour simplifier"

## Outils Claude Code

### Context7 — documentation live
**Quand** : avant d'écrire du code qui utilise FastAPI, Pydantic v2, asyncpg, aiodocker, redis-py, React Query, Vite, React Router, i18next, Tailwind, etc. Les API évoluent, ne te fie pas à ta mémoire.

### Serena — navigation sémantique
**Quand** : avant un refactor, pour comprendre les dépendances entre modules, ou pour trouver tous les usages d'une fonction/classe.

### Superpowers skills
- `writing-plans` : rédiger un plan d'implémentation TDD avant de coder
- `executing-plans` / `subagent-driven-development` : exécuter un plan tâche par tâche
- `systematic-debugging` : méthode pour debug un bug ou test qui échoue
- `test-driven-development` : TDD discipline

### /review
**Quand** : avant de présenter un changement multi-fichiers (>3 fichiers ou >100 lignes).

### /commit
**Quand** : quand l'utilisateur demande explicitement de committer.

## Auto-amélioration

Quand tu fais une erreur ou que l'utilisateur te corrige :
- Ajoute une leçon dans `LESSONS.md`
- Format : `- [module] description courte de l'erreur et de la bonne pratique`
- Relis `@LESSONS.md` en début de tâche qui touche un module mentionné
- Ne dépasse pas 50 lignes — consolide les leçons similaires

## Notifications de skills

Quand tu invoques une skill via l'outil Skill, affiche systématiquement un marqueur visuel **avant** d'exécuter :

> **`🟢 SKILL`** → _nom-de-la-skill_ — raison en une phrase
```

- [ ] **Step 3: Verify CLAUDE.md is valid Markdown**

Run: `head -5 CLAUDE.md && tail -5 CLAUDE.md && wc -l CLAUDE.md`
Expected: Header is "# agflow.docker — Instructions Claude Code", file is ~180 lines.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(phase0): rewrite CLAUDE.md for agflow.docker"
```

---

### Task 3: Backend `pyproject.toml` + dev environment setup

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.python-version`

- [ ] **Step 1: Write `backend/pyproject.toml`**

Create `backend/pyproject.toml` with:

```toml
[project]
name = "agflow-backend"
version = "0.1.0"
description = "agflow.docker backend — FastAPI + asyncpg platform for instantiating AI CLI agents"
readme = "../README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "asyncpg>=0.30",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "structlog>=24.4",
    "httpx>=0.28",
    "python-multipart>=0.0.12",
    "pyjwt[crypto]>=2.9",
    "bcrypt>=4.2",
    "aiodocker>=0.24",
    "redis[hiredis]>=5.1",
    "anthropic>=0.40",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "ruff>=0.7",
    "mypy>=1.13",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]
ignore = ["E501"]  # line length handled by formatter

[tool.ruff.format]
quote-style = "double"

[tool.coverage.run]
source = ["src/agflow"]
omit = ["tests/*"]
```

- [ ] **Step 2: Create `.python-version`**

Create `backend/.python-version`:
```
3.12
```

- [ ] **Step 3: Verify installable**

Run: `cd backend && uv sync 2>&1 | tail -20`
Expected: dependencies resolved and installed, no errors. (If `uv` isn't installed, fall back to `python -m venv .venv && .venv/bin/pip install -e .[dev]`.)

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/.python-version
git commit -m "feat(phase0): backend pyproject.toml with deps"
```

---

### Task 4: Backend config & logging setup (TDD)

**Files:**
- Create: `backend/src/agflow/config.py`
- Create: `backend/src/agflow/logging_setup.py`
- Create: `backend/tests/test_config.py`

- [ ] **Step 1: Write failing test for config**

Create `backend/tests/test_config.py`:

```python
from __future__ import annotations

import os

import pytest

from agflow.config import Settings


def test_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.org")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "$2b$12$fakehash")

    settings = Settings()

    assert settings.database_url == "postgresql://u:p@localhost:5432/test"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.jwt_secret == "test-secret-key"
    assert settings.admin_email == "admin@example.org"


def test_settings_default_environment() -> None:
    os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/test")
    os.environ.setdefault("JWT_SECRET", "x")
    os.environ.setdefault("ADMIN_EMAIL", "a@b.c")
    os.environ.setdefault("ADMIN_PASSWORD_HASH", "x")

    settings = Settings()

    assert settings.environment == "dev"
    assert settings.log_level == "INFO"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'agflow.config'`.

- [ ] **Step 3: Implement `config.py`**

Create `backend/src/agflow/config.py`:

```python
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required
    database_url: str
    jwt_secret: str
    admin_email: str
    admin_password_hash: str

    # Optional with defaults
    redis_url: str = "redis://localhost:6379/0"
    environment: str = "dev"
    log_level: str = "INFO"
    jwt_expire_hours: int = 24


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 5: Implement `logging_setup.py`**

Create `backend/src/agflow/logging_setup.py`:

```python
from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog to emit JSON logs to stdout."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level.upper(),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/agflow/config.py backend/src/agflow/logging_setup.py backend/tests/test_config.py
git commit -m "feat(phase0): backend config + structlog setup with tests"
```

---

### Task 5: Health endpoint + FastAPI app factory (TDD)

**Files:**
- Create: `backend/src/agflow/api/health.py`
- Create: `backend/src/agflow/main.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/conftest.py`:

```python
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Seed required env vars before importing app
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.local")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "$2b$12$placeholderhash")

from agflow.main import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)
```

Create `backend/tests/test_health.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: `ModuleNotFoundError: No module named 'agflow.main'`.

- [ ] **Step 3: Implement `api/health.py`**

Create `backend/src/agflow/api/health.py`:

```python
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Implement `main.py` (app factory)**

Create `backend/src/agflow/main.py`:

```python
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI

from agflow.api.health import router as health_router
from agflow.config import get_settings
from agflow.logging_setup import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)
    log.info("app.startup", environment=settings.environment)
    yield
    log.info("app.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="agflow.docker",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health_router)
    return app


app = create_app()
```

- [ ] **Step 5: Run test to confirm it passes**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: 1 passed.

- [ ] **Step 6: Smoke test via uvicorn**

Run (in a separate terminal):
```bash
cd backend && uv run uvicorn agflow.main:app --port 8000 &
sleep 2
curl -s http://localhost:8000/health
kill %1
```
Expected: `{"status":"ok"}` printed.

- [ ] **Step 7: Commit**

```bash
git add backend/src/agflow/api/health.py backend/src/agflow/api/__init__.py \
        backend/src/agflow/main.py \
        backend/tests/conftest.py backend/tests/test_health.py
git commit -m "feat(phase0): FastAPI app factory + /health endpoint"
```

---

### Task 6: asyncpg pool + helpers (TDD with real Postgres)

**Files:**
- Create: `backend/src/agflow/db/pool.py`
- Create: `backend/tests/test_db_pool.py`
- Create: `docker-compose.yml` (minimal, for the test to work)

- [ ] **Step 1: Create `docker-compose.yml` for dev/test infra**

Create `docker-compose.yml` at repo root:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: agflow-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: agflow
      POSTGRES_PASSWORD: agflow_dev
      POSTGRES_DB: agflow
    ports:
      - "5432:5432"
    volumes:
      - agflow_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agflow -d agflow"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: agflow-redis
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes"]
    ports:
      - "6379:6379"
    volumes:
      - agflow_redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  agflow_postgres_data:
  agflow_redis_data:
```

- [ ] **Step 2: Start Postgres locally**

Run: `docker compose up -d postgres && docker compose ps`
Expected: `agflow-postgres` in status `(healthy)` after ~10 seconds.

- [ ] **Step 3: Write failing test for the DB pool**

Create `backend/tests/test_db_pool.py`:

```python
from __future__ import annotations

import os

import pytest

from agflow.db.pool import close_pool, execute, fetch_one, get_pool


@pytest.fixture(autouse=True)
def _set_db_url() -> None:
    os.environ["DATABASE_URL"] = (
        "postgresql://agflow:agflow_dev@localhost:5432/agflow"
    )


@pytest.mark.asyncio
async def test_pool_connect_and_fetch_one() -> None:
    pool = await get_pool()
    assert pool is not None
    row = await fetch_one("SELECT 1 AS n")
    assert row is not None
    assert row["n"] == 1
    await close_pool()


@pytest.mark.asyncio
async def test_execute_creates_and_drops_table() -> None:
    await execute("CREATE TEMP TABLE IF NOT EXISTS t_test (id INT)")
    await execute("INSERT INTO t_test(id) VALUES (1), (2)")
    row = await fetch_one("SELECT COUNT(*) AS c FROM t_test")
    assert row is not None
    assert row["c"] == 2
    await close_pool()
```

- [ ] **Step 4: Run test to confirm it fails**

Run: `cd backend && uv run pytest tests/test_db_pool.py -v`
Expected: `ModuleNotFoundError: No module named 'agflow.db.pool'`.

- [ ] **Step 5: Implement `db/pool.py`**

Create `backend/src/agflow/db/pool.py`:

```python
from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from agflow.config import get_settings

_pool: asyncpg.Pool | None = None
_log = structlog.get_logger(__name__)


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _log.info("db.pool.create", dsn=_mask(settings.database_url))
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=30,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch_one(query: str, *args: Any) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row is not None else None


async def fetch_all(query: str, *args: Any) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(r) for r in rows]


async def execute(query: str, *args: Any) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


def _mask(dsn: str) -> str:
    """Hide the password in a DSN for logging."""
    if "@" not in dsn or "//" not in dsn:
        return dsn
    scheme, rest = dsn.split("//", 1)
    creds, host = rest.split("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        return f"{scheme}//{user}:***@{host}"
    return dsn
```

- [ ] **Step 6: Run test to confirm it passes**

Run: `cd backend && uv run pytest tests/test_db_pool.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml backend/src/agflow/db/pool.py \
        backend/src/agflow/db/__init__.py backend/tests/test_db_pool.py
git commit -m "feat(phase0): asyncpg pool + helpers + docker-compose dev infra"
```

---

### Task 7: DB migrations runner + initial migration (TDD)

**Files:**
- Create: `backend/migrations/001_init.sql`
- Create: `backend/src/agflow/db/migrations.py`
- Create: `backend/tests/test_migrations.py`

- [ ] **Step 1: Write `migrations/001_init.sql`**

Create `backend/migrations/001_init.sql`:

```sql
-- 001_init — initial schema
-- Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Migration bookkeeping
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 2: Write failing test for the runner**

Create `backend/tests/test_migrations.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute, fetch_all, fetch_one


@pytest.fixture(autouse=True)
def _set_db_url() -> None:
    os.environ["DATABASE_URL"] = (
        "postgresql://agflow:agflow_dev@localhost:5432/agflow"
    )


@pytest.mark.asyncio
async def test_run_migrations_creates_schema_migrations_table() -> None:
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")

    migrations_dir = Path(__file__).parent.parent / "migrations"
    applied = await run_migrations(migrations_dir)

    assert "001_init" in applied
    row = await fetch_one("SELECT version FROM schema_migrations WHERE version = $1", "001_init")
    assert row is not None
    assert row["version"] == "001_init"
    await close_pool()


@pytest.mark.asyncio
async def test_run_migrations_is_idempotent() -> None:
    migrations_dir = Path(__file__).parent.parent / "migrations"
    first = await run_migrations(migrations_dir)
    second = await run_migrations(migrations_dir)

    assert "001_init" in first
    assert second == []  # nothing new to apply
    rows = await fetch_all("SELECT version FROM schema_migrations")
    versions = [r["version"] for r in rows]
    assert versions.count("001_init") == 1
    await close_pool()
```

- [ ] **Step 3: Run test to confirm it fails**

Run: `cd backend && uv run pytest tests/test_migrations.py -v`
Expected: `ModuleNotFoundError: No module named 'agflow.db.migrations'`.

- [ ] **Step 4: Implement `db/migrations.py`**

Create `backend/src/agflow/db/migrations.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

import structlog

from agflow.db.pool import execute, fetch_all, get_pool

_log = structlog.get_logger(__name__)
_VERSION_RE = re.compile(r"^(\d{3,})_.*\.sql$")


async def run_migrations(migrations_dir: Path) -> list[str]:
    """Apply all SQL files in `migrations_dir` that have not yet been applied.

    Returns the list of newly applied version strings (e.g. ['001_init']).
    """
    await _ensure_bookkeeping_table()

    applied_versions = {r["version"] for r in await fetch_all("SELECT version FROM schema_migrations")}
    all_files = sorted(p for p in migrations_dir.glob("*.sql") if _VERSION_RE.match(p.name))

    newly_applied: list[str] = []
    pool = await get_pool()

    for path in all_files:
        version = path.stem
        if version in applied_versions:
            continue
        sql = path.read_text(encoding="utf-8")
        _log.info("migrations.apply", version=version)
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations(version) VALUES ($1)", version
                )
        newly_applied.append(version)

    return newly_applied


async def _ensure_bookkeeping_table() -> None:
    await execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
```

- [ ] **Step 5: Run tests to confirm they pass**

Run: `cd backend && uv run pytest tests/test_migrations.py -v`
Expected: 2 passed.

- [ ] **Step 6: Add CLI entrypoint for migrations**

Append to `backend/src/agflow/db/migrations.py`:

```python


def _cli() -> None:
    import asyncio
    from pathlib import Path

    from agflow.logging_setup import configure_logging

    configure_logging("INFO")
    migrations_dir = Path(__file__).parent.parent.parent.parent / "migrations"
    applied = asyncio.run(run_migrations(migrations_dir))
    _log.info("migrations.done", applied=applied)


if __name__ == "__main__":
    _cli()
```

- [ ] **Step 7: Smoke test CLI**

Run:
```bash
cd backend && uv run python -m agflow.db.migrations
```
Expected: log line `{"event":"migrations.done","applied":[],...}` (empty because already applied in Step 5).

- [ ] **Step 8: Commit**

```bash
git add backend/migrations/001_init.sql \
        backend/src/agflow/db/migrations.py \
        backend/tests/test_migrations.py
git commit -m "feat(phase0): SQL migrations runner + 001_init"
```

---

### Task 8: JWT auth (token encode/decode + login endpoint) (TDD)

**Files:**
- Create: `backend/src/agflow/auth/jwt.py`
- Create: `backend/src/agflow/auth/dependencies.py`
- Create: `backend/src/agflow/schemas/auth.py`
- Create: `backend/src/agflow/api/admin/auth.py`
- Create: `backend/tests/test_auth_jwt.py`
- Create: `backend/tests/test_auth_endpoint.py`
- Modify: `backend/src/agflow/main.py` (register router)

- [ ] **Step 1: Write failing test for JWT encode/decode**

Create `backend/tests/test_auth_jwt.py`:

```python
from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-key-abc")

from agflow.auth.jwt import decode_token, encode_token


def test_encode_decode_roundtrip() -> None:
    token = encode_token("admin@example.org")
    payload = decode_token(token)
    assert payload["sub"] == "admin@example.org"
    assert payload["exp"] > time.time()


def test_decode_invalid_token_raises() -> None:
    from agflow.auth.jwt import InvalidTokenError

    with pytest.raises(InvalidTokenError):
        decode_token("not.a.token")
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd backend && uv run pytest tests/test_auth_jwt.py -v`
Expected: `ModuleNotFoundError: No module named 'agflow.auth.jwt'`.

- [ ] **Step 3: Implement `auth/jwt.py`**

Create `backend/src/agflow/auth/jwt.py`:

```python
from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt

from agflow.config import get_settings


class InvalidTokenError(Exception):
    pass


def encode_token(subject: str) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + settings.jwt_expire_hours * 3600,
    }
    return pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except pyjwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
```

- [ ] **Step 4: Run JWT test**

Run: `cd backend && uv run pytest tests/test_auth_jwt.py -v`
Expected: 2 passed.

- [ ] **Step 5: Write failing test for login endpoint**

Create `backend/tests/test_auth_endpoint.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

# Test admin credentials — hash of "correct-password"
# Generated via: python -c "import bcrypt; print(bcrypt.hashpw(b'correct-password', bcrypt.gensalt()).decode())"
# The conftest seeds this via env var.


def test_login_success(client: TestClient) -> None:
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@test.local", "password": "correct-password"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_login_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@test.local", "password": "wrong"},
    )
    assert response.status_code == 401


def test_login_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "other@test.local", "password": "anything"},
    )
    assert response.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    response = client.get("/api/admin/auth/me")
    assert response.status_code == 401


def test_me_with_valid_token(client: TestClient) -> None:
    login = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@test.local", "password": "correct-password"},
    )
    token = login.json()["access_token"]
    response = client.get(
        "/api/admin/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "admin@test.local"
```

- [ ] **Step 6: Update `conftest.py` with real bcrypt hash for test admin**

Overwrite `backend/tests/conftest.py`:

```python
from __future__ import annotations

import os

import bcrypt
import pytest
from fastapi.testclient import TestClient

# Compute a real bcrypt hash of "correct-password" for the test admin
_TEST_ADMIN_HASH = bcrypt.hashpw(b"correct-password", bcrypt.gensalt(rounds=4)).decode()

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.local")
os.environ["ADMIN_PASSWORD_HASH"] = _TEST_ADMIN_HASH

from agflow.main import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)
```

- [ ] **Step 7: Implement `schemas/auth.py`**

Create `backend/src/agflow/schemas/auth.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Me(BaseModel):
    email: str
```

- [ ] **Step 8: Implement `auth/dependencies.py`**

Create `backend/src/agflow/auth/dependencies.py`:

```python
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agflow.auth.jwt import InvalidTokenError, decode_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = decode_token(creds.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return sub
```

- [ ] **Step 9: Implement `api/admin/auth.py`**

Create `backend/src/agflow/api/admin/auth.py`:

```python
from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.auth.jwt import encode_token
from agflow.config import get_settings
from agflow.schemas.auth import LoginRequest, LoginResponse, Me

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    settings = get_settings()
    if payload.email.lower() != settings.admin_email.lower():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not bcrypt.checkpw(payload.password.encode(), settings.admin_password_hash.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = encode_token(settings.admin_email)
    return LoginResponse(access_token=token)


@router.get("/me", response_model=Me)
async def me(admin_email: str = Depends(require_admin)) -> Me:
    return Me(email=admin_email)
```

- [ ] **Step 10: Register router in `main.py`**

Edit `backend/src/agflow/main.py` — add import and include_router:

```python
from agflow.api.admin.auth import router as admin_auth_router
```

And in `create_app()`:

```python
    app.include_router(health_router)
    app.include_router(admin_auth_router)
```

- [ ] **Step 11: Run all auth tests**

Run: `cd backend && uv run pytest tests/test_auth_jwt.py tests/test_auth_endpoint.py -v`
Expected: 7 passed (2 JWT + 5 endpoint).

- [ ] **Step 12: Run full test suite**

Run: `cd backend && uv run pytest -v`
Expected: all tests pass (health + config + db_pool + migrations + auth_jwt + auth_endpoint).

- [ ] **Step 13: Commit**

```bash
git add backend/src/agflow/auth/ backend/src/agflow/schemas/ \
        backend/src/agflow/api/admin/ backend/src/agflow/main.py \
        backend/tests/conftest.py backend/tests/test_auth_jwt.py backend/tests/test_auth_endpoint.py
git commit -m "feat(phase0): admin JWT auth with login + /me endpoints"
```

---

### Task 9: Backend Dockerfile + .env.example

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`
- Create: `.env.example`

- [ ] **Step 1: Write `backend/Dockerfile`**

Create `backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src /app/src
COPY migrations /app/migrations
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "agflow.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `backend/.dockerignore`**

Create `backend/.dockerignore`:

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.pytest_cache/
.coverage
.mypy_cache/
.ruff_cache/
tests/
```

- [ ] **Step 3: Write `.env.example`**

Create `.env.example` at repo root:

```bash
# ─── Database ───
DATABASE_URL=postgresql://agflow:agflow_dev@localhost:5432/agflow

# ─── Redis ───
REDIS_URL=redis://localhost:6379/0

# ─── Admin auth ───
# Generate hash with: python -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())"
ADMIN_EMAIL=admin@agflow.local
ADMIN_PASSWORD_HASH=$2b$12$REPLACEMEWITHREALBCRYPTHASHHHHHHHHHHHHHHHHHHHHHHHHH

# ─── JWT ───
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET=REPLACE_ME_WITH_A_LONG_RANDOM_STRING
JWT_EXPIRE_HOURS=24

# ─── App ───
ENVIRONMENT=dev
LOG_LEVEL=INFO

# ─── Anthropic (for Module 2 — prompt generation) ───
# ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Step 4: Verify backend Docker image builds**

Run:
```bash
cd backend && docker build -t agflow-backend:dev .
```
Expected: build succeeds, final image tagged.

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore .env.example
git commit -m "feat(phase0): backend Dockerfile + .env.example"
```

---

### Task 10: Frontend skeleton (Vite + React + TS strict)

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/index.html`
- Create: `frontend/.eslintrc.cjs`
- Create: `frontend/.prettierrc`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/vite-env.d.ts`

- [ ] **Step 1: Write `frontend/package.json`**

Create `frontend/package.json`:

```json
{
  "name": "agflow-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "format": "prettier --write src tests",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.59.0",
    "axios": "^1.7.9",
    "i18next": "^24.0.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-i18next": "^15.1.0",
    "react-router-dom": "^6.28.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/node": "^22.10.0",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@typescript-eslint/eslint-plugin": "^8.15.0",
    "@typescript-eslint/parser": "^8.15.0",
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "eslint": "^9.15.0",
    "eslint-plugin-react-hooks": "^5.0.0",
    "eslint-plugin-react-refresh": "^0.4.14",
    "jsdom": "^25.0.0",
    "postcss": "^8.4.49",
    "prettier": "^3.4.0",
    "tailwindcss": "^3.4.15",
    "typescript": "^5.7.0",
    "vite": "^5.4.11",
    "vitest": "^2.1.5"
  }
}
```

- [ ] **Step 2: Write `tsconfig.json` (strict)**

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src", "tests"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 3: Write `tsconfig.node.json`**

Create `frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts", "vitest.config.ts"]
}
```

- [ ] **Step 4: Write `vite.config.ts`**

Create `frontend/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
```

- [ ] **Step 5: Write `vitest.config.ts`**

Create `frontend/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
  },
});
```

- [ ] **Step 6: Write `index.html`**

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="fr">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>agflow.docker — Admin</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 7: Write `src/vite-env.d.ts`**

Create `frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

- [ ] **Step 8: Write `src/main.tsx`**

Create `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./lib/i18n";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 9: Write `src/App.tsx`**

Create `frontend/src/App.tsx`:

```tsx
import { Routes, Route, Navigate } from "react-router-dom";
import { LoginPage } from "./pages/LoginPage";
import { HomePage } from "./pages/HomePage";
import { ProtectedRoute } from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <HomePage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

- [ ] **Step 10: Run `npm install` to validate package.json**

Run: `cd frontend && npm install 2>&1 | tail -20`
Expected: `added N packages` without errors.

- [ ] **Step 11: Commit (partial — pages and i18n come in next tasks)**

```bash
git add frontend/package.json frontend/tsconfig.json frontend/tsconfig.node.json \
        frontend/vite.config.ts frontend/vitest.config.ts frontend/index.html \
        frontend/src/main.tsx frontend/src/App.tsx frontend/src/vite-env.d.ts
git commit -m "feat(phase0): frontend Vite+React+TS strict skeleton"
```

---

### Task 11: Frontend i18n + API client + auth hook (TDD)

**Files:**
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/i18n.ts`
- Create: `frontend/src/i18n/fr.json`
- Create: `frontend/src/i18n/en.json`
- Create: `frontend/src/hooks/useAuth.ts`
- Create: `frontend/tests/setup.ts`
- Create: `frontend/tests/hooks/useAuth.test.tsx`

- [ ] **Step 1: Write `tests/setup.ts`**

Create `frontend/tests/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  localStorage.clear();
});
```

- [ ] **Step 2: Write failing test for `useAuth`**

Create `frontend/tests/hooks/useAuth.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAuth } from "@/hooks/useAuth";

describe("useAuth", () => {
  it("starts unauthenticated when no token in storage", () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.token).toBe(null);
  });

  it("becomes authenticated after setToken", () => {
    const { result } = renderHook(() => useAuth());
    act(() => {
      result.current.setToken("fake.jwt.token");
    });
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.token).toBe("fake.jwt.token");
    expect(localStorage.getItem("agflow_token")).toBe("fake.jwt.token");
  });

  it("clears auth on logout", () => {
    localStorage.setItem("agflow_token", "pre.existing.token");
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(true);
    act(() => {
      result.current.logout();
    });
    expect(result.current.isAuthenticated).toBe(false);
    expect(localStorage.getItem("agflow_token")).toBe(null);
  });
});
```

- [ ] **Step 3: Run failing test**

Run: `cd frontend && npm test -- useAuth`
Expected: error `Cannot find module '@/hooks/useAuth'`.

- [ ] **Step 4: Implement `hooks/useAuth.ts`**

Create `frontend/src/hooks/useAuth.ts`:

```ts
import { useCallback, useState } from "react";

const STORAGE_KEY = "agflow_token";

export interface UseAuth {
  token: string | null;
  isAuthenticated: boolean;
  setToken: (token: string) => void;
  logout: () => void;
}

export function useAuth(): UseAuth {
  const [token, setTokenState] = useState<string | null>(() =>
    localStorage.getItem(STORAGE_KEY),
  );

  const setToken = useCallback((newToken: string) => {
    localStorage.setItem(STORAGE_KEY, newToken);
    setTokenState(newToken);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setTokenState(null);
  }, []);

  return {
    token,
    isAuthenticated: token !== null,
    setToken,
    logout,
  };
}
```

- [ ] **Step 5: Run test to confirm it passes**

Run: `cd frontend && npm test -- useAuth`
Expected: 3 passed.

- [ ] **Step 6: Implement `lib/api.ts`**

Create `frontend/src/lib/api.ts`:

```ts
import axios, { type AxiosInstance } from "axios";

const STORAGE_KEY = "agflow_token";

export const api: AxiosInstance = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(STORAGE_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(STORAGE_KEY);
      window.location.assign("/login");
    }
    return Promise.reject(error);
  },
);
```

- [ ] **Step 7: Implement `lib/i18n.ts`**

Create `frontend/src/lib/i18n.ts`:

```ts
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import fr from "@/i18n/fr.json";
import en from "@/i18n/en.json";

void i18n.use(initReactI18next).init({
  resources: {
    fr: { translation: fr },
    en: { translation: en },
  },
  lng: "fr",
  fallbackLng: "fr",
  interpolation: { escapeValue: false },
});

export default i18n;
```

- [ ] **Step 8: Create i18n JSON files**

Create `frontend/src/i18n/fr.json`:

```json
{
  "app": {
    "title": "agflow.docker"
  },
  "login": {
    "title": "Connexion",
    "email": "Email",
    "password": "Mot de passe",
    "submit": "Se connecter",
    "error_invalid": "Identifiants invalides"
  },
  "home": {
    "welcome": "Bienvenue sur agflow.docker",
    "logout": "Déconnexion"
  },
  "status": {
    "missing": "Variable manquante",
    "empty": "Variable présente mais vide",
    "ok": "Variable renseignée"
  }
}
```

Create `frontend/src/i18n/en.json`:

```json
{
  "app": {
    "title": "agflow.docker"
  },
  "login": {
    "title": "Login",
    "email": "Email",
    "password": "Password",
    "submit": "Sign in",
    "error_invalid": "Invalid credentials"
  },
  "home": {
    "welcome": "Welcome to agflow.docker",
    "logout": "Log out"
  },
  "status": {
    "missing": "Variable missing",
    "empty": "Variable present but empty",
    "ok": "Variable set"
  }
}
```

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/ frontend/src/i18n/ frontend/src/hooks/ \
        frontend/tests/setup.ts frontend/tests/hooks/
git commit -m "feat(phase0): frontend i18n + api client + useAuth hook"
```

---

### Task 12: StatusIndicator component (TDD) + Login + Home pages

**Files:**
- Create: `frontend/src/components/StatusIndicator.tsx`
- Create: `frontend/src/components/ProtectedRoute.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/HomePage.tsx`
- Create: `frontend/tests/components/StatusIndicator.test.tsx`
- Create: `frontend/tests/pages/LoginPage.test.tsx`

- [ ] **Step 1: Write failing test for StatusIndicator**

Create `frontend/tests/components/StatusIndicator.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusIndicator } from "@/components/StatusIndicator";

describe("StatusIndicator", () => {
  it("renders red dot when status is missing", () => {
    render(<StatusIndicator status="missing" label="TEST_VAR" />);
    expect(screen.getByRole("img", { name: /TEST_VAR/ })).toHaveTextContent("🔴");
  });

  it("renders orange dot when status is empty", () => {
    render(<StatusIndicator status="empty" label="TEST_VAR" />);
    expect(screen.getByRole("img", { name: /TEST_VAR/ })).toHaveTextContent("🟠");
  });

  it("renders green dot when status is ok", () => {
    render(<StatusIndicator status="ok" label="TEST_VAR" />);
    expect(screen.getByRole("img", { name: /TEST_VAR/ })).toHaveTextContent("🟢");
  });
});
```

- [ ] **Step 2: Run failing test**

Run: `cd frontend && npm test -- StatusIndicator`
Expected: `Cannot find module '@/components/StatusIndicator'`.

- [ ] **Step 3: Implement `components/StatusIndicator.tsx`**

Create `frontend/src/components/StatusIndicator.tsx`:

```tsx
import { useTranslation } from "react-i18next";

export type IndicatorStatus = "missing" | "empty" | "ok";

interface Props {
  status: IndicatorStatus;
  label: string;
}

const GLYPHS: Record<IndicatorStatus, string> = {
  missing: "🔴",
  empty: "🟠",
  ok: "🟢",
};

export function StatusIndicator({ status, label }: Props) {
  const { t } = useTranslation();
  const title = `${label} — ${t(`status.${status}`)}`;
  return (
    <span role="img" aria-label={title} title={title}>
      {GLYPHS[status]}
    </span>
  );
}
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `cd frontend && npm test -- StatusIndicator`
Expected: 3 passed.

- [ ] **Step 5: Implement `components/ProtectedRoute.tsx`**

Create `frontend/src/components/ProtectedRoute.tsx`:

```tsx
import { Navigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
}

export function ProtectedRoute({ children }: Props) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
```

- [ ] **Step 6: Implement `pages/LoginPage.tsx`**

Create `frontend/src/pages/LoginPage.tsx`:

```tsx
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { setToken } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await api.post<{ access_token: string }>(
        "/admin/auth/login",
        { email, password },
      );
      setToken(res.data.access_token);
      navigate("/");
    } catch {
      setError(t("login.error_invalid"));
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: "4rem auto", padding: "1rem" }}>
      <h1>{t("login.title")}</h1>
      <form onSubmit={handleSubmit}>
        <div>
          <label>
            {t("login.email")}
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
        </div>
        <div>
          <label>
            {t("login.password")}
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
        </div>
        {error && <p role="alert" style={{ color: "red" }}>{error}</p>}
        <button type="submit">{t("login.submit")}</button>
      </form>
    </div>
  );
}
```

- [ ] **Step 7: Write test for LoginPage**

Create `frontend/tests/pages/LoginPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LoginPage } from "@/pages/LoginPage";
import { api } from "@/lib/api";
import "@/lib/i18n";

vi.mock("@/lib/api", () => ({
  api: { post: vi.fn() },
}));

function renderWithRouter() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders form labels in French", () => {
    renderWithRouter();
    expect(screen.getByRole("heading")).toHaveTextContent("Connexion");
    expect(screen.getByLabelText(/Email/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Mot de passe/)).toBeInTheDocument();
  });

  it("submits credentials and stores token on success", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { access_token: "abc.def.ghi" },
    } as never);
    renderWithRouter();
    await userEvent.type(screen.getByLabelText(/Email/), "admin@test.local");
    await userEvent.type(screen.getByLabelText(/Mot de passe/), "correct-password");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    await waitFor(() => {
      expect(localStorage.getItem("agflow_token")).toBe("abc.def.ghi");
    });
  });

  it("shows error message on failed login", async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error("401"));
    renderWithRouter();
    await userEvent.type(screen.getByLabelText(/Email/), "admin@test.local");
    await userEvent.type(screen.getByLabelText(/Mot de passe/), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Identifiants invalides");
  });
});
```

- [ ] **Step 8: Implement `pages/HomePage.tsx`**

Create `frontend/src/pages/HomePage.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export function HomePage() {
  const { t } = useTranslation();
  const { logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div style={{ padding: "2rem" }}>
      <h1>{t("home.welcome")}</h1>
      <button type="button" onClick={handleLogout}>
        {t("home.logout")}
      </button>
    </div>
  );
}
```

- [ ] **Step 9: Run full frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests green (StatusIndicator + LoginPage + useAuth).

- [ ] **Step 10: Verify TS strict compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 11: Verify dev server starts**

Run (separate terminal):
```bash
cd frontend && npm run dev &
sleep 3
curl -s http://localhost:5173/ | grep -q 'id="root"' && echo OK
kill %1
```
Expected: `OK` printed.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/components/ frontend/src/pages/ \
        frontend/tests/components/ frontend/tests/pages/
git commit -m "feat(phase0): StatusIndicator + Login/Home pages with tests"
```

---

### Task 13: Frontend Dockerfile + nginx config

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `frontend/.dockerignore`

- [ ] **Step 1: Write `frontend/Dockerfile`**

Create `frontend/Dockerfile`:

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

- [ ] **Step 2: Write `frontend/nginx.conf`**

Create `frontend/nginx.conf`:

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 3: Write `.dockerignore`**

Create `frontend/.dockerignore`:

```
node_modules/
dist/
.vite/
tests/
coverage/
*.log
```

- [ ] **Step 4: Build frontend image**

Run: `cd frontend && docker build -t agflow-frontend:dev .`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf frontend/.dockerignore
git commit -m "feat(phase0): frontend Dockerfile + nginx SPA config"
```

---

### Task 14: `docker-compose.prod.yml` + deploy script

**Files:**
- Create: `docker-compose.prod.yml`
- Create: `scripts/deploy.sh`

- [ ] **Step 1: Write `docker-compose.prod.yml`**

Create `docker-compose.prod.yml`:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: agflow-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-agflow}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?postgres password required}
      POSTGRES_DB: ${POSTGRES_DB:-agflow}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      retries: 5
    networks: [agflow]

  redis:
    image: redis:7-alpine
    container_name: agflow-redis
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5
    networks: [agflow]

  backend:
    image: agflow-backend:latest
    container_name: agflow-backend
    restart: unless-stopped
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    networks: [agflow]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 10s
      retries: 5

  frontend:
    image: agflow-frontend:latest
    container_name: agflow-frontend
    restart: unless-stopped
    depends_on: [backend]
    networks: [agflow]

  caddy:
    image: caddy:2-alpine
    container_name: agflow-caddy
    restart: unless-stopped
    ports:
      - "80:80"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on: [frontend, backend]
    networks: [agflow]

volumes:
  postgres_data:
  redis_data:
  caddy_data:
  caddy_config:

networks:
  agflow:
    driver: bridge
```

- [ ] **Step 2: Write `Caddyfile` for prod**

Create `Caddyfile` at repo root:

```
:80 {
    @api path /api/*
    handle @api {
        reverse_proxy backend:8000
    }

    handle {
        reverse_proxy frontend:80
    }
}
```

- [ ] **Step 3: Write `scripts/deploy.sh`**

Create `scripts/deploy.sh`:

```bash
#!/usr/bin/env bash
###############################################################################
# Deploy agflow.docker to LXC 201 (192.168.10.82)
# Prereqs: ssh alias `pve`, SSH key injected in CT 201, CT 201 has Docker installed.
###############################################################################
set -euo pipefail

CTID="${CTID:-201}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
REPO_DIR_ON_HOST="/root/agflow.docker"

echo "==> Building backend image..."
docker build -t "agflow-backend:${IMAGE_TAG}" ./backend

echo "==> Building frontend image..."
docker build -t "agflow-frontend:${IMAGE_TAG}" ./frontend

echo "==> Saving images to tarballs..."
docker save "agflow-backend:${IMAGE_TAG}" | gzip > /tmp/agflow-backend.tar.gz
docker save "agflow-frontend:${IMAGE_TAG}" | gzip > /tmp/agflow-frontend.tar.gz

echo "==> Uploading to pve and pushing into CT ${CTID}..."
scp /tmp/agflow-backend.tar.gz /tmp/agflow-frontend.tar.gz pve:/tmp/
ssh pve "pct push ${CTID} /tmp/agflow-backend.tar.gz /root/agflow-backend.tar.gz && \
         pct push ${CTID} /tmp/agflow-frontend.tar.gz /root/agflow-frontend.tar.gz && \
         pct exec ${CTID} -- mkdir -p ${REPO_DIR_ON_HOST}"

echo "==> Uploading compose files + Caddyfile + .env..."
tar czf /tmp/agflow-deploy.tar.gz docker-compose.prod.yml Caddyfile .env 2>/dev/null || {
  echo "ERROR: .env missing. Create it from .env.example before deploying."
  exit 1
}
scp /tmp/agflow-deploy.tar.gz pve:/tmp/
ssh pve "pct push ${CTID} /tmp/agflow-deploy.tar.gz /root/agflow-deploy.tar.gz && \
         pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_HOST} && tar xzf /root/agflow-deploy.tar.gz'"

echo "==> Loading images + starting stack in CT ${CTID}..."
ssh pve "pct exec ${CTID} -- bash -c '
  docker load < /root/agflow-backend.tar.gz
  docker load < /root/agflow-frontend.tar.gz
  cd ${REPO_DIR_ON_HOST}
  docker compose -f docker-compose.prod.yml up -d
  docker compose -f docker-compose.prod.yml ps
'"

echo ""
echo "==> Deployed. Test: curl http://192.168.10.82/health"
```

- [ ] **Step 4: Make script executable**

Run: `chmod +x scripts/deploy.sh`

- [ ] **Step 5: Commit**

```bash
git add docker-compose.prod.yml Caddyfile scripts/deploy.sh
git commit -m "feat(phase0): prod compose + Caddy + deploy script"
```

---

### Task 15: Full verification + LXC 201 smoke test

- [ ] **Step 1: Run full backend test suite**

Run:
```bash
docker compose up -d postgres
cd backend && uv run pytest -v
```
Expected: all tests green.

- [ ] **Step 2: Run backend lint**

Run: `cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`
Expected: clean, no issues.

- [ ] **Step 3: Run full frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests green.

- [ ] **Step 4: Run frontend TS strict check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: clean, no warnings.

- [ ] **Step 6: Generate `.env` from `.env.example`**

Run:
```bash
cp .env.example .env
# Edit .env and fill: ADMIN_PASSWORD_HASH, JWT_SECRET, POSTGRES_PASSWORD
python -c "import bcrypt; print('ADMIN_PASSWORD_HASH=' + bcrypt.hashpw(b'agflow-admin-2026', bcrypt.gensalt()).decode())"
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
```

Manually append these 3 lines to `.env`.

- [ ] **Step 7: Deploy to LXC 201**

Run: `./scripts/deploy.sh`
Expected: script finishes, final output shows all containers running.

- [ ] **Step 8: Smoke test LXC 201 endpoints**

Run:
```bash
curl -s http://192.168.10.82/health
curl -s -X POST http://192.168.10.82/api/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@agflow.local","password":"agflow-admin-2026"}'
```
Expected:
1. `{"status":"ok"}`
2. `{"access_token":"...","token_type":"bearer"}`

- [ ] **Step 9: Apply migrations on LXC 201**

Run:
```bash
ssh pve "pct exec 201 -- docker exec agflow-backend python -m agflow.db.migrations"
```
Expected: log entry `migrations.done applied=['001_init']` (first run) or `applied=[]` (already applied).

- [ ] **Step 10: Verify schema_migrations table**

Run:
```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d agflow -c 'SELECT * FROM schema_migrations'"
```
Expected: 1 row with `version=001_init`.

- [ ] **Step 11: Move plan file into the repo**

Run:
```bash
mkdir -p docs/superpowers/plans
cp "C:/Users/g.beard/.claude/plans/dapper-crafting-narwhal.md" docs/superpowers/plans/2026-04-10-phase0-bootstrap.md
git add docs/superpowers/plans/2026-04-10-phase0-bootstrap.md
git commit -m "docs(phase0): add phase 0 bootstrap plan to repo"
```

- [ ] **Step 12: Push to GitHub**

Run: `git push origin main`
Expected: push succeeds.

- [ ] **Step 13: Phase 0 complete — write the Phase 1 plan next**

Per the scope decomposition, the next step after Phase 0 is writing the Phase 1 plan (Module 0 — Secrets) using the same TDD bite-sized format, saved to `docs/superpowers/plans/2026-04-XX-phase1-secrets.md`.

---

## Self-Review Checklist

**1. Spec coverage (for Phase 0 scope only):**
- ✅ Monorepo skeleton : Tasks 1, 3, 10
- ✅ FastAPI backend with health : Tasks 4, 5
- ✅ asyncpg pool : Task 6
- ✅ Migrations runner : Task 7
- ✅ JWT admin auth : Task 8
- ✅ Backend Dockerfile : Task 9
- ✅ Vite+React+TS strict : Tasks 10, 11, 12
- ✅ Frontend Dockerfile + nginx : Task 13
- ✅ Prod compose + Caddy + deploy : Task 14
- ✅ LXC 201 smoke test : Task 15
- ✅ CLAUDE.md rewrite : Task 2
- ✅ LandGraph docs cleanup : Task 1
- ✅ Visual indicator 🔴🟠🟢 component : Task 12 (StatusIndicator)
- ✅ i18n foundation : Task 11

**Out of scope for Phase 0 (future phases):** modules M0-M6, MOM Redis Streams, aiodocker wrappers, MCP/Skills catalogs, Docker images build (agents), mockups Module 4, CI/CD pipeline.

**2. Placeholder scan:** Every step has exact code, exact commands, and expected output. No "TODO", "TBD", "add appropriate error handling", "implement later". ✅

**3. Type consistency:** `Settings` fields used in Task 4 match the JWT/auth usage in Task 8 (`jwt_secret`, `admin_email`, `admin_password_hash`, `jwt_expire_hours`). `useAuth` hook contract (`token`, `isAuthenticated`, `setToken`, `logout`) matches usage in `LoginPage` and `ProtectedRoute`. API client `/admin/auth/login` path matches backend router prefix `/api/admin/auth` with Vite proxy stripping `/api/`. ✅

---

## Execution Handoff

After this plan is approved and the plan file moved into the repo (Task 15 Step 11), there are two ways to execute:

1. **Subagent-Driven** *(recommended for this kind of multi-step plan)* — dispatch a fresh subagent per task, two-stage review between tasks, fast iteration. Uses skill `superpowers:subagent-driven-development`.
2. **Inline Execution** — execute tasks in the current session with checkpoints every few tasks. Uses skill `superpowers:executing-plans`.

Once you approve the plan, tell me which approach you prefer and whether you want me to start immediately with Task 1 or pause for a review.

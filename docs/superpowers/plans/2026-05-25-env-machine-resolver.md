# Résolveur unifié des placeholders + support `${env-machine://}` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centraliser la résolution des 4 syntaxes de placeholders (`${VAR}`, `${env://}`, `${vault://}`, `${env-machine://}`) dans un service dédié `input_resolver`, adopter une politique fail-fast alignée à l'exécution, et étendre le check de pré-déploiement pour qu'il utilise le même résolveur en mode "collect-all". Garantit `check vert ⇔ exécution OK` par construction.

**Architecture:** Nouveau module `input_resolver.py` qui orchestre les 4 résolutions dans un ordre figé, lève `UnresolvedPlaceholderError(kind, ref, detail, var_name)` au 1er échec (fail-fast) ou accumule les erreurs (collect-all). Les 2 callsites d'exécution (`_run_script_streaming` dans `deployment_executor`, `_run_group_script` dans `project_deployments`) sont migrés vers ce service. Le check `check_project_env_vars` utilise la variante collect-all et transforme les erreurs en `ProjectEnvVarsCheckMissingReason` typés. La bannière frontend affiche la raison détaillée par variable non résoluble.

**Tech Stack:** Python 3.12 + asyncio + asyncpg + Pydantic v2 + pytest-asyncio ; React 18 + TanStack Query + i18next + Vitest

**Spec source:** [docs/superpowers/specs/2026-05-25-env-machine-resolver-design.md](../specs/2026-05-25-env-machine-resolver-design.md)

---

## Structure des fichiers

**À créer :**
- `backend/src/agflow/services/placeholder_parsers.py` — regex + parsers purs (pas d'I/O)
- `backend/src/agflow/services/input_resolver.py` — orchestration des 4 résolutions + exceptions typées
- `backend/tests/services/test_placeholder_parsers.py` — tests unitaires purs
- `backend/tests/services/test_input_resolver.py` — tests avec mocks pour les dépendances DB
- `backend/tests/services/test_check_project_env_vars.py` — tests d'intégration du check

**À modifier :**
- `backend/src/agflow/schemas/infra_env_vars.py:66-81` — ajout `ProjectEnvVarsCheckMissingReason`, breaking change sur `ProjectEnvVarsCheckMissing.missing_env_vars` → `missing`
- `backend/src/agflow/services/infra_env_vars_service.py:286-352` — refonte `check_project_env_vars`
- `backend/src/agflow/api/admin/project_deployments.py:319-336` — migration `_run_group_script`
- `backend/src/agflow/services/deployment_executor.py:46-62` — migration `_run_script_streaming`
- `backend/src/agflow/services/deployment_env_helpers.py:15-41` — suppression `resolve_input_value`
- `frontend/src/lib/infraEnvVarsApi.ts:50-60` — types `ProjectEnvVarsCheckMissingReason` + breaking `missing`
- `frontend/src/pages/ProjectDetailPage.tsx:193-211` — bannière avec raisons détaillées
- `frontend/src/i18n/fr.json` + `en.json` — clés `projects.env_vars_reason.*` + label banner reformulé

---

## Task 1 : Parsers purs (placeholder_parsers.py)

**Files:**
- Create: `backend/src/agflow/services/placeholder_parsers.py`
- Create: `backend/tests/services/test_placeholder_parsers.py`

- [x] **Step 1 : Écrire le test rouge — patterns de détection**

Créer `backend/tests/services/test_placeholder_parsers.py` :

```python
# backend/tests/services/test_placeholder_parsers.py
"""Tests unitaires purs des parsers de placeholders. Aucun I/O."""
from __future__ import annotations

from agflow.services.placeholder_parsers import (
    ENV_MACHINE_RE,
    ENV_REF_RE,
    SIMPLE_VAR_RE,
    UNKNOWN_BRACE_RE,
    VAULT_REF_RE,
    parse_env_machine_ref,
    parse_env_text,
)


class TestEnvMachineRef:
    def test_parses_machine_and_var(self) -> None:
        result = parse_env_machine_ref("${env-machine://keycloak1:KC_ADMIN_PASSWORD}")
        assert result == ("keycloak1", "KC_ADMIN_PASSWORD")

    def test_returns_none_for_non_machine_ref(self) -> None:
        assert parse_env_machine_ref("${env://NAME}") is None
        assert parse_env_machine_ref("plain value") is None
        assert parse_env_machine_ref("") is None

    def test_strips_surrounding_whitespace(self) -> None:
        result = parse_env_machine_ref("  ${env-machine://m1:VAR}  ")
        assert result == ("m1", "VAR")


class TestEnvText:
    def test_parses_key_value_lines(self) -> None:
        text = "FOO=bar\nBAZ=qux\n"
        assert parse_env_text(text) == {"FOO": "bar", "BAZ": "qux"}

    def test_ignores_comments_and_blank_lines(self) -> None:
        text = "# comment\n\nFOO=bar\n"
        assert parse_env_text(text) == {"FOO": "bar"}

    def test_ignores_lines_without_equals(self) -> None:
        text = "FOO=bar\nnokey\nBAZ=qux\n"
        assert parse_env_text(text) == {"FOO": "bar", "BAZ": "qux"}

    def test_returns_empty_dict_for_empty_input(self) -> None:
        assert parse_env_text("") == {}
        assert parse_env_text(None) == {}  # type: ignore[arg-type]


class TestRegexPatterns:
    def test_env_machine_re_matches_only_well_formed_refs(self) -> None:
        assert ENV_MACHINE_RE.findall("${env-machine://m1:VAR}") == [("m1", "VAR")]
        assert ENV_MACHINE_RE.findall("${env://NAME}") == []

    def test_vault_re_matches(self) -> None:
        assert VAULT_REF_RE.findall("${vault://api:SECRET_NAME}") == ["SECRET_NAME"]

    def test_env_ref_re_matches(self) -> None:
        assert ENV_REF_RE.findall("${env://CONFIG}") == ["CONFIG"]

    def test_simple_var_re_matches_uppercase_only(self) -> None:
        # SIMPLE_VAR_RE matches ${VAR} or $VAR with [A-Z_][A-Z0-9_]*
        text = "${FOO} $BAR ${lower} ${MIX_3}"
        matches = [m.group(1) or m.group(2) for m in SIMPLE_VAR_RE.finditer(text)]
        assert matches == ["FOO", "BAR", "MIX_3"]

    def test_unknown_brace_re_catches_residual_braces(self) -> None:
        # Used to detect ${...} that didn't match any of the 4 patterns
        assert UNKNOWN_BRACE_RE.findall("${foo-bar}") == ["foo-bar"]
        assert UNKNOWN_BRACE_RE.findall("${non.standard}") == ["non.standard"]
```

- [x] **Step 2 : Run test to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_placeholder_parsers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agflow.services.placeholder_parsers'`

- [x] **Step 3 : Implémenter placeholder_parsers.py**

Créer `backend/src/agflow/services/placeholder_parsers.py` :

```python
# backend/src/agflow/services/placeholder_parsers.py
"""Parsers purs des placeholders d'input. Aucun I/O — testables sans mocks.

Reconnaît 4 syntaxes :
- ${env-machine://<machine>:<VAR>}  — variable d'env d'une machine distante
- ${vault://api:<NAME>}              — secret Harpocrate
- ${env://<NAME>}                    — variable globale platform_secrets
- ${VAR} / $VAR                      — variable du .env de déploiement (MAJUSCULES)

Le pattern UNKNOWN_BRACE_RE sert à détecter les ${...} résiduels qui ne
matchent aucun des 4 patterns ci-dessus (erreur de saisie probable).
"""
from __future__ import annotations

import re

ENV_MACHINE_RE = re.compile(r"\$\{env-machine://([^:}]+):([^}]+)\}")
VAULT_REF_RE = re.compile(r"\$\{vault://[^:}]+:([^}]+)\}")
ENV_REF_RE = re.compile(r"\$\{env://([^}]+)\}")
SIMPLE_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]*)")
# Détecte tout ${...} restant après les 4 substitutions ci-dessus.
UNKNOWN_BRACE_RE = re.compile(r"\$\{([^}]+)\}")


def parse_env_machine_ref(value: str | None) -> tuple[str, str] | None:
    """Retourne (machine_name, var_name) si la valeur est entièrement une ref env-machine, sinon None."""
    if not value:
        return None
    m = re.fullmatch(
        r"\s*\$\{env-machine://([^:}]+):([^}]+)\}\s*",
        value,
    )
    return (m.group(1), m.group(2)) if m else None


def parse_env_text(env_text: str | None) -> dict[str, str]:
    """Parse un .env text vers dict[name, value]. Ignore blanks et commentaires."""
    result: dict[str, str] = {}
    for line in (env_text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip()
    return result
```

- [x] **Step 4 : Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/services/test_placeholder_parsers.py -v`
Expected: PASS — 9 tests

- [x] **Step 5 : Lint + format**

Run: `cd backend && uv run ruff check src/agflow/services/placeholder_parsers.py tests/services/test_placeholder_parsers.py && uv run ruff format src/agflow/services/placeholder_parsers.py tests/services/test_placeholder_parsers.py`
Expected: no errors

- [x] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/placeholder_parsers.py backend/tests/services/test_placeholder_parsers.py
git commit -m "feat(resolver): placeholder_parsers — regex + parsers purs"
```

---

## Task 2 : Exception UnresolvedPlaceholderError + classe de base input_resolver

**Files:**
- Create: `backend/src/agflow/services/input_resolver.py`
- Create: `backend/tests/services/test_input_resolver.py`

- [x] **Step 1 : Écrire le test rouge — exception**

Créer `backend/tests/services/test_input_resolver.py` :

```python
# backend/tests/services/test_input_resolver.py
"""Tests unitaires d'input_resolver. Mocks pour les dépendances DB."""
from __future__ import annotations

import pytest

from agflow.services.input_resolver import UnresolvedPlaceholderError


class TestUnresolvedPlaceholderError:
    def test_carries_kind_ref_detail_varname(self) -> None:
        err = UnresolvedPlaceholderError(
            kind="machine_not_found",
            ref="${env-machine://keycloak1:KC_ADMIN_PASSWORD}",
            detail="machine 'keycloak1' inconnue",
            var_name="KC_ADMIN_PASSWORD",
        )
        assert err.kind == "machine_not_found"
        assert err.ref == "${env-machine://keycloak1:KC_ADMIN_PASSWORD}"
        assert err.detail == "machine 'keycloak1' inconnue"
        assert err.var_name == "KC_ADMIN_PASSWORD"

    def test_str_contains_useful_info(self) -> None:
        err = UnresolvedPlaceholderError(
            kind="env_machine_var_empty",
            ref="${env-machine://m1:VAR}",
            detail="variable 'VAR' vide sur 'm1'",
            var_name="VAR",
        )
        msg = str(err)
        assert "env_machine_var_empty" in msg
        assert "VAR" in msg
```

- [x] **Step 2 : Run test — fails (module missing)**

Run: `cd backend && uv run pytest tests/services/test_input_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3 : Créer input_resolver.py avec l'exception**

Créer `backend/src/agflow/services/input_resolver.py` :

```python
# backend/src/agflow/services/input_resolver.py
"""Résolveur unifié des placeholders d'input pour les group_scripts.

Orchestre les 4 syntaxes (env-machine://, vault://, env://, ${VAR}) dans
un ordre figé. Politique fail-fast à l'exécution ; variante collect-all
pour le check de pré-déploiement.

Voir docs/superpowers/specs/2026-05-25-env-machine-resolver-design.md
"""
from __future__ import annotations

from typing import Literal

UnresolvedKind = Literal[
    "value_empty",
    "var_not_in_env",
    "platform_secret_missing",
    "machine_not_found",
    "env_machine_var_not_found",
    "env_machine_var_empty",
    "unknown_ref",
]


class UnresolvedPlaceholderError(Exception):
    """Levée quand une référence dans un input_value ne peut être résolue.

    L'objet porte assez d'information pour générer un message humain
    précis et pour catégoriser l'erreur dans la réponse API du check.
    """

    def __init__(
        self,
        *,
        kind: UnresolvedKind,
        ref: str,
        detail: str,
        var_name: str | None = None,
    ) -> None:
        self.kind = kind
        self.ref = ref
        self.detail = detail
        self.var_name = var_name
        super().__init__(f"{kind}: {detail} (var={var_name}, ref={ref})")
```

- [x] **Step 4 : Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/services/test_input_resolver.py -v`
Expected: PASS — 2 tests

- [x] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/input_resolver.py backend/tests/services/test_input_resolver.py
git commit -m "feat(resolver): UnresolvedPlaceholderError + squelette input_resolver"
```

---

## Task 3 : `resolve_input_values` — résolution fail-fast

**Files:**
- Modify: `backend/src/agflow/services/input_resolver.py`
- Modify: `backend/tests/services/test_input_resolver.py`

- [x] **Step 1 : Écrire les tests rouges — résolution OK**

Ajouter à `backend/tests/services/test_input_resolver.py` :

```python
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from agflow.services.input_resolver import (
    UnresolvedPlaceholderError,
    resolve_input_values,
)

MACHINE_ID = uuid4()


@pytest.fixture
def mock_resolve_for_machine():
    """Mock infra_env_vars_service.resolve_for_machine — retourne env vars de la machine cible."""
    with patch(
        "agflow.services.input_resolver.infra_env_vars_service.resolve_for_machine",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = {}
        yield m


@pytest.fixture
def mock_get_machine_by_name():
    """Mock machines_service.get_by_name — lookup machine par nom (cas env-machine://)."""
    with patch(
        "agflow.services.input_resolver.infra_machines_service.get_by_name",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = None  # par défaut : machine inconnue
        yield m


@pytest.fixture
def mock_resolve_for_named_machine():
    """Mock infra_env_vars_service.resolve_for_machine pour une machine arbitraire."""
    with patch(
        "agflow.services.input_resolver.infra_env_vars_service.resolve_for_machine",
        new_callable=AsyncMock,
    ) as m:
        yield m


class TestResolveInputValuesFailFast:
    async def test_literal_value_preserved(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"PORT": "8080"},
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={},
        )
        assert result == {"PORT": "8080"}

    async def test_simple_var_resolved_from_env_text(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"HOST": "${MY_HOST}"},
            target_machine_id=MACHINE_ID,
            env_text="MY_HOST=example.com",
            platform_secrets_map={},
        )
        assert result == {"HOST": "example.com"}

    async def test_env_ref_resolved_from_platform_secrets(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"API_URL": "${env://API_URL}"},
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={"API_URL": "https://api.example.com"},
        )
        assert result == {"API_URL": "https://api.example.com"}

    async def test_vault_ref_resolved_from_platform_secrets(self, mock_resolve_for_machine) -> None:
        # platform_secrets_service.resolve_all renvoie déjà les valeurs vault déchiffrées
        # indexées par le NAME de la ref vault://api:NAME — c'est cohérent par construction
        # (cf. platform_secrets_service.resolve_all:171-188).
        result = await resolve_input_values(
            input_values={"TOKEN": "${vault://api:GITHUB_TOKEN}"},
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={"GITHUB_TOKEN": "ghp_xxx"},
        )
        assert result == {"TOKEN": "ghp_xxx"}

    async def test_env_machine_ref_resolved(
        self, mock_get_machine_by_name, mock_resolve_for_named_machine,
    ) -> None:
        # machine 'keycloak1' existe, contient KC_ADMIN_PASSWORD
        from types import SimpleNamespace
        kc_id = uuid4()
        mock_get_machine_by_name.return_value = SimpleNamespace(id=kc_id, name="keycloak1")
        mock_resolve_for_named_machine.return_value = {"KC_ADMIN_PASSWORD": "s3cret"}

        result = await resolve_input_values(
            input_values={"KC_ADMIN_PASSWORD": "${env-machine://keycloak1:KC_ADMIN_PASSWORD}"},
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={},
        )
        assert result == {"KC_ADMIN_PASSWORD": "s3cret"}
        mock_get_machine_by_name.assert_awaited_with("keycloak1")
        mock_resolve_for_named_machine.assert_awaited_with(kc_id)

    async def test_mixed_value_prefix_ref_suffix(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"URL": "https://${HOST}:8080/api"},
            target_machine_id=MACHINE_ID,
            env_text="HOST=example.com",
            platform_secrets_map={},
        )
        assert result == {"URL": "https://example.com:8080/api"}
```

- [x] **Step 2 : Écrire les tests rouges — résolution KO**

Ajouter à la suite :

```python
class TestResolveInputValuesErrors:
    async def test_empty_value_raises_value_empty(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"PASSWORD": ""},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "value_empty"
        assert exc_info.value.var_name == "PASSWORD"

    async def test_simple_var_not_in_env_raises(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"HOST": "${MY_HOST}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "var_not_in_env"
        assert exc_info.value.var_name == "HOST"
        assert "MY_HOST" in exc_info.value.detail

    async def test_empty_var_in_env_raises(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"HOST": "${MY_HOST}"},
                target_machine_id=MACHINE_ID,
                env_text="MY_HOST=",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "var_not_in_env"

    async def test_env_ref_missing_raises_platform_secret_missing(
        self, mock_resolve_for_machine,
    ) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${env://NO_SUCH}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "platform_secret_missing"

    async def test_vault_ref_missing_raises_platform_secret_missing(
        self, mock_resolve_for_machine,
    ) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${vault://api:NO_SUCH}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "platform_secret_missing"

    async def test_env_machine_unknown_machine_raises(
        self, mock_get_machine_by_name, mock_resolve_for_named_machine,
    ) -> None:
        mock_get_machine_by_name.return_value = None
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${env-machine://ghost:VAR}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "machine_not_found"
        assert "ghost" in exc_info.value.detail

    async def test_env_machine_var_missing_raises(
        self, mock_get_machine_by_name, mock_resolve_for_named_machine,
    ) -> None:
        from types import SimpleNamespace
        mock_get_machine_by_name.return_value = SimpleNamespace(id=uuid4(), name="m1")
        mock_resolve_for_named_machine.return_value = {"OTHER": "v"}
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${env-machine://m1:MISSING}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "env_machine_var_not_found"
        assert "MISSING" in exc_info.value.detail

    async def test_env_machine_var_empty_raises(
        self, mock_get_machine_by_name, mock_resolve_for_named_machine,
    ) -> None:
        # resolve_for_machine filtre les valeurs vides (cf. infra_env_vars_service:281)
        # donc en pratique env_machine_var_empty ne sera levé que si on contourne
        # ce filtre. Mais on teste le code défensif.
        from types import SimpleNamespace
        mock_get_machine_by_name.return_value = SimpleNamespace(id=uuid4(), name="m1")
        mock_resolve_for_named_machine.return_value = {"VAR": ""}
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${env-machine://m1:VAR}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind in ("env_machine_var_empty", "env_machine_var_not_found")

    async def test_unknown_brace_raises_unknown_ref(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${foo-bar}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "unknown_ref"
        assert "foo-bar" in exc_info.value.detail

    async def test_fail_fast_stops_at_first_error(self, mock_resolve_for_machine) -> None:
        # 2 variables KO, on doit lever sur la première (ordre du dict en Python 3.7+)
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"FIRST": "${MISSING_A}", "SECOND": "${MISSING_B}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.var_name == "FIRST"

    async def test_no_recursion_in_env_machine_value(
        self, mock_get_machine_by_name, mock_resolve_for_named_machine,
    ) -> None:
        # Si la value sur la machine cible contient un ${...}, on renvoie brut (pas de récursion)
        from types import SimpleNamespace
        mock_get_machine_by_name.return_value = SimpleNamespace(id=uuid4(), name="m1")
        mock_resolve_for_named_machine.return_value = {"VAR": "literal-${OTHER}-value"}
        result = await resolve_input_values(
            input_values={"X": "${env-machine://m1:VAR}"},
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={},
        )
        assert result == {"X": "literal-${OTHER}-value"}
```

- [x] **Step 3 : Run tests — fails (resolve_input_values undefined)**

Run: `cd backend && uv run pytest tests/services/test_input_resolver.py -v`
Expected: FAIL with ImportError on `resolve_input_values`

- [x] **Step 4 : Implémenter `resolve_input_values` (fail-fast)**

Ajouter à `backend/src/agflow/services/input_resolver.py` (après `UnresolvedPlaceholderError`) :

```python
from uuid import UUID

import structlog

from agflow.services import infra_env_vars_service, infra_machines_service
from agflow.services.placeholder_parsers import (
    ENV_MACHINE_RE,
    ENV_REF_RE,
    SIMPLE_VAR_RE,
    UNKNOWN_BRACE_RE,
    VAULT_REF_RE,
    parse_env_text,
)

_log = structlog.get_logger(__name__)


async def resolve_input_values(
    input_values: dict[str, str],
    *,
    target_machine_id: UUID,
    env_text: str,
    platform_secrets_map: dict[str, str],
) -> dict[str, str]:
    """Résout les input_values d'un group_script (fail-fast).

    Lève UnresolvedPlaceholderError dès la 1ère valeur non résoluble.
    Utilisé par les chemins d'exécution (deployment_executor, project_deployments).
    """
    env_map = parse_env_text(env_text)
    env_machine_cache: dict[str, dict[str, str]] = {}

    resolved: dict[str, str] = {}
    for var_name, raw in input_values.items():
        resolved[var_name] = await _resolve_single(
            var_name=var_name,
            raw=raw,
            env_map=env_map,
            platform_secrets_map=platform_secrets_map,
            env_machine_cache=env_machine_cache,
        )
    return resolved


async def _resolve_single(
    *,
    var_name: str,
    raw: str,
    env_map: dict[str, str],
    platform_secrets_map: dict[str, str],
    env_machine_cache: dict[str, dict[str, str]],
) -> str:
    value = raw or ""
    if not value.strip():
        raise UnresolvedPlaceholderError(
            kind="value_empty",
            ref="",
            detail=f"valeur vide pour '{var_name}'",
            var_name=var_name,
        )

    # Étape 1 — env-machine://
    value = await _substitute_env_machine(value, var_name, env_machine_cache)
    # Étape 2 — vault://
    value = _substitute_vault(value, var_name, platform_secrets_map)
    # Étape 3 — env://
    value = _substitute_env_ref(value, var_name, platform_secrets_map)
    # Étape 4 — ${VAR}
    value = _substitute_simple_var(value, var_name, env_map)
    # Étape 5 — détection de ${...} résiduel non reconnu
    leftover = UNKNOWN_BRACE_RE.search(value)
    if leftover:
        raise UnresolvedPlaceholderError(
            kind="unknown_ref",
            ref=leftover.group(0),
            detail=f"référence non reconnue '{leftover.group(1)}' dans '{var_name}'",
            var_name=var_name,
        )

    return value


async def _substitute_env_machine(
    value: str,
    var_name: str,
    cache: dict[str, dict[str, str]],
) -> str:
    """Remplace toutes les refs ${env-machine://m:V} dans value."""
    out = value
    for m in list(ENV_MACHINE_RE.finditer(value)):
        machine_name, ref_var = m.group(1), m.group(2)
        if machine_name not in cache:
            machine = await infra_machines_service.get_by_name(machine_name)
            if machine is None:
                raise UnresolvedPlaceholderError(
                    kind="machine_not_found",
                    ref=m.group(0),
                    detail=f"machine '{machine_name}' inconnue",
                    var_name=var_name,
                )
            cache[machine_name] = await infra_env_vars_service.resolve_for_machine(machine.id)

        env_vars = cache[machine_name]
        if ref_var not in env_vars:
            raise UnresolvedPlaceholderError(
                kind="env_machine_var_not_found",
                ref=m.group(0),
                detail=f"variable '{ref_var}' absente sur la machine '{machine_name}'",
                var_name=var_name,
            )
        if not env_vars[ref_var]:
            raise UnresolvedPlaceholderError(
                kind="env_machine_var_empty",
                ref=m.group(0),
                detail=f"variable '{ref_var}' vide sur la machine '{machine_name}'",
                var_name=var_name,
            )
        out = out.replace(m.group(0), env_vars[ref_var])
    return out


def _substitute_vault(value: str, var_name: str, secrets: dict[str, str]) -> str:
    out = value
    for m in list(VAULT_REF_RE.finditer(value)):
        name = m.group(1)
        secret = secrets.get(name)
        if not secret:
            raise UnresolvedPlaceholderError(
                kind="platform_secret_missing",
                ref=m.group(0),
                detail=f"secret '{name}' introuvable dans le coffre",
                var_name=var_name,
            )
        out = out.replace(m.group(0), secret)
    return out


def _substitute_env_ref(value: str, var_name: str, secrets: dict[str, str]) -> str:
    out = value
    for m in list(ENV_REF_RE.finditer(value)):
        name = m.group(1)
        secret = secrets.get(name)
        if not secret:
            raise UnresolvedPlaceholderError(
                kind="platform_secret_missing",
                ref=m.group(0),
                detail=f"variable globale '{name}' introuvable",
                var_name=var_name,
            )
        out = out.replace(m.group(0), secret)
    return out


def _substitute_simple_var(value: str, var_name: str, env_map: dict[str, str]) -> str:
    out = value
    for m in list(SIMPLE_VAR_RE.finditer(value)):
        name = m.group(1) or m.group(2)
        if name is None:
            continue
        env_val = env_map.get(name)
        if not env_val:
            raise UnresolvedPlaceholderError(
                kind="var_not_in_env",
                ref=m.group(0),
                detail=f"variable '{name}' introuvable dans le .env",
                var_name=var_name,
            )
        out = out.replace(m.group(0), env_val)
    return out
```

- [x] **Step 5 : Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/services/test_input_resolver.py -v`
Expected: PASS — toutes les classes TestResolveInputValues* doivent être vertes (16 tests)

- [x] **Step 6 : Lint + format**

Run: `cd backend && uv run ruff check src/agflow/services/input_resolver.py tests/services/test_input_resolver.py && uv run ruff format src/agflow/services/input_resolver.py tests/services/test_input_resolver.py`
Expected: no errors

- [x] **Step 7 : Commit**

```bash
git add backend/src/agflow/services/input_resolver.py backend/tests/services/test_input_resolver.py
git commit -m "feat(resolver): resolve_input_values fail-fast — 4 syntaxes + 7 kinds d'erreur"
```

---

## Task 4 : `resolve_input_values_collect` — résolution collect-all pour le check

**Files:**
- Modify: `backend/src/agflow/services/input_resolver.py`
- Modify: `backend/tests/services/test_input_resolver.py`

- [x] **Step 1 : Écrire les tests rouges**

Ajouter à `backend/tests/services/test_input_resolver.py` :

```python
from agflow.services.input_resolver import resolve_input_values_collect


class TestResolveInputValuesCollect:
    async def test_returns_resolved_and_errors(self, mock_resolve_for_machine) -> None:
        resolved, errors = await resolve_input_values_collect(
            input_values={
                "OK": "${HOST}",
                "KO1": "${MISSING}",
                "KO2": "",
            },
            target_machine_id=MACHINE_ID,
            env_text="HOST=example.com",
            platform_secrets_map={},
        )
        assert resolved == {"OK": "example.com"}
        kinds = sorted([(e.var_name, e.kind) for e in errors])
        assert kinds == [("KO1", "var_not_in_env"), ("KO2", "value_empty")]

    async def test_empty_inputs(self, mock_resolve_for_machine) -> None:
        resolved, errors = await resolve_input_values_collect(
            input_values={},
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={},
        )
        assert resolved == {}
        assert errors == []

    async def test_all_errors_collected(self, mock_resolve_for_machine) -> None:
        resolved, errors = await resolve_input_values_collect(
            input_values={
                "A": "${env://NO_A}",
                "B": "${vault://api:NO_B}",
                "C": "${MISSING}",
            },
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={},
        )
        assert resolved == {}
        assert len(errors) == 3
        kinds = {e.var_name: e.kind for e in errors}
        assert kinds == {
            "A": "platform_secret_missing",
            "B": "platform_secret_missing",
            "C": "var_not_in_env",
        }
```

- [x] **Step 2 : Run tests — fails (function undefined)**

Run: `cd backend && uv run pytest tests/services/test_input_resolver.py::TestResolveInputValuesCollect -v`
Expected: FAIL with ImportError

- [x] **Step 3 : Implémenter `resolve_input_values_collect`**

Ajouter à `backend/src/agflow/services/input_resolver.py` :

```python
async def resolve_input_values_collect(
    input_values: dict[str, str],
    *,
    target_machine_id: UUID,
    env_text: str,
    platform_secrets_map: dict[str, str],
) -> tuple[dict[str, str], list[UnresolvedPlaceholderError]]:
    """Résolution collect-all : accumule les erreurs au lieu de lever.

    Utilisée par check_project_env_vars pour rapporter TOUTES les
    variables non résolubles dans une seule réponse API.
    """
    env_map = parse_env_text(env_text)
    env_machine_cache: dict[str, dict[str, str]] = {}

    resolved: dict[str, str] = {}
    errors: list[UnresolvedPlaceholderError] = []
    for var_name, raw in input_values.items():
        try:
            resolved[var_name] = await _resolve_single(
                var_name=var_name,
                raw=raw,
                env_map=env_map,
                platform_secrets_map=platform_secrets_map,
                env_machine_cache=env_machine_cache,
            )
        except UnresolvedPlaceholderError as exc:
            errors.append(exc)
    return resolved, errors
```

- [x] **Step 4 : Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/services/test_input_resolver.py -v`
Expected: PASS — toute la suite (~19 tests)

- [x] **Step 5 : Lint + format**

Run: `cd backend && uv run ruff check src/agflow/services/input_resolver.py && uv run ruff format src/agflow/services/input_resolver.py`
Expected: no errors

- [x] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/input_resolver.py backend/tests/services/test_input_resolver.py
git commit -m "feat(resolver): resolve_input_values_collect — variante collect-all pour le check"
```

---

## Task 5 : Vérifier la présence de `infra_machines_service.get_by_name`

**Why:** `input_resolver` dépend de cette fonction. Si elle n'existe pas, l'ajouter ou adapter.

- [x] **Step 1 : Vérifier l'existence**

Run: `cd backend && uv run python -c "from agflow.services import infra_machines_service; print(hasattr(infra_machines_service, 'get_by_name'))"`
Expected: `True` ou `False`.

- [x] **Step 2 (si False) : Écrire le test rouge**

Ajouter à `backend/tests/services/test_infra_machines_service.py` (créer le fichier si absent) :

```python
import uuid
import pytest

from agflow.db.pool import execute
from agflow.services import infra_machines_service as svc
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db():
    await reset_schema_and_migrate()
    yield


async def test_get_by_name_returns_machine(fresh_db) -> None:
    await execute(
        "INSERT INTO infra_categories (name) VALUES ('test-cat') "
        "ON CONFLICT DO NOTHING",
    )
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'test-cat', 'SSH')",
        nt_id,
    )
    m_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'lookup-target', $2, '127.0.0.1', 22)",
        m_id, nt_id,
    )

    result = await svc.get_by_name("lookup-target")
    assert result is not None
    assert result.id == m_id
    assert result.name == "lookup-target"


async def test_get_by_name_returns_none_for_unknown(fresh_db) -> None:
    assert await svc.get_by_name("does-not-exist") is None
```

- [x] **Step 3 (si False) : Implémenter `get_by_name`**

Localiser `infra_machines_service.get_by_id` dans `backend/src/agflow/services/infra_machines_service.py`, ajouter en dessous :

```python
async def get_by_name(name: str):
    """Retourne la machine par son nom (unique), ou None si absente."""
    row = await fetch_one(
        "SELECT * FROM infra_machines WHERE name = $1",
        name,
    )
    return _row_to_machine(row) if row else None
```

(Le helper `_row_to_machine` doit déjà exister pour `get_by_id` — sinon adapter.)

- [x] **Step 4 (si False) : Run + commit**

Run: `cd backend && uv run pytest tests/services/test_infra_machines_service.py::test_get_by_name_returns_machine tests/services/test_infra_machines_service.py::test_get_by_name_returns_none_for_unknown -v`
Expected: PASS

```bash
git add backend/src/agflow/services/infra_machines_service.py backend/tests/services/test_infra_machines_service.py
git commit -m "feat(infra): infra_machines_service.get_by_name — lookup par nom unique"
```

- [x] **Step 5 (si True) : Skip — passer à Task 6**

---

## Task 6 : Migration de `_run_script_streaming` (deployment_executor.py)

**Files:**
- Modify: `backend/src/agflow/services/deployment_executor.py:46-62`
- Modify: `backend/tests/test_deployment_executor.py`

- [x] **Step 1 : Écrire le test rouge — step échoue si placeholder KO**

Ajouter à `backend/tests/test_deployment_executor.py` :

```python
from unittest.mock import AsyncMock, patch

from agflow.services.input_resolver import UnresolvedPlaceholderError


async def test_run_script_streaming_fails_on_unresolved_placeholder(monkeypatch) -> None:
    """Si input_resolver lève, le streaming échoue AVANT l'upload SSH."""
    from agflow.services import deployment_executor

    # Setup minimal link (SimpleNamespace pour ressembler à GroupScriptRow)
    from types import SimpleNamespace
    from uuid import uuid4
    link = SimpleNamespace(
        id=uuid4(),
        input_values={"PWD": "${env-machine://ghost:VAR}"},
        script_name="dummy",
        machine_name="target",
        timing="before",
    )

    captured_lines: list[tuple[str, str]] = []
    async def on_line(stream: str, line: str) -> None:
        captured_lines.append((stream, line))

    with (
        patch(
            "agflow.services.deployment_executor.group_scripts_service.resolve_target_machine_id",
            new_callable=AsyncMock, return_value=uuid4(),
        ),
        patch(
            "agflow.services.deployment_executor.ssh_kwargs_for_machine",
            new_callable=AsyncMock, return_value={},
        ),
        patch(
            "agflow.services.deployment_executor.platform_secrets_service.resolve_all",
            new_callable=AsyncMock, return_value={},
        ),
        patch(
            "agflow.services.deployment_executor.input_resolver.resolve_input_values",
            new_callable=AsyncMock,
            side_effect=UnresolvedPlaceholderError(
                kind="machine_not_found",
                ref="${env-machine://ghost:VAR}",
                detail="machine 'ghost' inconnue",
                var_name="PWD",
            ),
        ),
        patch(
            "agflow.services.deployment_executor.ssh_executor.exec_command",
            new_callable=AsyncMock,
        ) as mock_exec,
    ):
        result = await deployment_executor._run_script_streaming(
            link=link, script_content="echo {PWD}", env_text="", on_line=on_line,
        )

    assert result["success"] is False
    assert result["exit_code"] == -1
    assert "PWD" in result["stderr"]
    assert "ghost" in result["stderr"]
    # Aucun exec_command appelé : on a fail avant l'upload
    mock_exec.assert_not_called()
    # Le stderr a été propagé via on_line
    assert any(s == "stderr" and "ghost" in line for s, line in captured_lines)
```

- [x] **Step 2 : Run test — fails (import resolve_input_value, behavior incorrect)**

Run: `cd backend && uv run pytest tests/test_deployment_executor.py::test_run_script_streaming_fails_on_unresolved_placeholder -v`
Expected: FAIL (either import error or wrong behavior — `ssh_executor.exec_command` est appelé)

- [x] **Step 3 : Migrer `_run_script_streaming`**

Dans `backend/src/agflow/services/deployment_executor.py` :

Remplacer ligne 19-28 (import) :

```python
from agflow.services.deployment_env_helpers import (
    collect_env_from_script,
    evaluate_trigger_rules,
    merge_env_with_values,
    parse_env_map,
    parse_last_json,
    resolve_input_value,
    ssh_kwargs_for_machine,
    substitute_script_placeholders,
)
```

Par :

```python
from agflow.services import input_resolver
from agflow.services.deployment_env_helpers import (
    collect_env_from_script,
    evaluate_trigger_rules,
    merge_env_with_values,
    parse_env_map,
    parse_last_json,
    ssh_kwargs_for_machine,
    substitute_script_placeholders,
)
from agflow.services.input_resolver import UnresolvedPlaceholderError
```

Remplacer ligne 55-60 :

```python
    platform_secrets_map = await platform_secrets_service.resolve_all()
    resolved_inputs: dict[str, str] = {}
    for name, raw in (link.input_values or {}).items():
        step1 = platform_secrets_service.resolve_platform_refs(raw or "", platform_secrets_map)
        resolved, _ = resolve_input_value(step1, env_text)
        resolved_inputs[name] = resolved
```

Par :

```python
    platform_secrets_map = await platform_secrets_service.resolve_all()
    try:
        resolved_inputs = await input_resolver.resolve_input_values(
            input_values=link.input_values or {},
            target_machine_id=target_machine_id,
            env_text=env_text,
            platform_secrets_map=platform_secrets_map,
        )
    except UnresolvedPlaceholderError as exc:
        msg = f"Variable '{exc.var_name}' non résoluble : {exc.detail}"
        _log.warning(
            "deployment_executor.unresolved_placeholder",
            var_name=exc.var_name, kind=exc.kind, ref=exc.ref,
        )
        await on_line("stderr", msg)
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": msg}
```

- [x] **Step 4 : Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_deployment_executor.py -v`
Expected: PASS — y compris les tests existants (régression check)

- [x] **Step 5 : Lint + format**

Run: `cd backend && uv run ruff check src/agflow/services/deployment_executor.py && uv run ruff format src/agflow/services/deployment_executor.py`
Expected: no errors

- [x] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/deployment_executor.py backend/tests/test_deployment_executor.py
git commit -m "feat(deployment): _run_script_streaming utilise input_resolver — fail-fast"
```

---

## Task 7 : Migration de `_run_group_script` (project_deployments.py)

**Files:**
- Modify: `backend/src/agflow/api/admin/project_deployments.py:297-336`
- Modify: tests existants si applicable

- [x] **Step 1 : Écrire le test rouge**

Ajouter à `backend/tests/api/admin/test_project_deployments.py` (créer si absent), ou à un fichier de tests existant qui couvre `_run_group_script` :

```python
async def test_run_group_script_fails_on_unresolved_placeholder() -> None:
    """_run_group_script échoue proprement si input_resolver lève."""
    from unittest.mock import AsyncMock, patch
    from types import SimpleNamespace
    from uuid import uuid4

    from agflow.api.admin import project_deployments

    link = SimpleNamespace(
        id=uuid4(),
        input_values={"X": "${env-machine://ghost:Y}"},
        script_name="dummy", machine_name="target", timing="before",
        position=0,
    )

    with (
        patch(
            "agflow.api.admin.project_deployments.group_scripts_service.resolve_target_machine_id",
            new_callable=AsyncMock, return_value=uuid4(),
        ),
        patch(
            "agflow.api.admin.project_deployments._ssh_kwargs_for_machine",
            new_callable=AsyncMock, return_value={},
        ),
        patch(
            "agflow.api.admin.project_deployments.platform_secrets_service.resolve_all",
            new_callable=AsyncMock, return_value={},
        ),
        patch(
            "agflow.api.admin.project_deployments.input_resolver.resolve_input_values",
            new_callable=AsyncMock,
            side_effect=__import__(
                "agflow.services.input_resolver", fromlist=["UnresolvedPlaceholderError"],
            ).UnresolvedPlaceholderError(
                kind="machine_not_found",
                ref="${env-machine://ghost:Y}",
                detail="machine 'ghost' inconnue",
                var_name="X",
            ),
        ),
        patch(
            "agflow.api.admin.project_deployments.ssh_executor.exec_command",
            new_callable=AsyncMock,
        ) as mock_exec,
    ):
        result = await project_deployments._run_group_script(link, "echo {X}", env_text="")

    assert result["success"] is False
    assert "X" in result["error"]
    assert "ghost" in result["error"]
    mock_exec.assert_not_called()
```

- [x] **Step 2 : Run test — fails**

Run: `cd backend && uv run pytest tests/api/admin/test_project_deployments.py::test_run_group_script_fails_on_unresolved_placeholder -v`
Expected: FAIL

- [x] **Step 3 : Migrer `_run_group_script`**

Dans `backend/src/agflow/api/admin/project_deployments.py` :

Ajouter en haut (à côté des autres imports services) :

```python
from agflow.services import input_resolver
from agflow.services.input_resolver import UnresolvedPlaceholderError
```

Retirer `resolve_input_value as _resolve_input_value` de l'import lignes 57-58.

Remplacer lignes 319-334 (la double boucle de résolution) :

```python
    # Résolution en 2 étapes pour chaque input_value :
    #   1) ${vault://api:path} et ${env://NAME} → via platform_secrets_service
    #      (qui fait l'appel SDK Harpocrate + lecture table env globale)
    #   2) ${SIMPLE_NAME} → contre le .env du déploiement (qui contient
    #      maintenant les variables de groupe injectées au Generate)
    from agflow.services import platform_secrets_service
    platform_secrets_map = await platform_secrets_service.resolve_all()
    resolved_inputs: dict[str, str] = {}
    for name, raw in (link.input_values or {}).items():
        # Étape 1 : résoudre les refs déclaratives ${vault://…} / ${env://…}
        step1 = platform_secrets_service.resolve_platform_refs(
            raw or "", platform_secrets_map,
        )
        # Étape 2 : résoudre les ${VAR} simples contre le .env
        resolved, _ok = _resolve_input_value(step1, env_text)
        resolved_inputs[name] = resolved
```

Par :

```python
    # Résolution unifiée des 4 syntaxes via input_resolver (fail-fast)
    from agflow.services import platform_secrets_service
    platform_secrets_map = await platform_secrets_service.resolve_all()
    try:
        resolved_inputs = await input_resolver.resolve_input_values(
            input_values=link.input_values or {},
            target_machine_id=target_machine_id,
            env_text=env_text,
            platform_secrets_map=platform_secrets_map,
        )
    except UnresolvedPlaceholderError as exc:
        msg = f"Variable '{exc.var_name}' non résoluble : {exc.detail}"
        _log.warning(
            "group_script.unresolved_placeholder",
            var_name=exc.var_name, kind=exc.kind, ref=exc.ref,
        )
        return {
            "script": link.script_name, "machine": link.machine_name,
            "timing": link.timing, "success": False, "error": msg,
        }
```

- [x] **Step 4 : Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/admin/test_project_deployments.py -v`
Expected: PASS — y compris tests existants

- [x] **Step 5 : Lint + format**

Run: `cd backend && uv run ruff check src/agflow/api/admin/project_deployments.py && uv run ruff format src/agflow/api/admin/project_deployments.py`
Expected: no errors

- [x] **Step 6 : Commit**

```bash
git add backend/src/agflow/api/admin/project_deployments.py backend/tests/api/admin/test_project_deployments.py
git commit -m "feat(deployment): _run_group_script utilise input_resolver — fail-fast"
```

---

## Task 8 : Schémas API — `ProjectEnvVarsCheckMissingReason` (breaking)

**Files:**
- Modify: `backend/src/agflow/schemas/infra_env_vars.py:66-81`

- [x] **Step 1 : Écrire le test rouge — round-trip Pydantic**

Ajouter à `backend/tests/services/test_input_resolver.py` (ou créer `tests/schemas/test_infra_env_vars_schemas.py`) :

```python
def test_project_env_vars_check_missing_reason_round_trip() -> None:
    from uuid import uuid4
    from agflow.schemas.infra_env_vars import (
        ProjectEnvVarsCheckMissing,
        ProjectEnvVarsCheckMissingReason,
    )

    reason = ProjectEnvVarsCheckMissingReason(
        var_name="KC_ADMIN_PASSWORD",
        kind="machine_not_found",
        ref="${env-machine://keycloak1:KC_ADMIN_PASSWORD}",
        detail="machine 'keycloak1' inconnue",
    )
    item = ProjectEnvVarsCheckMissing(
        group_script_id=uuid4(), script_id=uuid4(),
        script_name="create-oidc-client",
        group_id=uuid4(), group_name="primary",
        machine_id=None, machine_name=None,
        target_kind="deployment_host",
        missing=[reason],
    )
    dumped = item.model_dump()
    assert dumped["missing"][0]["kind"] == "machine_not_found"
    assert dumped["missing"][0]["var_name"] == "KC_ADMIN_PASSWORD"
```

- [x] **Step 2 : Run test — fails**

Run: `cd backend && uv run pytest tests/services/test_input_resolver.py::test_project_env_vars_check_missing_reason_round_trip -v`
Expected: FAIL with ImportError on `ProjectEnvVarsCheckMissingReason`

- [x] **Step 3 : Modifier le schéma**

Dans `backend/src/agflow/schemas/infra_env_vars.py:66-81`, remplacer :

```python
class ProjectEnvVarsCheckMissing(BaseModel):
    group_script_id: UUID
    script_id: UUID
    script_name: str
    group_id: UUID
    group_name: str
    machine_id: UUID | None
    machine_name: str | None
    target_kind: str
    missing_env_vars: list[str]


class ProjectEnvVarsCheck(BaseModel):
    project_id: UUID
    total_missing: int
    items: list[ProjectEnvVarsCheckMissing]
```

Par :

```python
class ProjectEnvVarsCheckMissingReason(BaseModel):
    """Une raison pour laquelle une variable d'input ne peut être résolue.

    `kind` correspond aux UnresolvedKind d'input_resolver.
    """
    var_name: str
    kind: Literal[
        "value_empty",
        "var_not_in_env",
        "platform_secret_missing",
        "machine_not_found",
        "env_machine_var_not_found",
        "env_machine_var_empty",
        "unknown_ref",
    ]
    ref: str
    detail: str


class ProjectEnvVarsCheckMissing(BaseModel):
    group_script_id: UUID
    script_id: UUID
    script_name: str
    group_id: UUID
    group_name: str
    machine_id: UUID | None
    machine_name: str | None
    target_kind: str
    missing: list[ProjectEnvVarsCheckMissingReason]


class ProjectEnvVarsCheck(BaseModel):
    project_id: UUID
    total_missing: int
    items: list[ProjectEnvVarsCheckMissing]
```

Ajouter l'import `Literal` en haut du fichier si absent :

```python
from typing import Literal
```

- [x] **Step 4 : Run test to verify it passes**

Run: `cd backend && uv run pytest tests/services/test_input_resolver.py::test_project_env_vars_check_missing_reason_round_trip -v`
Expected: PASS

- [x] **Step 5 : Run all backend tests — quels tests sont cassés par le breaking change ?**

Run: `cd backend && uv run pytest -v 2>&1 | tail -50`
Expected: certains tests vont casser sur `missing_env_vars` — c'est normal, on les fixe au Task 9.

**Ne pas committer maintenant** — on commit avec la refonte de `check_project_env_vars` au Task 9 pour garder le repo cohérent.

---

## Task 9 : Refonte de `check_project_env_vars`

**Files:**
- Modify: `backend/src/agflow/services/infra_env_vars_service.py:286-352`
- Create: `backend/tests/services/test_check_project_env_vars.py`

- [x] **Step 1 : Écrire les tests rouges (intégration, DB réelle)**

Créer `backend/tests/services/test_check_project_env_vars.py` :

```python
# backend/tests/services/test_check_project_env_vars.py
"""Tests d'intégration de check_project_env_vars (DB réelle)."""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.services import infra_env_vars_service as svc
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[None]:
    await reset_schema_and_migrate()
    yield


async def _seed_minimal_project_with_via_env_script(*, input_value: str) -> dict:
    """Crée un projet + groupe + group_script avec UNE variable via_env qui pointe sur `input_value`.

    Retourne les IDs créés pour assertions.
    """
    # Catégorie + named_type + machine
    await execute("INSERT INTO infra_categories (name) VALUES ('cat') ON CONFLICT DO NOTHING")
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'cat', 'SSH')",
        nt_id,
    )
    m_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'machine-target', $2, '127.0.0.1', 22)",
        m_id, nt_id,
    )

    # Projet + groupe
    p_id = uuid.uuid4()
    await execute(
        "INSERT INTO projects (id, display_name) VALUES ($1, 'proj-test')",
        p_id,
    )
    g_id = uuid.uuid4()
    await execute(
        "INSERT INTO groups (id, project_id, name, max_agents, max_replicas, machine_id) "
        "VALUES ($1, $2, 'primary', 1, 1, $3)",
        g_id, p_id, m_id,
    )

    # Script avec input via_env
    s_id = uuid.uuid4()
    input_vars = [
        {"name": "KC_ADMIN_PASSWORD", "description": "", "default": "", "via_env": True},
    ]
    await execute(
        "INSERT INTO scripts (id, name, description, content, input_variables) "
        "VALUES ($1, 'create-oidc-client', '', 'echo {KC_ADMIN_PASSWORD}', $2)",
        s_id, json.dumps(input_vars),
    )

    # group_script reliant le tout, input_values = {KC_ADMIN_PASSWORD: input_value}
    gs_id = uuid.uuid4()
    await execute(
        "INSERT INTO group_scripts (id, group_id, script_id, position, timing, "
        "target_kind, machine_id, input_values) "
        "VALUES ($1, $2, $3, 0, 'before', 'fixed_machine', $4, $5)",
        gs_id, g_id, s_id, m_id, json.dumps({"KC_ADMIN_PASSWORD": input_value}),
    )
    return {"project_id": p_id, "group_id": g_id, "script_id": s_id, "gs_id": gs_id, "machine_id": m_id}


async def test_check_returns_no_missing_when_input_value_is_env_machine_ref(fresh_db) -> None:
    """Le bug fixé : ${env-machine://X:VAR} doit être reconnu comme couvrant la variable."""
    # Setup : machine X = keycloak1, variable KC_ADMIN_PASSWORD avec value non-vide
    await execute("INSERT INTO infra_categories (name) VALUES ('cat-kc') ON CONFLICT DO NOTHING")
    nt_kc = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'cat-kc', 'SSH')",
        nt_kc,
    )
    kc_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'keycloak1', $2, '127.0.0.1', 22)",
        kc_id, nt_kc,
    )
    # Variable d'env déclarée sur le named_type + valeur sur la machine
    ev_id = uuid.uuid4()
    await execute(
        "INSERT INTO named_type_env_vars (id, named_type_id, name) "
        "VALUES ($1, $2, 'KC_ADMIN_PASSWORD')",
        ev_id, nt_kc,
    )
    await execute(
        "INSERT INTO infra_machine_env_vars (machine_id, named_type_env_var_id, value) "
        "VALUES ($1, $2, 's3cret')",
        kc_id, ev_id,
    )

    seed = await _seed_minimal_project_with_via_env_script(
        input_value="${env-machine://keycloak1:KC_ADMIN_PASSWORD}",
    )

    result = await svc.check_project_env_vars(seed["project_id"])

    assert result.total_missing == 0
    assert result.items == []


async def test_check_reports_machine_not_found(fresh_db) -> None:
    seed = await _seed_minimal_project_with_via_env_script(
        input_value="${env-machine://ghost-machine:KC_ADMIN_PASSWORD}",
    )

    result = await svc.check_project_env_vars(seed["project_id"])

    assert result.total_missing == 1
    assert len(result.items) == 1
    item = result.items[0]
    assert len(item.missing) == 1
    assert item.missing[0].kind == "machine_not_found"
    assert item.missing[0].var_name == "KC_ADMIN_PASSWORD"
    assert "ghost-machine" in item.missing[0].detail


async def test_check_reports_empty_value(fresh_db) -> None:
    seed = await _seed_minimal_project_with_via_env_script(input_value="")

    result = await svc.check_project_env_vars(seed["project_id"])

    assert result.total_missing == 1
    assert result.items[0].missing[0].kind == "value_empty"


async def test_check_skips_scripts_without_via_env(fresh_db) -> None:
    """Si toutes les inputs sont via_env=false, le script est ignoré."""
    # Setup similaire mais via_env=False
    await execute("INSERT INTO infra_categories (name) VALUES ('cat') ON CONFLICT DO NOTHING")
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'cat', 'SSH')",
        nt_id,
    )
    m_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'm', $2, '127.0.0.1', 22)",
        m_id, nt_id,
    )
    p_id = uuid.uuid4()
    await execute("INSERT INTO projects (id, display_name) VALUES ($1, 'p')", p_id)
    g_id = uuid.uuid4()
    await execute(
        "INSERT INTO groups (id, project_id, name, max_agents, max_replicas, machine_id) "
        "VALUES ($1, $2, 'g', 1, 1, $3)",
        g_id, p_id, m_id,
    )
    s_id = uuid.uuid4()
    await execute(
        "INSERT INTO scripts (id, name, description, content, input_variables) "
        "VALUES ($1, 's', '', '', $2)",
        s_id, json.dumps([{"name": "X", "via_env": False, "default": "", "description": ""}]),
    )
    gs_id = uuid.uuid4()
    await execute(
        "INSERT INTO group_scripts (id, group_id, script_id, position, timing, "
        "target_kind, machine_id, input_values) "
        "VALUES ($1, $2, $3, 0, 'before', 'fixed_machine', $4, $5)",
        gs_id, g_id, s_id, m_id, json.dumps({"X": ""}),
    )

    result = await svc.check_project_env_vars(p_id)
    assert result.total_missing == 0


async def test_check_aggregates_multiple_reasons_in_one_script(fresh_db) -> None:
    """Un script avec 2 via_env, l'une OK et l'autre KO, doit lister UNE raison."""
    # Setup : 2 input_variables via_env, l'une avec value="ok" littéral, l'autre vide
    await execute("INSERT INTO infra_categories (name) VALUES ('cat') ON CONFLICT DO NOTHING")
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'cat', 'SSH')",
        nt_id,
    )
    m_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'm', $2, '127.0.0.1', 22)",
        m_id, nt_id,
    )
    p_id = uuid.uuid4()
    await execute("INSERT INTO projects (id, display_name) VALUES ($1, 'p')", p_id)
    g_id = uuid.uuid4()
    await execute(
        "INSERT INTO groups (id, project_id, name, max_agents, max_replicas, machine_id) "
        "VALUES ($1, $2, 'g', 1, 1, $3)",
        g_id, p_id, m_id,
    )
    s_id = uuid.uuid4()
    inputs = [
        {"name": "OK_VAR", "via_env": True, "default": "", "description": ""},
        {"name": "KO_VAR", "via_env": True, "default": "", "description": ""},
    ]
    await execute(
        "INSERT INTO scripts (id, name, description, content, input_variables) "
        "VALUES ($1, 's', '', '', $2)",
        s_id, json.dumps(inputs),
    )
    gs_id = uuid.uuid4()
    await execute(
        "INSERT INTO group_scripts (id, group_id, script_id, position, timing, "
        "target_kind, machine_id, input_values) "
        "VALUES ($1, $2, $3, 0, 'before', 'fixed_machine', $4, $5)",
        gs_id, g_id, s_id, m_id, json.dumps({"OK_VAR": "literal-ok", "KO_VAR": ""}),
    )

    result = await svc.check_project_env_vars(p_id)
    assert result.total_missing == 1
    assert len(result.items) == 1
    assert len(result.items[0].missing) == 1
    assert result.items[0].missing[0].var_name == "KO_VAR"
    assert result.items[0].missing[0].kind == "value_empty"
```

- [x] **Step 2 : Run tests — fails**

Run: `cd backend && uv run pytest tests/services/test_check_project_env_vars.py -v`
Expected: FAIL — tous les tests, car `check_project_env_vars` retourne encore `missing_env_vars`

- [x] **Step 3 : Refondre `check_project_env_vars`**

Dans `backend/src/agflow/services/infra_env_vars_service.py:286-352`, remplacer toute la fonction `check_project_env_vars` :

```python
async def check_project_env_vars(project_id: UUID) -> ProjectEnvVarsCheck:
    """Pour chaque group_script avec via_env, dry-run du resolver et rapport.

    Utilise input_resolver.resolve_input_values_collect : on n'arrête pas
    au 1er échec, on accumule toutes les raisons.

    Une via_env var dont l'input_value se résout (ou est couverte par la
    machine cible / les group_variables) → absente de `missing`.
    Sinon → entrée dans `missing` avec le `kind` typé.
    """
    from agflow.services import (
        group_scripts_service,
        group_variables_service,
        groups_service,
        input_resolver,
        platform_secrets_service,
        scripts_service,
    )
    from agflow.schemas.infra_env_vars import ProjectEnvVarsCheckMissingReason

    groups = await groups_service.list_by_project(project_id)
    platform_secrets_map = await platform_secrets_service.resolve_all()
    items: list[ProjectEnvVarsCheckMissing] = []

    for group in groups:
        group_vars = await group_variables_service.list_by_group(group.id)
        env_text = "\n".join(
            f"{v.name}={v.value}" for v in group_vars if v.value
        )
        group_var_names = {v.name for v in group_vars if v.value}

        group_scripts = await group_scripts_service.list_by_group(group.id)
        for gs in group_scripts:
            script = await scripts_service.get_by_id(gs.script_id)
            via_env_vars = [v for v in script.input_variables if v.via_env]
            if not via_env_vars:
                continue

            # Résoudre la machine cible (cf. logique existante)
            machine_id: UUID | None = None
            machine_name: str | None = gs.machine_name or None
            if gs.target_kind == "fixed_machine" and gs.machine_id:
                machine_id = gs.machine_id
            elif gs.target_kind == "deployment_host":
                try:
                    machine_id = await group_scripts_service.resolve_target_machine_id(gs.id)
                except Exception as exc:
                    _log.debug(
                        "infra_env_vars.check.skip_group_script",
                        gs_id=str(gs.id), reason=str(exc),
                    )
                    continue
            if machine_id is None:
                continue

            # Dry-run du resolver — restreint aux input_values des via_env vars
            via_env_names = {v.name for v in via_env_vars}
            relevant_inputs = {
                k: v for k, v in (gs.input_values or {}).items()
                if k in via_env_names
            }
            # Inputs absents : on les considère comme value_empty
            for v in via_env_vars:
                if v.name not in relevant_inputs:
                    relevant_inputs[v.name] = ""

            _, errors = await input_resolver.resolve_input_values_collect(
                input_values=relevant_inputs,
                target_machine_id=machine_id,
                env_text=env_text,
                platform_secrets_map=platform_secrets_map,
            )

            # Si une via_env var est aussi définie au niveau du groupe (group_var
            # non vide), on l'élimine du rapport — elle sera injectée au deploy.
            reasons: list[ProjectEnvVarsCheckMissingReason] = [
                ProjectEnvVarsCheckMissingReason(
                    var_name=err.var_name or "<unknown>",
                    kind=err.kind,
                    ref=err.ref,
                    detail=err.detail,
                )
                for err in errors
                if (err.var_name or "") not in group_var_names
            ]
            if reasons:
                items.append(ProjectEnvVarsCheckMissing(
                    group_script_id=gs.id,
                    script_id=script.id,
                    script_name=script.name,
                    group_id=group.id,
                    group_name=group.name,
                    machine_id=machine_id,
                    machine_name=machine_name,
                    target_kind=gs.target_kind,
                    missing=reasons,
                ))

    return ProjectEnvVarsCheck(
        project_id=project_id,
        total_missing=sum(len(it.missing) for it in items),
        items=items,
    )
```

Ajouter l'import en tête du fichier si absent :

```python
from agflow.schemas.infra_env_vars import (
    ...,
    ProjectEnvVarsCheckMissingReason,
)
```

- [x] **Step 4 : Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/services/test_check_project_env_vars.py -v`
Expected: PASS — 5 tests verts

- [x] **Step 5 : Run all backend tests — vérifier qu'aucune régression ailleurs**

Run: `cd backend && uv run pytest -v 2>&1 | tail -30`
Expected: tous les tests verts (sauf ceux qui assertent encore `missing_env_vars` — à mettre à jour si présents)

S'il reste des tests cassés, les corriger pour utiliser `missing` au lieu de `missing_env_vars`.

- [x] **Step 6 : Lint + format**

Run: `cd backend && uv run ruff check src/agflow/services/infra_env_vars_service.py src/agflow/schemas/infra_env_vars.py tests/services/test_check_project_env_vars.py && uv run ruff format src/agflow/services/infra_env_vars_service.py src/agflow/schemas/infra_env_vars.py tests/services/test_check_project_env_vars.py`
Expected: no errors

- [x] **Step 7 : Commit**

```bash
git add backend/src/agflow/services/infra_env_vars_service.py backend/src/agflow/schemas/infra_env_vars.py backend/tests/services/test_check_project_env_vars.py
git commit -m "feat(check): check_project_env_vars utilise input_resolver — raisons typées"
```

---

## Task 10 : Frontend — types + bannière + i18n

**Files:**
- Modify: `frontend/src/lib/infraEnvVarsApi.ts:50-66`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx:193-211`
- Modify: `frontend/src/i18n/fr.json` (clé `projects.env_vars_*`)
- Modify: `frontend/src/i18n/en.json` (idem)

- [x] **Step 1 : Mettre à jour les types TS**

Dans `frontend/src/lib/infraEnvVarsApi.ts:50-60`, remplacer :

```ts
export interface ProjectEnvVarsCheckMissing {
  group_script_id: string;
  script_id: string;
  script_name: string;
  group_id: string;
  group_name: string;
  machine_id: string | null;
  machine_name: string | null;
  target_kind: string;
  missing_env_vars: string[];
}
```

Par :

```ts
export type EnvVarsMissingKind =
  | "value_empty"
  | "var_not_in_env"
  | "platform_secret_missing"
  | "machine_not_found"
  | "env_machine_var_not_found"
  | "env_machine_var_empty"
  | "unknown_ref";

export interface ProjectEnvVarsCheckMissingReason {
  var_name: string;
  kind: EnvVarsMissingKind;
  ref: string;
  detail: string;
}

export interface ProjectEnvVarsCheckMissing {
  group_script_id: string;
  script_id: string;
  script_name: string;
  group_id: string;
  group_name: string;
  machine_id: string | null;
  machine_name: string | null;
  target_kind: string;
  missing: ProjectEnvVarsCheckMissingReason[];
}
```

- [x] **Step 2 : Mettre à jour la bannière dans ProjectDetailPage**

Dans `frontend/src/pages/ProjectDetailPage.tsx:193-211`, remplacer :

```tsx
      {envVarsCheck.data && envVarsCheck.data.total_missing > 0 && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm">
          <p className="font-medium text-destructive">
            {t("projects.env_vars_missing_banner", { count: envVarsCheck.data.total_missing })}
          </p>
          <ul className="mt-2 space-y-1">
            {envVarsCheck.data.items.map((item) => (
              <li key={item.group_script_id} className="text-xs text-muted-foreground">
                <span className="font-mono">{item.script_name}</span>
                {" — "}
                {item.missing_env_vars.join(", ")}
                {" ("}
                {item.group_name}
                {")"}
              </li>
            ))}
          </ul>
        </div>
      )}
```

Par :

```tsx
      {envVarsCheck.data && envVarsCheck.data.total_missing > 0 && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm">
          <p className="font-medium text-destructive">
            {t("projects.env_vars_missing_banner", { count: envVarsCheck.data.total_missing })}
          </p>
          <ul className="mt-2 space-y-2">
            {envVarsCheck.data.items.map((item) => (
              <li key={item.group_script_id} className="text-xs">
                <div className="text-muted-foreground">
                  <span className="font-mono">{item.script_name}</span>
                  {" — "}
                  <span>{item.group_name}</span>
                </div>
                <ul className="ml-4 mt-0.5 space-y-0.5">
                  {item.missing.map((m) => (
                    <li key={m.var_name} className="text-muted-foreground">
                      <span className="font-mono">{m.var_name}</span>
                      {" : "}
                      <span>
                        {t(`projects.env_vars_reason.${m.kind}`, { detail: m.detail })}
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
```

- [x] **Step 3 : Mettre à jour les clés i18n FR**

Dans `frontend/src/i18n/fr.json`, dans la section `"projects"`, remplacer la ligne `"env_vars_missing_banner"` et ajouter le bloc `env_vars_reason` :

```json
    "env_vars_missing_banner": "{{count}} variable(s) d'environnement non résoluble(s) pour ce projet",
    "env_vars_reason": {
      "value_empty": "valeur vide",
      "var_not_in_env": "variable introuvable dans le .env : {{detail}}",
      "platform_secret_missing": "secret plateforme introuvable : {{detail}}",
      "machine_not_found": "machine inconnue : {{detail}}",
      "env_machine_var_not_found": "variable absente sur la machine : {{detail}}",
      "env_machine_var_empty": "variable vide sur la machine : {{detail}}",
      "unknown_ref": "référence non reconnue : {{detail}}"
    },
```

- [x] **Step 4 : Mettre à jour les clés i18n EN**

Dans `frontend/src/i18n/en.json`, miroir du précédent :

```json
    "env_vars_missing_banner": "{{count}} unresolved environment variable(s) for this project",
    "env_vars_reason": {
      "value_empty": "empty value",
      "var_not_in_env": "variable not found in .env: {{detail}}",
      "platform_secret_missing": "platform secret not found: {{detail}}",
      "machine_not_found": "unknown machine: {{detail}}",
      "env_machine_var_not_found": "variable absent on machine: {{detail}}",
      "env_machine_var_empty": "variable empty on machine: {{detail}}",
      "unknown_ref": "unrecognized reference: {{detail}}"
    },
```

- [x] **Step 5 : TS strict + lint**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

Run: `cd frontend && npm run lint`
Expected: no errors

- [x] **Step 6 : Tests frontend (Vitest)**

Run: `cd frontend && npm test -- --run`
Expected: PASS — y compris les tests existants de ProjectDetailPage s'ils existent. Si un test casse sur `missing_env_vars`, le mettre à jour pour utiliser le nouveau format.

- [x] **Step 7 : Commit**

```bash
git add frontend/src/lib/infraEnvVarsApi.ts frontend/src/pages/ProjectDetailPage.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(ui): bannière env-vars avec raisons typées par variable"
```

---

## Task 11 : Cleanup — suppression de `resolve_input_value` orpheline

**Files:**
- Modify: `backend/src/agflow/services/deployment_env_helpers.py:15-41`
- Modify: `backend/src/agflow/api/admin/project_deployments.py` (import)

- [x] **Step 1 : Vérifier qu'il n'y a plus aucun callsite**

Run grep via tool : `Grep pattern="resolve_input_value" path="E:\srcs\agflow.docker\backend"`
Expected: **0 hit** dans `src/` (sauf la définition elle-même). Si d'autres callsites apparaissent, les migrer d'abord vers `input_resolver`.

- [x] **Step 2 : Supprimer la fonction**

Dans `backend/src/agflow/services/deployment_env_helpers.py`, supprimer entièrement la fonction `resolve_input_value` (lignes 15-41 dans le fichier d'origine). Vérifier que les imports `re` restent utilisés ailleurs dans le fichier — si non, les retirer.

- [x] **Step 3 : Nettoyer l'import dans project_deployments.py**

Dans `backend/src/agflow/api/admin/project_deployments.py:57-58`, retirer :

```python
from agflow.services.deployment_env_helpers import (
    resolve_input_value as _resolve_input_value,
)
```

(garder les autres imports `deployment_env_helpers` si utilisés)

- [x] **Step 4 : Vérification finale par grep**

Run grep : `Grep pattern="resolve_input_value" path="E:\srcs\agflow.docker\backend"`
Expected: 0 hit dans `src/` ; vérifier qu'il n'y a pas de tests orphelins dans `tests/` qui importeraient encore la fonction.

- [x] **Step 5 : Run all tests pour confirmer absence de régression**

Run: `cd backend && uv run pytest -v 2>&1 | tail -10`
Expected: all green

- [x] **Step 6 : Lint + format**

Run: `cd backend && uv run ruff check src/ tests/ && uv run ruff format src/ tests/`
Expected: no errors

- [x] **Step 7 : Commit**

```bash
git add backend/src/agflow/services/deployment_env_helpers.py backend/src/agflow/api/admin/project_deployments.py
git commit -m "chore(cleanup): supprimer deployment_env_helpers.resolve_input_value (orpheline)"
```

---

## Task 12 : Smoke E2E sur LXC fresh

**Why:** Selon CLAUDE.md, validation end-to-end uniquement après deploy LXC. Le poste local n'a pas de stack qui tourne.

- [x] **Step 1 : Push de la branche**

```bash
git push origin dev
```

- [x] **Step 2 : Lancer le test fresh via run-test.sh**

Run: `./scripts/run-test.sh`
Expected: LXC créé, déploiement réussi, 8 assertions vertes + pytest backend complet vert.

- [x] **Step 3 : Vérification manuelle sur l'instance créée**

Une fois le LXC monté par le script :
1. Ouvrir l'UI dans le navigateur (URL fournie par le script).
2. Aller dans `Projects` → ouvrir un projet qui a un script avec une input via_env.
3. Configurer un input_value `${env-machine://<machine>:<VAR>}` valide → la bannière doit disparaître.
4. Mettre une ref `${env-machine://ghost:VAR}` → la bannière doit afficher : `KC_ADMIN_PASSWORD : machine inconnue : ghost`.
5. Mettre un input_value vide → la bannière doit afficher : `… : valeur vide`.
6. Cliquer sur "Pousser" → le wizard doit s'ouvrir, et le step ayant l'input non résoluble doit échouer avec un message explicite dans les logs SSE.

- [x] **Step 4 : Cleanup du LXC de test**

Run: `CLEANUP=1 ./scripts/run-test.sh` (ou `pct destroy <id>` sur l'hôte Proxmox).

- [x] **Step 5 : Si tout est OK, commit du PR ou merge**

(Selon préférence user — voir `superpowers:finishing-a-development-branch`.)

---

## Self-review

### Couverture spec
- ✅ Service `input_resolver` avec fail-fast + collect-all → Tasks 2, 3, 4
- ✅ 7 kinds d'erreur typés → Task 3 (tests par kind) + Task 8 (schéma)
- ✅ Migration des 2 callsites exec → Tasks 6, 7
- ✅ Refonte du check → Task 9
- ✅ Bannière frontend + i18n → Task 10
- ✅ Cleanup code mort → Task 11
- ✅ Smoke E2E → Task 12

### Cohérence types
- `UnresolvedKind` est `Literal[...]` à 7 valeurs ; identique dans `ProjectEnvVarsCheckMissingReason.kind` et dans `EnvVarsMissingKind` TS ; identique dans les clés i18n.
- `resolve_input_values` retourne `dict[str, str]` ; `resolve_input_values_collect` retourne `tuple[dict[str, str], list[UnresolvedPlaceholderError]]`.

### Risques connus / suivi
- Task 5 (`get_by_name`) conditionnelle — si la fonction n'existe pas, l'ajouter ; sinon skip. À vérifier avant Task 3.
- Performance : pas de cache global, juste un cache par invocation de `resolve_input_values`. Suffisant pour le périmètre actuel.
- Le hook `useEnvMachineVarCheck` côté frontend reste inchangé (UX dialog) — pas de conflit avec la bannière qui devient source de vérité au déploiement.

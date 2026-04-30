# Compose Renderer → Swarm Stack — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bascule le renderer admin (path A1, `render_group_compose`) du format compose v1 vers Swarm stack, en injectant un bloc `deploy:` résolu (recipe.deploy ⊕ defaults Python) sur chaque service via un filtre Jinja générique `to_yaml`.

**Architecture:** Nouveau module `services/swarm_defaults.py` avec defaults + deep_merge + resolve_deploy. Ajout d'un filtre Jinja `to_yaml` dans `compose_renderer_service.py`. Injection de `svc["deploy"]` dans `_build_group_context`. Template Jinja `seed-default-compose/fr.sh.j2` réécrit pour produire du Swarm stack (driver overlay, ports `mode: host`, deploy block générique).

**Tech Stack:** Python 3.12 + asyncpg + Jinja2 (SandboxedEnvironment) + PyYAML | pytest + pytest-asyncio.

**Spec source:** `docs/superpowers/specs/2026-04-30-compose-renderer-swarm-design.md`

---

## File Structure

| Fichier | Rôle | Action |
|---|---|---|
| `backend/src/agflow/services/swarm_defaults.py` | Constantes `_DEFAULT_DEPLOY` + `deep_merge()` + `resolve_deploy()` | NOUVEAU |
| `backend/src/agflow/services/compose_renderer_service.py` | Ajout filtre Jinja `to_yaml` + injection `svc["deploy"]` dans `_build_group_context` | MODIFIÉ (~15 lignes ajoutées) |
| `scripts/_prompts/seed-default-compose.sh.j2` | Template source de vérité repo, réécrit pour Swarm | MODIFIÉ (réécriture) |
| `backend/tests/test_swarm_defaults.py` | Tests unitaires `deep_merge` + `resolve_deploy` | NOUVEAU |
| `backend/tests/test_compose_renderer_swarm.py` | Tests filtre `to_yaml` + `_build_group_context` injection deploy + snapshot template | NOUVEAU |

**Hors plan** (ops manuel) : la propagation du nouveau template Jinja vers le volume `data/templates/seed-default-compose/fr.sh.j2` côté LXC 201 (et plus tard le cluster Swarm) — c'est un step de déploiement, pas du code.

---

## Task 1 — Module `swarm_defaults.py` : `deep_merge`

**Files:**
- Create: `backend/src/agflow/services/swarm_defaults.py`
- Create: `backend/tests/test_swarm_defaults.py`

- [ ] **Step 1 : Test rouge — deep_merge basics**

Créer `backend/tests/test_swarm_defaults.py` :

```python
from __future__ import annotations

from agflow.services.swarm_defaults import deep_merge


def test_deep_merge_returns_base_copy_when_override_is_none() -> None:
    base = {"a": 1, "b": {"c": 2}}
    result = deep_merge(base, None)
    assert result == base
    # Mutating result must not mutate base
    result["a"] = 999
    result["b"]["c"] = 999
    assert base == {"a": 1, "b": {"c": 2}}


def test_deep_merge_returns_base_copy_when_override_is_empty() -> None:
    base = {"a": 1}
    result = deep_merge(base, {})
    assert result == base


def test_deep_merge_override_replaces_scalar() -> None:
    base = {"a": 1, "b": 2}
    assert deep_merge(base, {"a": 10}) == {"a": 10, "b": 2}


def test_deep_merge_recurses_into_nested_dicts() -> None:
    base = {"outer": {"inner1": 1, "inner2": 2}}
    override = {"outer": {"inner1": 10}}
    assert deep_merge(base, override) == {"outer": {"inner1": 10, "inner2": 2}}


def test_deep_merge_lists_are_replaced_not_concatenated() -> None:
    base = {"items": [1, 2, 3]}
    override = {"items": [9]}
    assert deep_merge(base, override) == {"items": [9]}


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"a": {"b": 1}}
    override = {"a": {"c": 2}}
    base_snapshot = {"a": {"b": 1}}
    override_snapshot = {"a": {"c": 2}}
    deep_merge(base, override)
    assert base == base_snapshot
    assert override == override_snapshot
```

- [ ] **Step 2 : Vérifier qu'il échoue**

```bash
cd backend && uv run pytest tests/test_swarm_defaults.py -v
```

Attendu : `ModuleNotFoundError: agflow.services.swarm_defaults`.

- [ ] **Step 3 : Implémentation minimale**

Créer `backend/src/agflow/services/swarm_defaults.py` :

```python
"""Defaults Swarm pour les blocs `deploy:` injectes dans les services rendus.

Resolution : recipe.services[*].deploy (optionnel) deep-merge sur _DEFAULT_DEPLOY.
Le resultat est passe verbatim au template Jinja qui le dumpe via le filtre to_yaml.
"""
from __future__ import annotations

import copy


def deep_merge(base: dict, override: dict | None) -> dict:
    """Deep-merge: override prend priorite, dicts imbriques sont mergees
    recursivement, listes sont remplacees (pas concatenees).

    Aucune mutation des inputs. Retourne toujours un nouveau dict.
    """
    result = copy.deepcopy(base)
    if not override:
        return result
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
    return result
```

- [ ] **Step 4 : Vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_swarm_defaults.py -v
```

Attendu : 6 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/swarm_defaults.py tests/test_swarm_defaults.py
```

Attendu : `All checks passed!`

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/swarm_defaults.py backend/tests/test_swarm_defaults.py
git commit -m "feat(swarm-defaults): deep_merge utilitaire (listes remplacees, dicts mergees)"
```

---

## Task 2 — Module `swarm_defaults.py` : `_DEFAULT_DEPLOY` + `resolve_deploy`

**Files:**
- Modify: `backend/src/agflow/services/swarm_defaults.py`
- Modify: `backend/tests/test_swarm_defaults.py`

- [ ] **Step 1 : Tests rouges — resolve_deploy avec defaults**

Ajouter à la fin de `backend/tests/test_swarm_defaults.py` :

```python
from agflow.services.swarm_defaults import _DEFAULT_DEPLOY, resolve_deploy


def test_resolve_deploy_with_none_returns_full_defaults() -> None:
    result = resolve_deploy(None)
    assert result == _DEFAULT_DEPLOY
    # Independance : modifier le resultat ne doit pas muter les defaults
    result["replicas"] = 999
    assert _DEFAULT_DEPLOY["replicas"] == 1


def test_resolve_deploy_overrides_replicas() -> None:
    result = resolve_deploy({"replicas": 3})
    assert result["replicas"] == 3
    # Les autres defaults restent intacts
    assert result["endpoint_mode"] == "dnsrr"
    assert result["restart_policy"]["condition"] == "on-failure"


def test_resolve_deploy_deep_merges_resources() -> None:
    result = resolve_deploy({
        "resources": {"limits": {"memory": "1G"}},
    })
    assert result["resources"]["limits"]["memory"] == "1G"
    # Restart_policy intact
    assert result["restart_policy"]["max_attempts"] == 5


def test_resolve_deploy_replaces_constraints_list() -> None:
    result = resolve_deploy({
        "placement": {"constraints": ["node.role == worker"]},
    })
    assert result["placement"]["constraints"] == ["node.role == worker"]


def test_resolve_deploy_partial_restart_policy() -> None:
    result = resolve_deploy({
        "restart_policy": {"max_attempts": 10},
    })
    assert result["restart_policy"]["max_attempts"] == 10
    assert result["restart_policy"]["condition"] == "on-failure"
    assert result["restart_policy"]["delay"] == "10s"
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

```bash
cd backend && uv run pytest tests/test_swarm_defaults.py -v
```

Attendu : 6 verts (Task 1) + 5 rouges (`ImportError: cannot import name '_DEFAULT_DEPLOY' or 'resolve_deploy'`).

- [ ] **Step 3 : Implémentation**

Ajouter à la fin de `backend/src/agflow/services/swarm_defaults.py` :

```python
_DEFAULT_DEPLOY: dict = {
    "replicas": 1,
    "endpoint_mode": "dnsrr",                           # IPVS LXC workaround
    "placement": {"constraints": ["node.role == manager"]},
    "restart_policy": {
        "condition": "on-failure",
        "delay": "10s",
        "max_attempts": 5,
    },
    "update_config": {
        "parallelism": 1,
        "delay": "10s",
        "order": "start-first",
    },
}


def resolve_deploy(recipe_deploy: dict | None) -> dict:
    """Resolve le bloc deploy final : deep-merge recipe.deploy sur les defaults.

    Retourne un dict toujours complet (jamais None). Si recipe_deploy est None
    ou vide, retourne une copie defensive des defaults.
    """
    return deep_merge(_DEFAULT_DEPLOY, recipe_deploy)
```

- [ ] **Step 4 : Vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_swarm_defaults.py -v
```

Attendu : 11 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/swarm_defaults.py tests/test_swarm_defaults.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/swarm_defaults.py backend/tests/test_swarm_defaults.py
git commit -m "feat(swarm-defaults): _DEFAULT_DEPLOY + resolve_deploy (deep-merge avec defaults)"
```

---

## Task 3 — Filtre Jinja `to_yaml` dans `compose_renderer_service.py`

**Files:**
- Modify: `backend/src/agflow/services/compose_renderer_service.py` (ajout filtre + enregistrement)
- Create: `backend/tests/test_compose_renderer_swarm.py`

- [ ] **Step 1 : Tests rouges — filtre to_yaml**

Créer `backend/tests/test_compose_renderer_swarm.py` :

```python
"""Tests pour les helpers Swarm du compose renderer (path A1)."""
from __future__ import annotations

from agflow.services.compose_renderer_service import _to_yaml_filter


def test_to_yaml_filter_no_indent() -> None:
    out = _to_yaml_filter({"replicas": 1, "endpoint_mode": "dnsrr"}, indent=0)
    # Pas d'indentation, pas de newline final
    assert out == "replicas: 1\nendpoint_mode: dnsrr"


def test_to_yaml_filter_with_indent_pads_each_line() -> None:
    out = _to_yaml_filter({"replicas": 2, "placement": {"constraints": ["node.role == manager"]}}, indent=6)
    expected = (
        "      replicas: 2\n"
        "      placement:\n"
        "        constraints:\n"
        "        - node.role == manager"
    )
    assert out == expected


def test_to_yaml_filter_handles_nested_dict() -> None:
    out = _to_yaml_filter({"a": {"b": {"c": 1}}}, indent=4)
    assert out == "    a:\n      b:\n        c: 1"


def test_to_yaml_filter_preserves_key_order() -> None:
    out = _to_yaml_filter({"z": 1, "a": 2}, indent=0)
    # sort_keys=False → l'ordre d'insertion est preserve
    assert out == "z: 1\na: 2"
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

```bash
cd backend && uv run pytest tests/test_compose_renderer_swarm.py -v
```

Attendu : `ImportError: cannot import name '_to_yaml_filter' from 'agflow.services.compose_renderer_service'`.

- [ ] **Step 3 : Implémentation du filtre**

Modifier `backend/src/agflow/services/compose_renderer_service.py` — ajouter avant la définition de `_JINJA_ENV` (vers ligne 33) :

```python
def _to_yaml_filter(value, indent: int = 0) -> str:
    """Dump a dict/list as YAML at a given indent level. Used by templates to
    serialize deploy/resources blocks generically without hardcoding fields.

    The trailing newline is always stripped (the caller decides newline handling).
    Each non-empty output line gets ``indent`` spaces prepended when ``indent > 0``.
    """
    text = yaml.dump(value, default_flow_style=False, allow_unicode=True, sort_keys=False)
    text = text.rstrip("\n")
    if indent <= 0:
        return text
    pad = " " * indent
    return "\n".join(pad + line for line in text.splitlines())
```

Et juste après la définition de `_JINJA_ENV` (vers ligne 38), enregistrer le filtre :

```python
_JINJA_ENV.filters["to_yaml"] = _to_yaml_filter
```

- [ ] **Step 4 : Vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_compose_renderer_swarm.py -v
```

Attendu : 4 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/compose_renderer_service.py tests/test_compose_renderer_swarm.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/compose_renderer_service.py backend/tests/test_compose_renderer_swarm.py
git commit -m "feat(compose-renderer): filtre Jinja to_yaml(indent) pour rendre des blocs YAML generiques"
```

---

## Task 4 — Injection `deploy:` dans `_build_group_context`

**Files:**
- Modify: `backend/src/agflow/services/compose_renderer_service.py` (ligne ~163-191 : ajouter `"deploy"` dans `services.append({...})`)
- Modify: `backend/tests/test_compose_renderer_swarm.py` (ajouter tests sur le contenu produit)

- [ ] **Step 1 : Tests rouges — `_build_group_context` doit produire `svc.deploy`**

Ajouter à la fin de `backend/tests/test_compose_renderer_swarm.py` :

```python
from types import SimpleNamespace
from uuid import uuid4

from agflow.services.compose_renderer_service import _build_group_context


def _make_instance(name: str, group_id, catalog_id, variables: dict | None = None):
    return SimpleNamespace(
        id=uuid4(),
        instance_name=name,
        group_id=group_id,
        catalog_id=catalog_id,
        variables=variables or {},
        created_at="2026-04-30",
    )


def test_build_group_context_injects_default_deploy_when_recipe_has_none() -> None:
    group = SimpleNamespace(id=uuid4(), name="my-group")
    catalog_id = uuid4()
    instance = _make_instance("inst1", group.id, catalog_id)
    recipe = {
        "services": [
            {"id": "api", "image": "nginx:1.27", "ports": [80]},
        ],
    }
    block = _build_group_context(
        group=group,
        instances=[instance],
        all_instances=[instance],
        recipes_by_id={str(catalog_id): recipe},
        network="agflow",
    )

    svc = block["instances"][0]["services"][0]
    assert "deploy" in svc
    # Default deploy contient bien le bloc complet
    assert svc["deploy"]["replicas"] == 1
    assert svc["deploy"]["endpoint_mode"] == "dnsrr"
    assert svc["deploy"]["placement"]["constraints"] == ["node.role == manager"]
    assert svc["deploy"]["restart_policy"]["condition"] == "on-failure"


def test_build_group_context_deep_merges_recipe_deploy_override() -> None:
    group = SimpleNamespace(id=uuid4(), name="my-group")
    catalog_id = uuid4()
    instance = _make_instance("inst1", group.id, catalog_id)
    recipe = {
        "services": [
            {
                "id": "api",
                "image": "nginx:1.27",
                "ports": [80],
                "deploy": {
                    "replicas": 3,
                    "resources": {"limits": {"memory": "512M"}},
                },
            },
        ],
    }
    block = _build_group_context(
        group=group,
        instances=[instance],
        all_instances=[instance],
        recipes_by_id={str(catalog_id): recipe},
        network="agflow",
    )

    svc = block["instances"][0]["services"][0]
    assert svc["deploy"]["replicas"] == 3
    assert svc["deploy"]["resources"]["limits"]["memory"] == "512M"
    # Defaults non-touches conserves
    assert svc["deploy"]["endpoint_mode"] == "dnsrr"
    assert svc["deploy"]["restart_policy"]["max_attempts"] == 5
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

```bash
cd backend && uv run pytest tests/test_compose_renderer_swarm.py -v
```

Attendu : 4 verts (Task 3) + 2 rouges (`KeyError: 'deploy'` parce que la clé n'est pas encore injectée).

- [ ] **Step 3 : Implémentation**

Modifier `backend/src/agflow/services/compose_renderer_service.py` :

1. Ajouter l'import en haut du fichier (avec les autres imports `from agflow.services`) :

```python
from agflow.services.swarm_defaults import resolve_deploy
```

2. Dans la boucle `for svc in recipe.get("services", []):` de `_build_group_context` (vers ligne 149-191), modifier le `services.append({...})` pour ajouter la clé `"deploy"` :

```python
            services.append({
                "id": svc_id,
                "container_name": container,
                "image": svc.get("image", ""),
                "ports": list(svc.get("ports") or []),
                "environment": env,
                "volumes": [
                    {
                        "name": vol.get("name", ""),
                        "mount": vol.get("mount", ""),
                        "docker_volume": f"{container}-{vol.get('name', '')}" if vol.get("name") else "",
                    }
                    for vol in (svc.get("volumes") or [])
                ],
                "depends_on": [
                    f"{inst.instance_name}-{dep}"
                    for dep in (svc.get("requires_services") or [])
                ],
                "labels": labels,
                "networks": [network],
                "deploy": resolve_deploy(svc.get("deploy")),    # ← AJOUT
            })
```

> Note : la clé `"restart": "unless-stopped"` est **supprimee** du dict — Swarm l'ignore et `deploy.restart_policy` (du bloc `deploy` resolu) la remplace fonctionnellement. Si un autre consommateur lisait `svc["restart"]`, le test rouge le revelera.

- [ ] **Step 4 : Vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_compose_renderer_swarm.py -v
```

Attendu : 6 tests verts.

- [ ] **Step 5 : Régression sur les autres tests**

```bash
cd backend && uv run pytest tests/test_compose_renderer_runtime.py tests/test_swarm_defaults.py -v
```

Attendu : tous verts (les tests de `_build_runtime_instance_ctx` et `swarm_defaults` ne sont pas impactés).

- [ ] **Step 6 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/compose_renderer_service.py tests/test_compose_renderer_swarm.py
```

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/services/compose_renderer_service.py backend/tests/test_compose_renderer_swarm.py
git commit -m "feat(compose-renderer): injecte deploy resolu (defaults+recipe.deploy) sur chaque service"
```

---

## Task 5 — Réécriture du template `seed-default-compose.sh.j2` pour Swarm

**Files:**
- Modify: `scripts/_prompts/seed-default-compose.sh.j2`
- Modify: `backend/tests/test_compose_renderer_swarm.py` (ajout snapshot test)

- [ ] **Step 1 : Test rouge — snapshot du template Swarm rendered**

Ajouter à la fin de `backend/tests/test_compose_renderer_swarm.py` :

```python
from pathlib import Path

import yaml
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from agflow.services.compose_renderer_service import _to_yaml_filter


def _render_template(template_path: Path, context: dict) -> str:
    env = SandboxedEnvironment(
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    env.filters["to_yaml"] = _to_yaml_filter
    template = env.from_string(template_path.read_text(encoding="utf-8"))
    return template.render(**context)


def test_seed_default_compose_template_produces_valid_swarm_stack() -> None:
    """Le template seed-default-compose doit produire un YAML Swarm-stack valide."""
    template_path = Path(__file__).parent.parent.parent / "scripts" / "_prompts" / "seed-default-compose.sh.j2"
    assert template_path.exists(), f"Template introuvable : {template_path}"

    context = {
        "group": {"id": "g-1", "name": "g", "slug": "G"},
        "group_slug": "G",
        "network": "agflow_proj",
        "volumes": ["api-data"],
        "instances": [
            {
                "id": "inst-1",
                "group_id": "g-1",
                "instance_name": "inst",
                "catalog_id": "cat-1",
                "services": [
                    {
                        "id": "api",
                        "container_name": "inst-api",
                        "image": "nginx:1.27",
                        "ports": [80],
                        "environment": {"FOO": "bar"},
                        "volumes": [
                            {"name": "data", "mount": "/data", "docker_volume": "api-data"},
                        ],
                        "depends_on": [],
                        "labels": ["agflow.group_id=g-1"],
                        "networks": ["agflow_proj"],
                        "deploy": {
                            "replicas": 2,
                            "endpoint_mode": "dnsrr",
                            "placement": {"constraints": ["node.role == manager"]},
                            "restart_policy": {"condition": "on-failure", "delay": "10s", "max_attempts": 5},
                        },
                    },
                ],
            },
        ],
    }

    rendered = _render_template(template_path, context)

    # Parsing YAML : doit être valide
    parsed = yaml.safe_load(rendered)

    # Structure attendue
    assert "services" in parsed
    assert "inst-api" in parsed["services"]
    svc = parsed["services"]["inst-api"]

    assert svc["image"] == "nginx:1.27"
    assert svc["hostname"] == "inst-api"

    # Bloc deploy complet
    assert svc["deploy"]["replicas"] == 2
    assert svc["deploy"]["endpoint_mode"] == "dnsrr"

    # Ports en long-form mode: host
    assert svc["ports"] == [{"target": 80, "published": 80, "mode": "host"}]

    # Network en overlay
    assert parsed["networks"]["agflow_proj"]["driver"] == "overlay"

    # Volumes declarés
    assert "api-data" in parsed["volumes"]


def test_seed_default_compose_template_excludes_legacy_fields() -> None:
    """Le template ne doit PLUS contenir les directives compose-v1 obsolètes."""
    template_path = Path(__file__).parent.parent.parent / "scripts" / "_prompts" / "seed-default-compose.sh.j2"
    content = template_path.read_text(encoding="utf-8")

    assert "container_name:" not in content, "container_name doit etre supprime (Swarm gere les noms)"
    assert "restart:" not in content, "restart top-level doit etre supprime (Swarm utilise deploy.restart_policy)"
    assert "driver: bridge" not in content, "driver: bridge doit etre remplace par driver: overlay"
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

```bash
cd backend && uv run pytest tests/test_compose_renderer_swarm.py::test_seed_default_compose_template_produces_valid_swarm_stack -v
cd backend && uv run pytest tests/test_compose_renderer_swarm.py::test_seed_default_compose_template_excludes_legacy_fields -v
```

Attendu : tous deux rouges (le template actuel utilise `container_name`, `restart`, `driver: bridge`, ports court-format).

- [ ] **Step 3 : Réécrire le template**

Remplacer **intégralement** le contenu de `scripts/_prompts/seed-default-compose.sh.j2` par :

```jinja2
services:
{%- for inst in instances %}
{%- for svc in inst.services %}
  {{ svc.container_name }}:
    image: {{ svc.image }}
    hostname: {{ svc.container_name }}
    labels:
{%- for lbl in svc.labels %}
      - {{ lbl }}
{%- endfor %}
    networks:
{%- for net in svc.networks %}
      - {{ net }}
{%- endfor %}
{%- if svc.ports %}
    ports:
{%- for port in svc.ports %}
      - target: {{ port }}
        published: {{ port }}
        mode: host
{%- endfor %}
{%- endif %}
{%- if svc.environment %}
    environment:
{%- for k, v in svc.environment.items() %}
      {{ k }}: "{{ v }}"
{%- endfor %}
{%- endif %}
{%- if svc.volumes %}
    volumes:
{%- for vol in svc.volumes %}
      - {{ vol.docker_volume }}:{{ vol.mount }}
{%- endfor %}
{%- endif %}
{%- if svc.depends_on %}
    depends_on:
{%- for dep in svc.depends_on %}
      - {{ dep }}
{%- endfor %}
{%- endif %}
{%- if svc.deploy %}
    deploy:
{{ svc.deploy | to_yaml(6) }}
{%- endif %}
{%- endfor %}
{%- endfor %}

networks:
  {{ network }}:
    driver: overlay
{%- if volumes %}

volumes:
{%- for v in volumes %}
  {{ v }}:
{%- endfor %}
{%- endif %}
```

- [ ] **Step 4 : Vérifier que les snapshot tests passent**

```bash
cd backend && uv run pytest tests/test_compose_renderer_swarm.py -v
```

Attendu : 8 tests verts (les 6 précédents + 2 nouveaux).

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check tests/test_compose_renderer_swarm.py
```

- [ ] **Step 6 : Commit**

```bash
git add scripts/_prompts/seed-default-compose.sh.j2 backend/tests/test_compose_renderer_swarm.py
git commit -m "feat(template): seed-default-compose produit du Swarm stack (overlay, deploy, mode host)

- Network driver: bridge -> overlay
- Ports court-format -> long-form avec mode: host (workaround IPVS LXC)
- container_name: supprime (Swarm gere les noms de replicas)
- restart: top-level supprime (remplace par deploy.restart_policy via defaults)
- Bloc deploy: rendu generique via filtre Jinja to_yaml(6)
- Hostname ajoute pour stabilite DNS overlay

Snapshot test : YAML rendered parse valide + structure Swarm-spec respectee."
```

---

## Task 6 — Vérification globale + smoke render local

**Files:** Aucun changement de code.

- [ ] **Step 1 : Suite complète backend export + swarm**

```bash
cd backend && uv run pytest tests/test_swarm_defaults.py tests/test_compose_renderer_swarm.py tests/test_compose_renderer_runtime.py -v
```

Attendu : tous verts (11 + 8 + N existants).

- [ ] **Step 2 : Lint+format full sur les fichiers touchés**

```bash
cd backend && uv run ruff check src/agflow/services/swarm_defaults.py src/agflow/services/compose_renderer_service.py tests/test_swarm_defaults.py tests/test_compose_renderer_swarm.py
cd backend && uv run ruff format --check src/agflow/services/swarm_defaults.py src/agflow/services/compose_renderer_service.py tests/test_swarm_defaults.py tests/test_compose_renderer_swarm.py
```

Attendu : `All checks passed!` + `4 files already formatted`.

- [ ] **Step 3 : Smoke import**

```bash
cd backend && uv run python -c "from agflow.main import create_app; create_app(); print('boot ok')"
```

Attendu : `boot ok`.

- [ ] **Step 4 : Sanity git log**

```bash
git log --oneline 3c5d760..HEAD
```

Attendu : 5 commits dans cet ordre :
1. `feat(swarm-defaults): deep_merge utilitaire ...`
2. `feat(swarm-defaults): _DEFAULT_DEPLOY + resolve_deploy ...`
3. `feat(compose-renderer): filtre Jinja to_yaml ...`
4. `feat(compose-renderer): injecte deploy resolu ...`
5. `feat(template): seed-default-compose produit du Swarm stack ...`

- [ ] **Step 5 : `git status -s`**

```bash
git status -s
```

Attendu : vide.

---

## Task 7 — Smoke contre LXC 201 (validation manuelle)

**Note** : étape facultative tant qu'on n'a pas pushé l'image CI. Validation que le rendu fonctionne sur un projet réel.

**Files:** Aucun changement de code.

- [ ] **Step 1 : Push de la branche pour CI rebuild**

```bash
git push origin HEAD
```

(Push la branche courante telle qu'elle est, sans hardcoder le nom — le user décide ensuite s'il merge sur main pour déclencher le build automatique, ou s'il `workflow_dispatch` manuellement.)

- [ ] **Step 2 : (USER) Trigger manuel du workflow GHCR**

L'utilisateur déclenche `workflow_dispatch` sur la branche pushée avec `force_all=true` pour rebuild les images backend+frontend. Alternative : merger sur `main` pour déclencher le build auto via le trigger `push: [main]`.

- [ ] **Step 3 : Propagation du nouveau template sur LXC 201**

Le template Jinja vit dans le volume `data/`, pas dans l'image. Donc on doit explicitement le mettre à jour côté LXC :

```bash
scp scripts/_prompts/seed-default-compose.sh.j2 pve:/tmp/seed-default-compose.sh.j2
ssh pve "pct push 201 /tmp/seed-default-compose.sh.j2 /tmp/seed-default-compose.sh.j2 && \
         pct exec 201 -- cp /tmp/seed-default-compose.sh.j2 /root/agflow.docker/data/templates/seed-default-compose/fr.sh.j2 && \
         pct exec 201 -- ls -la /root/agflow.docker/data/templates/seed-default-compose/fr.sh.j2"
```

> Pour l'environnement Swarm (ops), le user appliquera la même mise à jour sur `/srv/agflow/data/templates/...`.

- [ ] **Step 4 : Smoke render via API admin**

Sur l'UI admin, ouvrir un projet existant, déclencher l'aperçu du `compose` d'un groupe, vérifier visuellement :

- Le YAML produit a un bloc `deploy:` sur chaque service
- `networks: agflow:\n    driver: overlay`
- `ports:` en long-form avec `mode: host`
- Plus de `restart:` ni `container_name:` ni `driver: bridge`

Si KO : récupérer le YAML brut, débugger le template ou le contexte.

- [ ] **Step 5 : Smoke `docker stack deploy --dry-run` (si dispo)**

Optionnel : sur la machine de déploiement cible, valider avec `docker stack config -c stack.yml STACK` que la syntaxe est acceptée par Swarm.

---

## Critères d'acceptation finaux

- [ ] Module `services/swarm_defaults.py` créé avec `_DEFAULT_DEPLOY`, `deep_merge`, `resolve_deploy`
- [ ] 11 tests unitaires `swarm_defaults` verts
- [ ] Filtre `to_yaml` enregistré dans `_JINJA_ENV` + 4 tests verts
- [ ] `_build_group_context` injecte `svc.deploy` résolu sur chaque service + 2 tests verts
- [ ] Template `seed-default-compose.sh.j2` réécrit pour Swarm + 2 snapshot tests verts
- [ ] Aucune régression sur `test_compose_renderer_runtime.py` (path A2 inchangé)
- [ ] Lint + format propres
- [ ] Smoke import OK (`from agflow.main import create_app`)
- [ ] Smoke prod (Task 7 facultative) : YAML rendered visuellement OK sur un projet exemple

---

## Hors plan

- Path A2 (`render_for_runtime`) — chantier suivant distinct
- Bloc `secrets:` Swarm — itération future
- UI admin pour éditer le `deploy:` du recipe — passe par l'éditeur YAML existant
- Refacto `container_runner.py` (Chantier B) — distinct

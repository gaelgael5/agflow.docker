# Spec — Compose renderer → Swarm stack renderer (Chantier A1)

> **Statut** : design validé 2026-04-30 — prêt pour le plan d'implémentation
> **Auteur** : brainstorming Claude + utilisateur
> **Initiative parente** : migration agflow.docker du paradigme `docker run` vers Docker Swarm
> **Hors scope** : path A2 (`render_for_runtime` SaaS), bloc `secrets:` Swarm, refacto `container_runner.py` (chantier B futur)

## 1. Contexte

Le module `services/compose_renderer_service.py` produit aujourd'hui un fichier `docker-compose.yml` au format compose v1 (services, networks bridge, restart, ports court-format) consommé par `docker compose up -d` côté machines de déploiement. Avec la migration vers Docker Swarm (cluster manager + workers), ce fichier doit basculer au format **Swarm stack** (compose v3+ avec blocs `deploy:`, ports long-form, networks overlay, etc.) pour être consommé par `docker stack deploy -c file.yml STACK`.

Deux paths produisent du compose dans ce module :

| Path | Fonction | Caller principal |
|------|----------|------------------|
| **A1** | `render_group_compose` | `api/admin/project_deployments.py` (preview + génération scripts) |
| **A2** | `render_for_runtime` | `api/public/runtimes.py` (SaaS multi-replica) |

**Cette spec couvre uniquement A1**. A2 fera l'objet d'un chantier suivant.

## 2. Décisions verrouillées

| Sujet | Choix | Raison |
|---|---|---|
| Format de sortie | **Swarm stack** (compose v3+ avec `deploy:`) | Cible : `docker stack deploy` |
| Strat. paramètres Swarm | **Par service**, dans le `recipe` du catalogue produit (option B + defaults) | Granularité fine, le recipe est la source de vérité métier |
| Localisation defaults | **Constantes Python** (`services/swarm_defaults.py`) | Single source of truth, testable, non-customer-tunable |
| Stratégie template | **Remplacement in-place** de `seed-default-compose/fr.sh.j2` | Bascule globale plateforme |
| Schéma `recipe.deploy` | **Format Swarm-spec** (replicas, placement, restart_policy, etc.) | Standard, auto-documenté |
| Rendering Jinja | **Filtre générique `to_yaml(indent)`** | Ajouter un champ Swarm = no template change |
| Network | **`driver: overlay`** créé par le stack | Auto-cleanup, isolation par projet |
| Ports | **Long-form `mode: host`** par défaut | Workaround IPVS LXC connu |
| Directive `restart:` | **Supprimée** | Ignored par Swarm, redondant avec `deploy.restart_policy` |
| `container_name:` | **Supprimé** | Swarm gère le nommage des replicas |
| Path A2 (`render_for_runtime`) | Hors scope, chantier suivant | |
| Bloc `secrets:` Swarm | Hors scope, conservation injection actuelle | "Pour le moment on ne touche pas aux secrets" |

## 3. Defaults Swarm (constantes Python)

```python
# backend/src/agflow/services/swarm_defaults.py
_DEFAULT_DEPLOY: dict = {
    "replicas": 1,
    "endpoint_mode": "dnsrr",                          # IPVS LXC workaround
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
```

**Volontairement absents** :
- `resources.limits.{memory,cpus}` / `resources.reservations.*` : workload-dépendant. Doit être déclaré explicitement par le recipe quand pertinent.
- `labels` Swarm-level (différents des container labels déjà gérés).
- `mode: replicated` : c'est le mode par défaut, pas besoin de l'expliciter.

## 4. Architecture

```
Recipe YAML (catalogue produit, par service)
    │  services:
    │    - id: api
    │      image: …
    │      ports: [8000]
    │      env_template: { … }
    │      volumes: [ … ]
    │      deploy:                       ← NOUVEAU bloc optionnel
    │        replicas: 3
    │        resources: { limits: { memory: 512M } }
    ▼
_build_group_context (Python, modifié)
    │  pour chaque service :
    │    svc_entry["deploy"] = resolve_deploy(svc_recipe.get("deploy"))
    │    # deep-merge recipe.deploy sur _DEFAULT_DEPLOY
    ▼
build_deployment_data → dict persisté en DB (project_deployments.generated_data)
    │  contient désormais svc.deploy par service (résolu = avec defaults appliqués)
    ▼
render_group_compose (Jinja, template modifié)
    │  data/templates/seed-default-compose/fr.sh.j2 réécrit pour Swarm
    │  filtre to_yaml(indent) dumpe svc.deploy générique
    ▼
docker-compose.yml (Swarm stack)
    │  consommable via `docker stack deploy -c …`
```

## 5. Modifications de fichiers

### 5.1 NOUVEAU `backend/src/agflow/services/swarm_defaults.py`

```python
"""Defaults Swarm pour les blocs `deploy:` injectes dans les services rendus.

Resolution : recipe.services[*].deploy (optionnel) deep-merge sur _DEFAULT_DEPLOY.
Le resultat est passe verbatim au template Jinja qui le dumpe via le filtre to_yaml.
"""
from __future__ import annotations

import copy

_DEFAULT_DEPLOY: dict = {
    "replicas": 1,
    "endpoint_mode": "dnsrr",
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


def deep_merge(base: dict, override: dict | None) -> dict:
    """Deep-merge: override prend priorite, dicts imbriques sont mergees recursivement,
    listes sont remplacees (pas concatenees)."""
    result = copy.deepcopy(base)
    if not override:
        return result
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def resolve_deploy(recipe_deploy: dict | None) -> dict:
    """Resolve le bloc deploy final : merge recipe.deploy sur les defaults."""
    return deep_merge(_DEFAULT_DEPLOY, recipe_deploy)
```

### 5.2 MODIFIÉ `backend/src/agflow/services/compose_renderer_service.py`

**Ajout du filtre Jinja `to_yaml`** (après définition de `_JINJA_ENV` ligne ~33-38) :

```python
def _to_yaml_filter(value, indent: int = 0) -> str:
    """Dump a dict/list as YAML at a given indent level. Used by templates to
    serialize deploy/resources blocks generically without hardcoding fields."""
    text = yaml.dump(value, default_flow_style=False, allow_unicode=True, sort_keys=False)
    if indent <= 0:
        return text.rstrip("\n")
    pad = " " * indent
    return "\n".join(pad + line for line in text.rstrip("\n").splitlines())

_JINJA_ENV.filters["to_yaml"] = _to_yaml_filter
```

**Ajout dans `_build_group_context`** (dans la boucle `for svc in recipe.get("services", []):`) :

```python
from agflow.services.swarm_defaults import resolve_deploy
...
services.append({
    "id": svc_id,
    "container_name": container,
    "image": svc.get("image", ""),
    # "restart": "unless-stopped",            ← SUPPRIMÉ (ignored par Swarm)
    "ports": list(svc.get("ports") or []),
    "environment": env,
    "volumes": [...],
    "depends_on": [...],
    "labels": labels,
    "networks": [network],
    "deploy": resolve_deploy(svc.get("deploy")),    # ← AJOUT
})
```

### 5.3 MODIFIÉ `data/templates/seed-default-compose/fr.sh.j2`

Réécriture complète pour produire du Swarm stack :

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

**Diff résumé vs ancien template** :

| Avant | Après |
|---|---|
| `container_name: …` | `hostname: …` (Swarm gère les noms de replicas) |
| `restart: {{ svc.restart }}` | (supprimé, remplacé par `deploy.restart_policy`) |
| `ports: ["{{ port }}:{{ port }}"]` | Long-form avec `mode: host` |
| (aucun) | `deploy:` rendu via `to_yaml` |
| `driver: bridge` | `driver: overlay` |

### 5.4 NOUVEAU `backend/tests/test_swarm_defaults.py`

Tests unitaires sur `deep_merge` et `resolve_deploy` :

| # | Cas | Attendu |
|---|---|---|
| 1 | `resolve_deploy(None)` | dict identique à `_DEFAULT_DEPLOY` (et indépendant — modifier le résultat ne mute pas le default) |
| 2 | `resolve_deploy({})` | idem cas 1 |
| 3 | `resolve_deploy({"replicas": 3})` | replicas=3, autres keys = defaults |
| 4 | `resolve_deploy({"resources": {"limits": {"memory": "1G"}}})` | resources.limits.memory="1G" injecté, restart_policy/placement intacts |
| 5 | `resolve_deploy({"placement": {"constraints": []}})` | placement.constraints = [] (replace, pas concat avec default) |
| 6 | `resolve_deploy({"restart_policy": {"max_attempts": 10}})` | restart_policy.max_attempts=10, condition/delay restent les defaults |
| 7 | `deep_merge` ne mute pas `base` ni `override` | invariant fondamental |

### 5.5 NOUVEAU `backend/tests/test_compose_renderer_swarm.py`

Audit fait : **aucun test n'existe actuellement sur le path A1**. Seul `test_compose_renderer_runtime.py` couvre `_build_runtime_instance_ctx` (path A2, hors scope).

On profite du chantier pour combler ce trou avec des tests purs (pas de DB) sur `_build_group_context` + le filtre `to_yaml` + un snapshot du template Swarm rendered :

| # | Cas | Cible |
|---|---|---|
| 1 | `_build_group_context` produit `svc.deploy` avec defaults complets quand recipe.deploy absent | `_build_group_context` |
| 2 | `_build_group_context` deep-merge correctement quand recipe.deploy est partiel | `_build_group_context` |
| 3 | Le filtre `to_yaml(0)` produit du YAML sans indentation | `_to_yaml_filter` |
| 4 | Le filtre `to_yaml(6)` indente chaque ligne de 6 espaces | `_to_yaml_filter` |
| 5 | Snapshot : template Swarm rendered sur un recipe minimaliste contient `deploy:`, `driver: overlay`, `mode: host` | `render_group_compose` |
| 6 | Snapshot : aucune occurrence de `restart:` (top-level) ni `container_name:` ni `driver: bridge` | `render_group_compose` |

Les tests utilisent des fixtures Python (instances mockées) — pas de connexion DB requise.

`test_compose_renderer_runtime.py` reste inchangé (path A2, hors scope).

## 6. Compatibilité ascendante

| Aspect | Impact |
|---|---|
| Recipes existants sans `deploy:` | ✅ Aucun changement requis. Les defaults Swarm s'appliquent automatiquement. |
| Recipes existants avec `deploy:` (cas non rencontré aujourd'hui) | ✅ Les sous-champs explicites overrident les defaults via deep-merge. |
| Templates custom autres que `seed-default-compose` | ⚠️ Restent au format compose v1 (pas de `deploy:` rendu). Si un groupe pointe sur un template custom, il continue de produire du compose-classique. |
| Déploiements en cours (`generated_compose` déjà persisté en DB) | ✅ Pas re-rendu sauf nouveau cycle de deploy. Pas d'impact rétroactif. |
| `render_for_runtime` (path A2) | ✅ Inchangé — reste sur sa logique Python actuelle. |

## 7. Risques et mitigation

| Risque | Mitigation |
|---|---|
| Le template custom d'un groupe ne sait pas faire le bloc `deploy:` | Contexte Jinja contient désormais `svc.deploy` ; les templates custom peuvent l'utiliser ou l'ignorer. Pas de régression. |
| Le filtre `to_yaml` produit une indentation inattendue | Tests unitaires sur le filtre + snapshot du template rendered avec un recipe d'exemple. |
| `endpoint_mode: dnsrr` cassé sur env non-LXC | Acceptable : le default cible le contexte LXC actuel. Si un projet déploie ailleurs, il override via `recipe.deploy.endpoint_mode: vip`. |
| Deep-merge surprenant sur les listes | Documentation explicite ("listes remplacées, pas concaténées") + test dédié. Comportement standard pour la plupart des merge libs. |

## 8. Critères d'acceptation

- [ ] Module `services/swarm_defaults.py` créé avec `_DEFAULT_DEPLOY`, `deep_merge`, `resolve_deploy`
- [ ] 7 tests unitaires sur `swarm_defaults` verts
- [ ] `_build_group_context` produit `svc.deploy` résolu pour chaque service
- [ ] `_JINJA_ENV` enregistre le filtre `to_yaml`
- [ ] Template `seed-default-compose/fr.sh.j2` réécrit pour Swarm (driver overlay, ports long-form, deploy block, etc.)
- [ ] Tests existants sur `compose_renderer_service` adaptés aux nouvelles attentes
- [ ] Smoke test : `_build_group_context` + `render_group_compose` sur un projet exemple → output validé manuellement contre la spec Swarm
- [ ] Aucune régression sur `render_for_runtime`
- [ ] Lint backend clean (`ruff check`)

## 9. Hors scope (rappel)

- Path A2 (`render_for_runtime` SaaS) — chantier suivant
- Bloc `secrets:` Swarm — itération future
- UI admin pour éditer le `deploy:` du recipe — passe par l'éditeur YAML existant
- Migration des recipes existants pour leur ajouter un `deploy:` — optionnel, defaults font le job
- Configurabilité des defaults via `platform_config` — option B rejetée
- Ressources limits/reservations dans les defaults — workload-dépendant, à déclarer par recipe
- Refacto `container_runner.py` (chantier B distinct, agents lifecycle Swarm)

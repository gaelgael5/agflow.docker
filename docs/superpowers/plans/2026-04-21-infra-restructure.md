# Infra — Restructure complète du référentiel (Migrations 064→069)

## Context

Le module Infrastructure livré en M8 (voir `2026-04-19-m8-infrastructure-registry.md`) reposait sur trois concepts :

- **Types** (`infra_types`) — dictionnaire nom → catégorie (`Proxmox` = platform, `LXC` = service)
- **Serveurs** (`infra_servers`) — hôtes SSH accessibles (plateformes de provisioning)
- **Machines** (`infra_machines`) — ressources K3s-ables, provisionnées depuis un serveur parent

Plusieurs frottements sont apparus à l'usage :

1. **Dualité `infra_servers` / `infra_machines` inutile** — les deux tables partagent 9 colonnes (host, port, user, password, cert_id, parent_id…) et ne divergent qu'autour du suivi d'install. La séparation complique le code et l'UI pour une réalité fonctionnelle unique : une machine SSH-accessible, parfois parente d'une autre.
2. **Définitions disque** — `backend/data/platforms/*.json` et `backend/data/services/*.json` étaient chargées par `types_loader.py` au démarrage. Impossible de configurer via UI, modèle opaque, pas de référencement relationnel propre depuis les machines.
3. **Dropdown type filtré sur `platform`** — impossible de créer un serveur LXC standalone.
4. **Disposition du dispatching post-exécution** — `_auto_provision` était hardcodé sur `action_name == "create"`, peu extensible.

Cette restructure se déploie en 6 migrations successives (064 à 069), chacune préservant `infra_certificates` et les catégories existantes.

## Décisions d'architecture

| Sujet | Décision |
|-------|----------|
| Tables infra | Fusionnées en `infra_machines` unique |
| Historique d'exécutions | Nouvelle table `infra_machines_runs` (machine_id, action_id, started_at, finished_at, success, exit_code, error_message) |
| Variantes typées | Nouvelle table `infra_named_types` — `(name, type_id, sub_type_id, connection_type)` — remplace les JSON disque |
| URLs d'actions | Nouvelle table `infra_named_type_actions` — `(named_type_id, category_action_id, url)` |
| Référence type sur machines | `machines.type_id UUID → infra_named_types.id` (variante, pas type de base) |
| FK `type_id` et `sub_type_id` sur named_types | Vers `infra_categories(name)` (VARCHAR) — décision finale en 067 après 2 itérations |
| `sub_type_id` | Auto-référence vers `infra_named_types.id` (depuis 068) — pointe vers la variante enfant à provisionner |
| Catégories | Colonne `is_vps BOOLEAN` ajoutée (065) pour distinguer plateformes de virtualisation (Proxmox) des services |
| Disque | JSON `platforms/*.json` et `services/*.json` supprimés, `types_loader.py` supprimé |
| `infra_types` | Droppée en 069 — plus d'intermédiaire entre catégorie et variante |
| `creation_url` sur named_types | Supprimée en 068 — l'action `create` devient une action de catégorie normale |
| Données existantes | Wipées (sauf `infra_certificates`) — utilisateur recrée via UI |

## Les 6 migrations

### 064 — `infra_restructure.sql` (la refonte principale)

- **Drop** `infra_machine_metadata` (les metadata passent en JSONB inline sur machines)
- **Drop** l'ancienne `infra_machines`
- **Delete** + **rename** `infra_servers` → `infra_machines`
- **Drop+recrée** `infra_types` en PK UUID (était VARCHAR `name`)
- **Crée** `infra_named_types`, `infra_named_type_actions`, `infra_machines_runs`
- **Ajoute** `infra_machines.type_id UUID → infra_named_types.id` (remplace l'ancienne colonne `type` VARCHAR)
- **Ajoute** `groups.machine_id UUID → infra_machines.id` (la colonne `server_id` avait été dropée en 057)
- **Reset** `project_deployments.group_servers = '{}'::jsonb` (IDs orphelins)
- Indexes + triggers `set_updated_at`

### 065 — `infra_categories_vps.sql`

- `ALTER TABLE infra_categories ADD COLUMN is_vps BOOLEAN NOT NULL DEFAULT false`
- Permet de distinguer les catégories « hébergeurs » (Proxmox, VMware) des catégories « services » (LXC, Docker)
- Le flag pilote la visibilité du champ `sub_type_id` dans la page Variantes et le filtre du dropdown sub_type

### 066 — `named_types_name_and_sub_type.sql`

- Ajoute `infra_named_types.name VARCHAR NOT NULL DEFAULT ''` (label humain de la variante, ex. "Proxmox-DC1")
- Change `sub_type_id` : était auto-ref vers `infra_named_types` → passe à `infra_types(id)` (itération intermédiaire, annulée en 068)

### 067 — `named_types_refs_categories.sql`

- `type_id` et `sub_type_id` passent de UUID(`infra_types.id`) à VARCHAR(`infra_categories.name`)
- Simplifie le modèle : plus d'intermédiaire `infra_types`. Une variante référence directement une catégorie.

### 068 — `named_types_subtype_self_ref.sql`

- `sub_type_id` repasse en auto-référence UUID vers `infra_named_types.id`
- **Drop** `infra_named_types.creation_url` — l'action `create` devient une action de catégorie standard avec URL stockée dans `infra_named_type_actions`
- Le dispatch post-exécution se base désormais sur le **tag `add_node`** du manifest (voir plan `2026-04-22-machine-actions-tag-dispatch.md`), plus sur `action_name == "create"`

### 069 — `drop_infra_types.sql`

- `DROP TABLE infra_types CASCADE`
- Plus aucune référence après 067/068. Le concept `infra_types` est redondant avec `infra_categories` + `infra_named_types`.

## Schéma final

```
infra_categories(name PK, is_vps)
       ↑ ON UPDATE CASCADE ON DELETE RESTRICT
infra_named_types(id PK, name, type_id→categories, sub_type_id→self, connection_type)
       ↑ ON DELETE RESTRICT (machines) / CASCADE (actions)
infra_machines(id PK, name, type_id→named_types, host, port, username, password,
               certificate_id→certs, metadata JSONB, status, parent_id→self)
       ↑ ON DELETE CASCADE
infra_machines_runs(id, machine_id, action_id→named_type_actions,
                    started_at, finished_at, success, exit_code, error_message)

infra_category_actions(id PK, category→categories, name) — pivot
infra_named_type_actions(id, named_type_id, category_action_id, url)
```

## Fichiers backend

### Nouveaux
- `services/infra_machines_service.py` (remplace `infra_servers_service.py`)
- `services/infra_named_types_service.py`
- `services/infra_named_type_actions_service.py`
- `services/infra_machines_runs_service.py`
- `api/infra/machines.py` (remplace `servers.py`)
- `api/infra/named_types.py`
- `api/infra/named_type_actions.py`

### Supprimés
- `services/infra_servers_service.py`, `services/types_loader.py`
- `api/infra/servers.py`, `api/infra/platforms.py`, `api/infra/services.py`, `api/infra/types.py`
- `backend/data/platforms/proxmox.json`, `backend/data/services/lxc.json`

### Modifiés
- `schemas/infra.py` — ajoute CategoryRow.is_vps, NamedTypeRow/Create/Update, MachineRow avec type_name + category dérivés, MachineRunRow
- `api/infra/categories.py` — colonne is_vps + PATCH endpoint
- `api/admin/project_deployments.py` — passe de `server_id` à `machine_id` + le flux push utilise `infra_machines_service`
- `main.py` — routers renommés

## Fichiers frontend

### Nouveaux
- `pages/InfraMachinesPage.tsx` (remplace `InfraServersPage.tsx`)
- `pages/InfraNamedTypesPage.tsx`
- `pages/InfraCategoriesPage.tsx` (remplace `InfraTypesPage.tsx` — la page est renommée conceptuellement en 069)

### Modifiés
- `lib/infraApi.ts` — InfraCategory.is_vps, InfraNamedType.name + sub_type_id UUID, InfraNamedTypeAction, MachineSummary.type_name + category, MachineRun
- `hooks/useInfra.ts` — useInfraNamedTypes, useInfraNamedTypeActions, useInfraMachinesRuns (suppression de useInfraTypes)
- `pages/ProjectDetailPage.tsx` — sélecteur serveur devient sélecteur machine
- `components/layout/Sidebar.tsx` — lien Types → Catégories, ajout Variantes typées et Machines
- `App.tsx` — routes mises à jour
- `i18n/fr.json`, `i18n/en.json` — labels machines, named_types, runs, category_vps

## Changements sur `_auto_provision`

Le handler `_auto_provision` existait en M8 pour parser la sortie JSON d'un script `create` et auto-créer la machine enfant. Avec la restructure :

- Il prend son type depuis `parent.named_type.sub_type_id` (directement une variante UUID depuis 068)
- Il est renommé `_handle_add_node` dans `2026-04-22-machine-actions-tag-dispatch.md`

## Vérification end-to-end

```bash
# Sur LXC 201
docker compose -f docker-compose.prod.yml logs backend | grep migrations.apply
# Doit montrer 064 à 069 appliquées

docker exec agflow-postgres psql -U agflow -d agflow -c "\dt infra_*"
# Doit lister 7 tables : infra_categories, infra_category_actions, infra_certificates,
# infra_machines, infra_machines_runs, infra_named_type_actions, infra_named_types
```

Scénario UI après déploiement :
1. `/admin/infra/categories` — créer `Proxmox` (category, is_vps=true) et `LXC` (category, is_vps=false)
2. Ajouter les actions de catégorie : `create` + `destroy` pour Proxmox, `install` pour LXC
3. `/admin/infra/named-types` — créer variante `Proxmox-DC1` (type=Proxmox, sub_type=LXC-Prod, connection=SSH), puis `LXC-Prod` (type=LXC, connection=SSH)
4. Ajouter les URLs d'action sur chaque variante
5. `/admin/infra/machines` — créer une machine Proxmox → lancer l'action `create` → vérifier qu'une machine LXC enfant est provisionnée automatiquement et apparaît en dessous dans la liste

## Notes / risques

- **Données wipées** : toute donnée infra existante (sauf certificats, catégories, actions de catégories) est perdue. L'utilisateur a explicitement accepté.
- **Règle de memory respectée** : aucune migration ne seed de ligne dans `infra_categories`, `infra_named_types` ou leurs enfants — tout vient de l'UI.
- **Script `deploy.sh`** : `tar xzf` écrase mais ne supprime pas → ce déploiement nécessite un cleanup distant des anciens fichiers (`InfraServersPage.tsx`, `InfraTypesPage.tsx`, `api/infra/servers.py`, etc.). Voir notes dans le script pour amélioration future.

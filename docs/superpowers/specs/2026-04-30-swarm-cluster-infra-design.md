# Spec — Modélisation Swarm cluster + ingestion machines (Chantier B0)

> **Statut** : design validé 2026-04-30 — prêt pour le plan d'implémentation
> **Auteur** : brainstorming Claude + utilisateur
> **Initiative parente** : préparer la migration agflow.docker → Docker Swarm. B0 est le prérequis du chantier B (lancement agents Swarm) — il pose le modèle DB et les actions infra qui permettront ensuite de cibler un cluster spécifique.

## 1. Contexte

Aujourd'hui le module M8 Infra modélise des **machines** (`infra_machines`) avec un type (`infra_named_types`) et des actions par catégorie (`infra_category_actions` × `infra_named_type_actions`). Pas de notion de cluster Swarm.

Pour pouvoir lancer des agents agflow.docker dans un Swarm cible, on a besoin de :

1. **Phase 1** — Enrichir le modèle `infra_machines` pour absorber le JSON retourné par les scripts ops de création de LXC (statut, distro, version Docker, prêt-pour-Swarm, etc.)
2. **Phase 2** — Ajouter une entité `infra_swarm_clusters` (cluster Swarm comme citoyen de premier rang), une relation `machine ∈ cluster + role`, et 3 actions sur les LXC Swarm-ready : `swarm_init`, `swarm_join`, `swarm_leave`.

Le chantier suivant (B1+) utilisera ce modèle pour cibler un cluster Swarm spécifique au moment du lancement d'un agent.

**Hors scope de B0** :
- Scripts ops eux-mêmes (vivent dans le repo Configurations, pas dans agflow.docker)
- Lancement d'agents Swarm (chantier B1)
- Refacto `container_runner.py` (chantier B2+)
- Refacto des `group_scripts` post-template-Jinja pour passer en `docker stack deploy` au lieu de `docker compose up` (chantier B-stack distinct)

## 2. Décisions verrouillées

| Sujet | Choix | Raison |
|---|---|---|
| Promotion vs JSONB | **8 colonnes 1st-class** sur `infra_machines` (cf. §4.2) | Filtrage SQL, type contraint, list view simple |
| SSH key persistée | **Clé du user `agflow` uniquement** (pas root) | Moindre privilège, sudo NOPASSWD couvre les besoins |
| Statut machine dérivé | `'ready'` si `docker_ok && ip_type valide` sinon `'partial'` | Lisible, pas de field redondant |
| Cluster Swarm modélisation | **Table dédiée** `infra_swarm_clusters` | Multi-cluster supporté, intégrité référentielle, listing par cluster |
| Tokens Swarm | **Chiffrés Fernet** via `crypto_service` existant | Cohérent avec `infra_certificates` |
| Rôle dans le cluster | Colonne `swarm_node_role` sur `infra_machines` (`manager`/`worker`/NULL) | Sémantique explicite, contrainte CHECK |
| Actions Swarm | Sous catégorie `service` (LXC est service) — `swarm_init`, `swarm_join`, `swarm_leave` | Réutilise le mécanisme `infra_named_type_actions` existant |
| Contrat scripts ops | **JSON-only** (cf. §6) — exit_code 0/2 + status ok/partial | Standard machine-readable, parse asyncpg trivial |

## 3. Architecture

```
┌─ UI Infra ─────────────────────────────────────────────────────────────┐
│ Liste machines + détail machine + page Swarm Clusters                  │
│ Boutons d'action : "Init Swarm cluster", "Join cluster", "Leave"       │
└──────────────────────────────────────────────────────────────────────────┘
                                  ↓ POST /api/admin/infra/machines/{id}/actions/{action}
┌─ Backend FastAPI ──────────────────────────────────────────────────────┐
│ api/admin/infra/machines.py                                             │
│   POST /machines/{id}/actions/swarm_init    → swarm_actions_service     │
│   POST /machines/{id}/actions/swarm_join    → swarm_actions_service     │
│   POST /machines/{id}/actions/swarm_leave   → swarm_actions_service     │
│                                                                          │
│ services/swarm_actions_service.py (NOUVEAU)                              │
│   - init_cluster(machine_id, cluster_name)                              │
│   - join_cluster(machine_id, cluster_id, role)                          │
│   - leave_cluster(machine_id)                                           │
│   utilise ssh_executor + crypto_service + infra_machines_runs           │
│                                                                          │
│ services/infra_swarm_clusters_service.py (NOUVEAU)                       │
│   - CRUD sur infra_swarm_clusters                                       │
│   - get_decoded_tokens(cluster_id)  # déchiffre Fernet à la demande     │
│                                                                          │
│ services/infra_machines_service.py (MODIFIÉ)                             │
│   - ingest_creation_output(machine_id, json) → met à jour les colonnes  │
│     1st-class et les fields metadata                                    │
└──────────────────────────────────────────────────────────────────────────┘
                                  ↓ ssh_executor.exec_command (asyncssh)
┌─ Scripts ops (Configurations repo, hors scope) ────────────────────────┐
│ create-swarm-lxc.sh   → JSON {identification, systeme, docker, swarm,..}│
│ init-swarm-node.sh    → JSON {swarm: {cluster_name, manager_addr, ...}} │
│ join-swarm-node.sh    → JSON {swarm: {joined, node_id}}                 │
│ leave-swarm-node.sh   → JSON {swarm: {left: true}}                      │
└──────────────────────────────────────────────────────────────────────────┘
```

## 4. Modifications de schéma DB

Migration `087_swarm_clusters.sql` (nouvelle, après `086_workflow_orchestration.sql`).

### 4.1 Nouvelle table `infra_swarm_clusters`

```sql
CREATE TABLE infra_swarm_clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR NOT NULL UNIQUE,
    manager_addr VARCHAR NOT NULL,
    join_token_worker_encrypted TEXT NOT NULL,
    join_token_manager_encrypted TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_infra_swarm_clusters_updated_at
    BEFORE UPDATE ON infra_swarm_clusters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

### 4.2 Extension `infra_machines` — colonnes 1st-class

```sql
ALTER TABLE infra_machines
    ADD COLUMN ctid INTEGER,                          -- LXC id Proxmox (identification.ctid)
    ADD COLUMN distro VARCHAR(64),                    -- systeme.distro
    ADD COLUMN ip_type VARCHAR(16),                   -- systeme.ip_type ("static" | "dhcp")
    ADD COLUMN docker_version VARCHAR(32),            -- docker.docker_version
    ADD COLUMN compose_version VARCHAR(32),           -- docker.compose_version
    ADD COLUMN swarm_ready BOOLEAN NOT NULL DEFAULT FALSE,  -- swarm.swarm_ready
    ADD COLUMN swarm_mode VARCHAR(16),                -- swarm.swarm_mode ("inactive"|"active")
    ADD COLUMN tun_device_present BOOLEAN,            -- swarm.tun_device_present (overlay support)
    ADD COLUMN swarm_cluster_id UUID REFERENCES infra_swarm_clusters(id) ON DELETE SET NULL,
    ADD COLUMN swarm_node_role VARCHAR(16);

ALTER TABLE infra_machines
    ADD CONSTRAINT swarm_node_role_chk
    CHECK (swarm_node_role IN ('manager', 'worker') OR swarm_node_role IS NULL);

-- Cohérence : pas de role sans cluster, pas de cluster sans role
ALTER TABLE infra_machines
    ADD CONSTRAINT swarm_membership_consistent_chk
    CHECK ((swarm_cluster_id IS NULL AND swarm_node_role IS NULL)
        OR (swarm_cluster_id IS NOT NULL AND swarm_node_role IS NOT NULL));

CREATE INDEX idx_infra_machines_swarm_cluster ON infra_machines (swarm_cluster_id) WHERE swarm_cluster_id IS NOT NULL;
```

### 4.3 Seed : 3 nouvelles `infra_category_actions`

```sql
INSERT INTO infra_category_actions (category, name, is_required) VALUES
    ('service', 'swarm_init',  FALSE),
    ('service', 'swarm_join',  FALSE),
    ('service', 'swarm_leave', FALSE)
ON CONFLICT (category, name) DO NOTHING;
```

> Les 3 actions ne sont **pas** required (`is_required=FALSE`) — elles sont conditionnelles selon `swarm_ready` et `swarm_cluster_id` de la machine.

## 5. Mapping JSON création de LXC → DB

Le script ops `create-swarm-lxc.sh` retourne ce JSON :

```json
{
  "status": "ok|partial",
  "exit_code": 0,
  "identification": { "ctid": 300, "hostname": "swarm1-mgr", "hostname_raw": "swarm1-mgr" },
  "ressources":     { "storage": "20G" },
  "systeme":        { "distro": "debian-12", "ip": "192.168.10.300", "ip_type": "static" },
  "ssh_root":       { "private_key_path": "...", "public_key_path": "...", "public_key": "...", "login_method": "key-only" },
  "users": [
    { "user": "agflow", "password": "...", "ssh_key_private_path": "...", "ssh_key_public_path": "...",
      "ssh_key_public": "...", "groups": ["sudo", "docker"], "sudo_nopasswd": true }
  ],
  "docker": { "docker_ok": true, "docker_version": "29.4", "compose_version": "5.1", "hello_world_ok": true },
  "swarm":  { "swarm_mode": "inactive", "swarm_ready": true, "tun_device_present": true },
  "host":   { "proxmox_host": "pve", "created_at": "...", "script_version": "1.0", "conf_path": "...", "conf_backup_path": "..." }
}
```

### Mapping ingestion (`ingest_creation_output`)

| Champ JSON | Cible DB | Notes |
|---|---|---|
| `identification.hostname` | `infra_machines.name` | Nom affiché UI |
| `identification.ctid` | `infra_machines.ctid` | INTEGER |
| `systeme.ip` | `infra_machines.host` | Adresse SSH |
| `systeme.distro` | `infra_machines.distro` | VARCHAR(64) |
| `systeme.ip_type` | `infra_machines.ip_type` | VARCHAR(16) |
| `users[0].user` | `infra_machines.username` | "agflow" — plus root |
| `users[0].ssh_key_private_path` (lecture du fichier côté Proxmox host via SSH, contenu chiffré Fernet) | nouvelle ligne `infra_certificates` → `infra_machines.certificate_id` | clé privée seule chiffrée |
| `users[0].ssh_key_public` | `infra_certificates.public_key` | clair |
| `docker.docker_version` | `infra_machines.docker_version` | VARCHAR(32) |
| `docker.compose_version` | `infra_machines.compose_version` | VARCHAR(32) |
| `swarm.swarm_ready` | `infra_machines.swarm_ready` | BOOLEAN |
| `swarm.swarm_mode` | `infra_machines.swarm_mode` | VARCHAR(16) |
| `swarm.tun_device_present` | `infra_machines.tun_device_present` | BOOLEAN |
| `host.proxmox_host` | `infra_machines.parent_id` | Résolution par nom/IP du Proxmox host (existing machine) |
| `status` (JSON top-level) → dérivation | `infra_machines.status` | `'ready'` si `docker.docker_ok && systeme.ip_type IN ('static','dhcp')`, sinon `'partial'` |
| `ressources.storage`, `host.script_version`, `host.conf_path`, `host.conf_backup_path`, `users[0].groups`, `users[0].sudo_nopasswd`, `docker.hello_world_ok` | `infra_machines.metadata` JSONB | flexibilité, traces non filtrables |

> **Note importante** : le JSON contient **2 paires de clés** (`ssh_root.*` et `users[0].*`). On ne stocke QUE celle d'`agflow`. La clé root n'a pas vocation à être réutilisée par le backend (tout passe par `agflow` + sudo).

## 6. Contrats JSON des scripts ops (Phase 2)

### 6.1 `init-swarm-node.sh --init --name <cluster_name>`

Initialise un nouveau cluster Swarm sur le LXC cible.

```json
{
  "status": "ok|partial",
  "exit_code": 0,
  "swarm": {
    "cluster_name": "swarm1",
    "manager_addr": "192.168.10.300:2377",
    "join_token_worker": "SWMTKN-1-...",
    "join_token_manager": "SWMTKN-1-..."
  }
}
```

Backend après réception :
1. INSERT `infra_swarm_clusters` (name, manager_addr, tokens chiffrés Fernet)
2. UPDATE `infra_machines` SET `swarm_cluster_id = ...`, `swarm_node_role = 'manager'`, `swarm_mode = 'active'`
3. INSERT `infra_machines_runs` (machine_id, action_id, success=true, ...)

### 6.2 `init-swarm-node.sh --join --manager <addr> --token <token> [--manager-role]`

Rejoint un cluster existant.

```json
{
  "status": "ok|partial",
  "exit_code": 0,
  "swarm": {
    "joined": true,
    "node_id": "x9k...",
    "role": "worker|manager"
  }
}
```

Backend après réception :
1. UPDATE `infra_machines` SET `swarm_cluster_id = <cluster cible>`, `swarm_node_role = <role>`, `swarm_mode = 'active'`
2. INSERT `infra_machines_runs`

### 6.3 `init-swarm-node.sh --leave [--force]`

Retire la machine du cluster.

```json
{
  "status": "ok|partial",
  "exit_code": 0,
  "swarm": {
    "left": true
  }
}
```

Backend après réception :
1. SAUVEGARDE temp : `cluster_id_was = m.swarm_cluster_id`
2. UPDATE `infra_machines` SET `swarm_cluster_id = NULL`, `swarm_node_role = NULL`, `swarm_mode = 'inactive'`
3. Si la machine était le **dernier node** du cluster : DELETE `infra_swarm_clusters` (cascade SET NULL via FK)
4. INSERT `infra_machines_runs`

## 7. Endpoints API (à créer)

```
GET  /api/admin/infra/swarm-clusters                    Liste les clusters + count nodes
GET  /api/admin/infra/swarm-clusters/{id}               Détail cluster + liste de ses nodes
POST /api/admin/infra/machines/{id}/actions/swarm_init  body: {cluster_name}
POST /api/admin/infra/machines/{id}/actions/swarm_join  body: {cluster_id, role}
POST /api/admin/infra/machines/{id}/actions/swarm_leave body: {} (ou {force: true})
```

> **Tokens Swarm jamais retournés en clair par l'API**. Les déchiffrements Fernet ne se font qu'**en mémoire** au moment du `swarm_join` (lecture token → SSH → script ops). Pas d'endpoint "give me the token", trop sensible.

## 8. UI/Frontend

### 8.1 Page existante "Infrastructure → Machines"

Ajout :
- Colonne **Swarm** : badge "manager swarm1" / "worker swarm2" / "—"
- Boutons d'action **conditionnels** sur le détail machine :
  - "Init Swarm cluster" (si `swarm_ready=true && swarm_cluster_id IS NULL`)
  - "Join cluster" (si `swarm_ready=true && swarm_cluster_id IS NULL`)
  - "Leave cluster" (si `swarm_cluster_id IS NOT NULL`)

### 8.2 Nouvelle page "Infrastructure → Swarm Clusters"

Liste tabulaire des clusters :
- Nom
- Manager addr
- Nombre de nodes (managers / workers)
- Date création
- Bouton "Voir nodes" → drill-down

Pas de bouton "Créer cluster" — les clusters sont créés via l'action `swarm_init` sur une machine.

## 9. Tests

### 9.1 Backend tests purs (pas de DB)

`backend/tests/test_swarm_clusters_service.py` :
- `ingest_creation_output` produit le bon mapping (snapshot du JSON exemple → dict colonnes attendues + metadata résiduel)
- Dérivation `status='ready'` vs `'partial'` selon `docker_ok` + `ip_type`
- Validation que les seuls champs sensibles passés à `crypto_service.encrypt` sont les tokens Fernet et la clé privée

### 9.2 Backend tests DB (intégration)

`backend/tests/test_infra_swarm_clusters_endpoint.py` :
- POST `swarm_init` → cluster créé en DB, machine liée en role manager
- POST `swarm_join` → machine liée au cluster cible avec le bon role
- POST `swarm_leave` → machine déliée, cluster supprimé si dernier node
- POST `swarm_init` sur machine déjà dans un cluster → 409 conflict
- POST `swarm_join` sur cluster inexistant → 404
- Tokens jamais retournés en clair dans les réponses API

### 9.3 Tests migrations

`backend/tests/test_migrations.py` (existant probablement) :
- Migration 087 idempotente
- CHECK constraints fonctionnent (insertion d'un role sans cluster → erreur SQL)

## 10. Points d'attention pour les ops (à transmettre)

À l'auteur du script `init-swarm-node.sh` côté Configurations :

- **Le retour DOIT être JSON sur stdout uniquement** — toute erreur sur stderr est tolérée mais l'exit_code doit refléter le succès
- **Les tokens Swarm doivent être renvoyés en clair dans le JSON** — le backend les chiffrera avant DB. Pas de tentative de chiffrement côté script.
- **Le script `--leave`** doit vérifier si c'est le dernier node du cluster (côté Swarm) et appeler `docker swarm leave --force` dans ce cas
- **Le script `--join` en mode manager** doit utiliser le manager token, pas le worker token

## 11. Hors scope

- Création/modification des scripts ops (Configurations repo)
- Lancement d'agents Swarm via `services.create` (chantier B1)
- Refacto `container_runner.py` (chantier B2+)
- Refacto `group_scripts` post-template-Jinja vers `docker stack deploy` (chantier distinct)
- Sélection automatique du cluster cible pour un agent (chantier futur, dépend de B1)
- Health checks périodiques des nodes Swarm (futur)
- UI graphique des relations cluster ↔ nodes (futur)
- Multi-manager promotion automatique (futur)

## 12. Critères d'acceptation

- [ ] Migration 087 appliquée idempotente (smoke test sur DB temp)
- [ ] Table `infra_swarm_clusters` créée avec trigger updated_at
- [ ] 9 nouvelles colonnes sur `infra_machines` (CHECK constraints OK)
- [ ] 3 actions `swarm_init`/`swarm_join`/`swarm_leave` seedées
- [ ] Service `swarm_actions_service` avec 3 endpoints fonctionnels
- [ ] `ingest_creation_output` parse le JSON exemple sans erreur, persiste correctement
- [ ] Tokens Swarm chiffrés Fernet en DB, jamais en clair en logs/réponses API
- [ ] Tests unitaires + intégration verts
- [ ] Pas de régression sur les autres tests M8 Infra

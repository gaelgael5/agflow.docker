# M8 — Infrastructure Registry — Plan d'implémentation

## Context

Module d'infrastructure : référencement de serveurs SSH, provisioning de machines (LXC, VM) via pipelines de scripts externes, installation K3s, et déploiement des instances M7 sur les nodes K3s.

## Décisions d'architecture

| Sujet | Décision |
|-------|----------|
| Convention PK | `id` (pas `_id`) |
| Stockage | Tout en BDD PostgreSQL (5 tables transactionnelles) |
| Service chiffrement | `crypto_service.py` (Fernet) |
| API | Serveur FastAPI séparé, port 8001, même codebase, même DB |
| Contrat OpenAPI | Distinct sur `:8001/docs` |
| Platforms/Services | Fichiers JSON sur disque (`data/platforms/`, `data/services/`) |
| Scripts manifests | JSON sur URL publique, pipeline séquentiel |
| Capture outputs | Convention dernière ligne stdout = JSON |
| Credentials | Chiffrés au repos (Fernet), pas zero-knowledge |

## Vue d'ensemble des 9 phases

| Phase | Titre | Tables | Services | Frontend | Complexité |
|-------|-------|--------|----------|----------|------------|
| 1 | Foundations — crypto + certificates + types | `types`, `certificates` | `crypto_service`, `certificates_service` | `InfraCertificatesPage` | Moyenne |
| 2 | Types + Platforms + Services loaders | — | `types_loader`, schemas Pydantic | `InfraTypesPage` | Moyenne |
| 3 | Servers — CRUD + test SSH | `servers` | `servers_service`, `ssh_executor` | `InfraServersPage` | Haute (asyncssh) |
| 4 | Machines — CRUD import + metadata | `machines`, `machine_metadata` | `machines_service`, `machine_metadata_service` | `InfraMachinesPage`, `MetadataPanel` | Moyenne |
| 5 | Pipeline executor + WebSocket logs | — | `script_manifest_fetcher`, `pipeline_executor`, `run_registry`, WS | `RunLogsPanel` | Haute |
| 6 | Provision + Finalize | — | intégration pipeline côté server | `ProvisionMachineDialog` | Haute |
| 7 | Install + capture metadata K3s | — | pipeline côté machine, capture JSON | `InstallMachineDialog`, badges | Haute |
| 8 | Destroy + lien M7 (deploy K3s) | — | `m7_k3s_deployer` | `DeployToMachineDialog` | Très haute |
| 9 | Discovery LXC (optionnel) | — | SSH + list LXC | import bulk | Moyenne |

## Fichiers à créer

### Backend — nouveau serveur FastAPI

```
backend/src/agflow/
├── infra_app.py                           # FastAPI app infra (port 8001)
├── services/
│   ├── crypto_service.py                  # Fernet encrypt/decrypt
│   ├── types_loader.py                    # Scan disque + sync vs table types
│   ├── script_manifest_fetcher.py         # Fetch URL + cache
│   ├── pipeline_executor.py              # Exécution séquentielle + parse JSON
│   ├── servers_service.py                # CRUD (existe déjà pour discovery — renommer)
│   ├── infra_servers_service.py          # CRUD servers infra
│   ├── infra_machines_service.py         # CRUD + provision + install + destroy
│   ├── machine_metadata_service.py       # CRUD metadata + chiffrement granulaire
│   ├── infra_certificates_service.py     # CRUD certificates
│   ├── ssh_executor.py                   # Wrapper asyncssh
│   ├── run_registry.py                   # In-memory registry des runs pour WS
│   └── m7_k3s_deployer.py               # Charge kubeconfig + kubectl apply
├── api/infra/
│   ├── types.py
│   ├── platforms.py
│   ├── services.py
│   ├── servers.py
│   ├── machines.py
│   ├── machine_metadata.py
│   ├── certificates.py
│   └── ws_run_logs.py
```

### Backend — migrations

```
backend/migrations/
└── 049_m8_infrastructure.sql              # types + certificates + servers + machines + machine_metadata + triggers
```

### Backend — données disque

```
backend/data/
├── platforms/
│   └── proxmox.json
└── services/
    └── lxc.json
```

### Frontend

```
frontend/src/
├── lib/infraApi.ts
├── hooks/useInfra.ts
└── pages/
    ├── InfraServersPage.tsx
    ├── InfraMachinesPage.tsx
    ├── InfraCertificatesPage.tsx
    └── InfraTypesPage.tsx
```

### Docker

```
docker-compose.prod.yml                    # Ajouter service infra-backend sur port 8001
backend/Dockerfile                         # (partagé, même image, entrypoint différent)
```

## Dépendances Python à ajouter

```toml
"asyncssh>=2.14",
"cryptography>=41.0",
"kubernetes-asyncio>=29.0",      # Phase 8 seulement
```

## Phase 1 — Foundations (crypto + certificates + table types)

### Task 1: Migration SQL

**Files:**
- Create: `backend/migrations/049_m8_infrastructure.sql`

Les 5 tables + triggers + index + seed types. Une seule migration pour tout M8 (les tables sont interdépendantes).

### Task 2: Service crypto_service.py

**Files:**
- Create: `backend/src/agflow/services/crypto_service.py`

Fernet encrypt/decrypt. Clé depuis `AGFLOW_INFRA_KEY` (env var). Fonctions :
- `encrypt(plaintext) → ciphertext`
- `decrypt(ciphertext) → plaintext`
- `is_sensitive_key(key) → bool` (détection convention : token, key, secret, password, kubeconfig)

### Task 3: Schemas Pydantic infra

**Files:**
- Create: `backend/src/agflow/schemas/infra.py`

Types, Certificates, Servers, Machines, MachineMetadata — tous les DTOs dans un seul fichier (comme `products.py`).

### Task 4: Service certificates

**Files:**
- Create: `backend/src/agflow/services/infra_certificates_service.py`

CRUD asyncpg. Private key chiffrée via crypto_service à l'INSERT/UPDATE, jamais retournée en clair dans les Summary.

### Task 5: App FastAPI infra (port 8001)

**Files:**
- Create: `backend/src/agflow/infra_app.py`
- Modify: `docker-compose.prod.yml` — ajouter service infra-backend

Nouveau `FastAPI()` avec ses propres routers, lifespan (pool DB partagé), serveur uvicorn sur :8001.

### Task 6: Router certificates + types

**Files:**
- Create: `backend/src/agflow/api/infra/certificates.py`
- Create: `backend/src/agflow/api/infra/types.py`

### Task 7: Frontend — InfraCertificatesPage + InfraTypesPage

**Files:**
- Create: `frontend/src/lib/infraApi.ts`
- Create: `frontend/src/hooks/useInfra.ts`
- Create: `frontend/src/pages/InfraCertificatesPage.tsx`
- Create: `frontend/src/pages/InfraTypesPage.tsx`
- Modify: `frontend/src/App.tsx` — routes
- Modify: `frontend/src/components/layout/Sidebar.tsx` — section Infrastructure
- Modify: `frontend/src/i18n/fr.json` + `en.json`

### Task 8: Lint + TypeScript + deploy + test

## Phases suivantes (résumé)

### Phase 2 — Types + Platforms + Services loaders
- `types_loader.py` : scan `data/platforms/*.json` + `data/services/*.json`
- Endpoints GET platforms/services (lecture disque)
- Fichiers exemples `proxmox.json` + `lxc.json`

### Phase 3 — Servers CRUD + test SSH
- `infra_servers_service.py` : CRUD avec password chiffré
- `ssh_executor.py` : wrapper asyncssh
- Endpoint test-connection
- `InfraServersPage` + `ServerFormDialog`

### Phase 4 — Machines CRUD + metadata
- `infra_machines_service.py` : CRUD basique (import manuel)
- `machine_metadata_service.py` : CRUD + chiffrement granulaire
- `InfraMachinesPage` + `MetadataPanel`

### Phase 5 — Pipeline executor + WebSocket
- `script_manifest_fetcher.py` : fetch URL + cache 5min
- `pipeline_executor.py` : exécution séquentielle + parse JSON stdout
- `run_registry.py` : in-memory registry des runs
- WS endpoint `/runs/{id}/logs`
- `RunLogsPanel` avec progress bar

### Phase 6 — Provision + Finalize
- Endpoints provision + finalize
- `ProvisionMachineDialog` avec formulaire dynamique
- Intégration pipeline_executor côté server

### Phase 7 — Install + capture metadata K3s
- Endpoint install
- Pipeline service côté machine
- Capture JSON stdout → machine_metadata
- Mise à jour install_status/step/total
- Badges UI + InstallMachineDialog

### Phase 8 — Destroy + M7 deploy K3s
- Pipeline destroy
- `m7_k3s_deployer.py` : kubeconfig + kubernetes-asyncio
- Endpoint deploy/undeploy
- `DeployToMachineDialog`

### Phase 9 — Discovery LXC (optionnel)
- SSH dans Proxmox + list LXC
- Import bulk

## Vérification Phase 1

1. Migration appliquée — 5 tables créées
2. `crypto_service` — encrypt/decrypt fonctionnel
3. CRUD certificates via API `:8001`
4. Private key jamais retournée en clair dans les réponses API
5. Table types contient `Proxmox` (platform) et `LXC` (service)
6. Frontend : pages Certificates + Types visibles
7. Sidebar : nouvelle section Infrastructure

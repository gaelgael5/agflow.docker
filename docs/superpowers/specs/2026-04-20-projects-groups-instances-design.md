# Projets, Groupes, Instances — Migration PostgreSQL

> **Date** : 2026-04-20
> **Statut** : Validé
> **Scope** : Migration projets/instances du filesystem vers PostgreSQL + ajout groupes logiques

## Contexte

Les projets et instances sont aujourd'hui stockés en fichiers JSON sur disque (`data/projects/`). Ce sont des données transactionnelles qui doivent être en base. Le catalogue produit (YAML) reste sur disque — c'est de la config.

On ajoute le concept de **groupe logique** entre projet et instance : un groupe rassemble des instances qui seront déployées ensemble et définit combien d'agents Docker peuvent être instanciés dessus.

## Modèle de données

```
Projet (logique)
  └─ Groupe (logique)     — nom, max_agents
       ├─ Instance A       — produit du catalogue + variables
       ├─ Instance B       — produit du catalogue + variables
       └─ [slots agents: max_agents]
```

### Tables SQL

```sql
CREATE TABLE projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    environment     VARCHAR(20) NOT NULL DEFAULT 'dev'
                    CHECK (environment IN ('dev', 'staging', 'prod')),
    tags            JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            VARCHAR(200) NOT NULL,
    max_agents      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(project_id, name)
);

CREATE TABLE instances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id        UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    instance_name   VARCHAR(128) NOT NULL,
    catalog_id      VARCHAR(128) NOT NULL,
    variables       JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(20) NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'active', 'stopped')),
    service_url     VARCHAR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(group_id, instance_name)
);
```

### Cascades
- Supprimer un projet → cascade groupes → cascade instances
- Supprimer un groupe → cascade instances

### Triggers
- `updated_at` auto-update sur les 3 tables

## Backend

### Services (asyncpg, plus de filesystem)

**`projects_service.py`** — réécrit
- `list_all()` → `SELECT * FROM projects ORDER BY display_name`
- `get_by_id(id)` → `SELECT WHERE id = $1`
- `create(display_name, description, environment, tags)`
- `update(id, **kwargs)`
- `delete(id)` → `DELETE CASCADE`

**`groups_service.py`** — nouveau
- `list_by_project(project_id)` → `SELECT WHERE project_id = $1 ORDER BY name`
- `get_by_id(id)`
- `create(project_id, name, max_agents)`
- `update(id, **kwargs)`
- `delete(id)` → `DELETE CASCADE`

**`product_instances_service.py`** — réécrit
- `list_by_group(group_id)` → `SELECT WHERE group_id = $1 ORDER BY instance_name`
- `list_by_project(project_id)` → `JOIN groups` pour lister toutes les instances d'un projet
- `get_by_id(id)`
- `create(group_id, instance_name, catalog_id, variables)`
- `update(id, **kwargs)`
- `update_status(id, status, service_url)`
- `delete(id)`

### Routers

**`admin/projects.py`** — adapté pour asyncpg
- `GET /api/admin/projects`
- `POST /api/admin/projects`
- `GET /api/admin/projects/{id}`
- `PUT /api/admin/projects/{id}`
- `DELETE /api/admin/projects/{id}`

**`admin/groups.py`** — nouveau
- `GET /api/admin/groups?project_id={id}`
- `POST /api/admin/groups`
- `GET /api/admin/groups/{id}`
- `PUT /api/admin/groups/{id}`
- `DELETE /api/admin/groups/{id}`

**`admin/product_instances.py`** — adapté
- `GET /api/admin/product-instances?group_id={id}`
- `POST /api/admin/product-instances`
- `GET /api/admin/product-instances/{id}`
- `PUT /api/admin/product-instances/{id}`
- `DELETE /api/admin/product-instances/{id}`
- `POST /api/admin/product-instances/{id}/activate`
- `POST /api/admin/product-instances/{id}/stop`

## Frontend

### Renommages
- "Projets" → "Projets (logique)" dans la sidebar
- "Instances" → supprimé de la sidebar (les instances sont dans le détail projet)

### Pages

**ProjectsPage.tsx** — liste des projets
- Tableau : display_name, environment (badge couleur), description, nombre de groupes
- Actions : créer, éditer, supprimer

**ProjectDetailPage.tsx** — nouveau, détail d'un projet
- En-tête : nom, environment, description
- Section groupes en cartes :
  - Chaque carte : nom du groupe, badge `max_agents`, liste des instances
  - Bouton "+" pour ajouter un groupe
  - Bouton "+" sur chaque groupe pour ajouter une instance
- Chaque instance : nom, produit (badge), status (badge), bouton éditer variables

**Instance variables editor**
- Dialog avec tableau key/value
- Les valeurs commençant par `${` affichent un indicateur secret
- Pas de résolution — juste la saisie

### Navigation
- `/projects` → liste des projets
- `/projects/{id}` → détail avec groupes et instances

## Ce qui disparaît
- `data/projects/` et tout son contenu filesystem
- L'ancien `projects_service.py` basé sur filesystem
- L'ancien `product_instances_service.py` basé sur filesystem
- L'entrée "Instances" dans la sidebar (intégré dans le détail projet)

## Ce qui ne change PAS
- Catalogue produit (YAML sur disque)
- `activation_service.py` (sera adapté pour utiliser les IDs de la base)
- Générateurs docker-compose (prochaine itération)
- Lien groupe → serveur cible (prochaine itération)

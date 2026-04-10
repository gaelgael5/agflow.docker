# ag.flow Admin Dashboard -- Specifications fonctionnelles detaillees

> **Version** : 2026-03-22
> **Scope** : `web/server.py` (backend FastAPI) + `web/static/` (frontend SPA)
> **Port** : **8080**
> **Container** : `langgraph-admin`

---

## Table des matieres

1. [Vue d'ensemble](#1-vue-densemble)
2. [Navigation](#2-navigation)
3. [Dashboard](#3-dashboard)
4. [Production](#4-production)
5. [Configuration](#5-configuration)
6. [Secrets (.env)](#6-secrets-env)
7. [Channels](#7-channels)
8. [Chat LLM](#8-chat-llm)
9. [Validations (HITL)](#9-validations-hitl)
10. [Utilisateurs](#10-utilisateurs)
11. [Monitoring](#11-monitoring)
12. [Scripts](#12-scripts)
13. [API Endpoints](#13-api-endpoints)
14. [Fichiers de configuration](#14-fichiers-de-configuration)
15. [Modals et popups](#15-modals-et-popups)

---

## 1. Vue d'ensemble

### 1.1 Objectif

Le dashboard admin est l'interface centrale de gestion de la plateforme ag.flow. Il permet de :

- Configurer les providers LLM, les serveurs MCP, les agents et les equipes
- Gerer deux scopes de configuration : **Production** (`config/`) et **Configuration** (`Shared/`)
- Administrer les secrets (`.env`), les channels de communication, les utilisateurs HITL
- Monitorer les containers Docker, les logs et les evenements du gateway
- Versionner les configurations via Git (commit/push/pull par scope)
- Interagir avec un LLM via un chat integre

### 1.2 Architecture

| Composant | Technologie |
|---|---|
| Backend | FastAPI (Python), fichier unique `web/server.py` (~6100 lignes) |
| Frontend | SPA HTML/JS vanilla (pas de framework), `web/static/` |
| Editeur de code | CodeMirror 5 (Dockerfiles, shell) |
| Polices | Inter (UI) + JetBrains Mono (code) |
| Theme | Dark mode uniquement (palette Slate/Blue) |
| Persistence | Fichiers JSON/Markdown sur disque + PostgreSQL (HITL, API keys) |

### 1.3 Mode Docker vs Local

Le backend detecte automatiquement s'il tourne dans Docker (`/project` existe) ou en local :

| Variable | Docker | Local |
|---|---|---|
| `PROJECT_DIR` | `/project` | `../` (parent de `web/`) |
| `CONFIGS` | `/project/config` | `../config` |
| `SHARED_DIR` | `/project/Shared` | `../Shared` |
| `ENV_FILE` | `/project/.env` | `../.env` |
| `GIT_DIR` | `/project` | `../` |

### 1.4 Authentification

**Modele** : Cookie-based session avec HMAC-SHA256.

| Aspect | Detail |
|---|---|
| Credentials | Lus depuis `.env` : `WEB_ADMIN_USERNAME` / `WEB_ADMIN_PASSWORD` |
| Si absent | Pas d'auth (acces libre) |
| Session token | `{username}:{hmac_sha256(username, secret)}` |
| Cookie | `lg_session`, httpOnly, SameSite=Lax, max-age 7 jours |
| Secret | `_AUTH_SECRET` genere aleatoirement au demarrage (`secrets.token_hex(32)`) |
| Routes publiques | `/auth/login`, `/auth/logout`, `/api/version` |
| Middleware | Toute requete non publique verifiee ; 401 JSON pour `/api/*`, page login HTML sinon |

**Flux de connexion** :

1. GET `/` → middleware detecte absence de cookie → retourne page login HTML inline
2. Utilisateur soumet username + password → POST `/auth/login`
3. Backend compare avec `secrets.compare_digest` → si OK, set cookie `lg_session`
4. Redirect vers `/` → middleware laisse passer → retourne `index.html`

**Deconnexion** : GET `/auth/logout` → supprime le cookie → redirect vers `/`

### 1.5 Version

- Lue depuis le fichier `.version` (`/project/.version` ou racine du projet)
- Endpoint `GET /api/version` retourne `{version, last_update}` (derniere date de commit git)
- Affichee dans la sidebar (`#sidebar-version`) et sur la page de login

---

## 2. Navigation

### 2.1 Structure de la sidebar

La sidebar gauche (240px, fixe) est divisee en trois sections :

**Section "Configuration"** :

| Item | `data-section` | Loader |
|---|---|---|
| Dashboard | `dashboard` | `loadDashboard()` |
| Production | `teams` | `loadTeams()` |
| Configuration | `templates` | `loadTemplates()` |
| Channels | `channels` | `loadChannels()` |
| Secrets (.env) | `secrets` | `loadEnv()` |

**Section "Outils"** :

| Item | `data-section` | Loader |
|---|---|---|
| Chat LLM | `chat` | `loadChat()` |

**Section "Operations"** :

| Item | `data-section` | Loader |
|---|---|---|
| Validations | `hitl` | `loadHitl()` |
| Utilisateurs | `users` | `loadUsers()` |
| Monitoring | `monitoring` | `loadMonitoring()` |
| Scripts | `scripts` | `loadScripts()` |

**Pied de sidebar** : Lien "Deconnexion" (`/auth/logout`)

### 2.2 Systeme de navigation

- Chaque item a un attribut `data-section` correspondant a un `<div class="section" id="section-{name}">`
- `showSection(name)` : masque toutes les sections, affiche la bonne, met en surbrillance le nav-item, et appelle le loader correspondant
- Le loader est appele a chaque changement de section (pas de cache)
- Le badge HITL (`#hitl-badge`) affiche le nombre de validations en attente en rouge

---

## 3. Dashboard

### 3.1 Vue d'ensemble

Le dashboard affiche une grille de cartes (`dashboard-grid`) avec un apercu de l'etat de la plateforme.

**Boutons d'action** :
- **Rafraichir** : recharge toutes les cartes
- **Recharger config** : envoie POST `/reload-config` au gateway pour forcer le rechargement de la configuration en memoire

### 3.2 Cartes

Les 7 cartes sont chargees en parallele via `Promise.allSettled` :

#### 3.2.1 Gateway

| API | `GET /api/monitoring/gateway` |
|---|---|
| Affichage | Pastille verte/rouge + "En ligne"/"Hors ligne" |
| Sous-titre | Version du gateway ou message d'erreur |

#### 3.2.2 Containers

| API | `GET /api/monitoring/containers` |
|---|---|
| Affichage | `{running} / {total}` containers en cours d'execution |
| Liste | Nom + status avec pastille verte (Up) ou rouge |

#### 3.2.3 Equipes

| API | `GET /api/teams` |
|---|---|
| Affichage | Nombre d'equipes |
| Liste | Nom + ID (tag bleu) |

#### 3.2.4 Agents

| API | `GET /api/agents` |
|---|---|
| Affichage | Nombre d'agents |
| Liste | 8 premiers agents (nom + LLM), "+N autres" si plus |

#### 3.2.5 Validations HITL

| API | `GET /api/hitl/stats` |
|---|---|
| Affichage | Nombre de validations en attente (valeur principale) |
| Liste | Total, Approuvees (vert), Rejetees (rouge) |

#### 3.2.6 Modeles LLM

| API | `GET /api/llm/providers` |
|---|---|
| Affichage | Nombre de providers |
| Sous-titre | Modele par defaut |
| Liste | 6 premiers providers (ID + type en tag bleu) |

#### 3.2.7 Validation de la configuration

| API | `GET /api/config/check` |
|---|---|
| Affichage | Pastille verte/jaune/rouge + nombre d'erreurs/avertissements |
| Liste | Erreurs (rouge, tag ERR) et avertissements (jaune, tag WARN) avec categorie |
| Pleine largeur | `dash-card-wide` (occupe toute la ligne) |

Les categories verifiees par `/api/config/check` :
- `secrets` : variables d'environnement manquantes/vides pour les providers LLM et MCP
- `mcp` : variables MCP non configurees
- `teams` : registry manquant, agents sans nom
- `agents` : prompts manquants, images Docker non compilees, orchestrator_prompt.md manquant
- `workflow` : agents references inexistants, livrables incomplets, transitions invalides
- `prompts` : blocs JSON invalides dans les prompts et instructions

---

## 4. Production

**Section** : `section-teams`
**Scope** : `config/` (donnees de production)

### 4.1 En-tete

- **Titre** : "Production"
- **Description** : "Configuration de production (`config/Teams/`) -- serveurs MCP et equipes operationnelles"
- **Boutons** :
  - **Rafraichir** : recharge l'onglet courant
  - **Exporter** : telecharge `config.zip` (GET `/api/export/configs`)
  - **Importer** : upload `.zip` qui remplace le contenu de `config/`

### 4.2 Sous-onglets

Navigation par onglets horizontaux (`prompt-tabs`) :

| Onglet | ID tab | Description |
|---|---|---|
| Modeles LLM | `cfg-llm` | Providers LLM de production |
| Services MCP | `cfg-mcp` | Serveurs MCP configures |
| Agents | `cfg-agents` | Catalogue agents de production |
| Equipes | `cfg-prod-teams` | Equipes operationnelles |
| Types de projet | `cfg-prod-projects` | Types de projets deployes |
| Models | `cfg-models` | Fichiers modeles de production |
| Prompts | `cfg-prompts` | Prompts systeme de production |
| Enregistrement | `cfg-git` | Git pour `config/` |

#### 4.2.1 Modeles LLM (Production)

**Fichier source** : `config/llm_providers.json`

**Carte "Modele par defaut"** :
- **Select "Modele par defaut (agents)"** : `#cfg-llm-default-select` → `PUT /api/llm/providers/default`
- **Select "LLM Admin (dashboard)"** : `#cfg-llm-admin-select` → `PUT /api/llm/providers/admin`

**Carte "Providers"** :
- **Bouton "Copier depuis Configuration"** : ouvre modal `#modal-copy-llm` listant les providers de `Shared/llm_providers.json` absents de la config
- **Bouton "Importer JSON"** : upload fichier `.json` → `POST /api/llm/providers/upload` (merge avec detection de conflits)
- **Bouton "+ Ajouter"** : ouvre modal d'ajout de provider
- **Filtre** : champ texte `#cfg-llm-filter` pour filtrer la table
- **Table** : ID, Type (tag), Modele, Description, Cle API (env_key), Actions (editer, supprimer)

**Carte "Throttling"** :
- **Bouton "+ Ajouter"** : ouvre modal avec champs env_key, RPM, TPM
- **Table** : env_key, RPM, TPM, Actions (editer, supprimer)

#### 4.2.2 Services MCP (Production)

**Fichiers source** : `config/mcp_servers.json` + `Shared/Teams/mcp_catalog.csv`

**Carte "Services avec parametres"** :
- **Bouton "Copier depuis Configuration"** : ouvre modal `#modal-copy-mcp` avec liste des serveurs de `Shared/Teams/mcp_servers.json`
- **Bouton "+ Installer un service"** : ouvre modal avec le catalogue MCP
- **Table** : pour chaque serveur installe : ID, commande, transport, etat enabled/disabled (toggle), variables env (avec statut configure/non configure), boutons (desinstaller, editer)

**Carte "Services sans parametres"** :
- Grille de cartes pour les serveurs du catalogue non installes
- **Bouton "Afficher deprecies"** : toggle visibilite des serveurs marques deprecated
- Chaque carte : nom, description, commande, bouton "Installer" en un clic

#### 4.2.3 Agents (Production)

**Fichier source** : `config/Agents/*/agent.json`

**Layout** : Split-panel (`sa-split`) :
- **Panel gauche** (`#pa-left`, 260px) : liste arborescente des agents
  - Pour chaque agent : nom, sous-items (prompt.md, identity.md, roles, missions, skills)
  - Bouton "Supprimer" dans la zone en bas
- **Panel droit** (`#pa-right`) : editeur du fichier selectionne
  - En-tete avec nom de l'agent + boutons d'action
  - Textarea pour le contenu Markdown
  - Bouton "Sauvegarder"

**Bouton "Copier depuis Configuration"** : ouvre modal `#modal-copy-agents` listant les agents de `Shared/Agents/` absents de `config/Agents/` → `POST /api/prod-agents/copy-from-config`

#### 4.2.4 Equipes (Production)

**Fichier source** : `config/teams.json` + `config/Teams/*/agents_registry.json`

**Bouton "Copier depuis Configuration"** : ouvre modal `#modal-copy-teams`
- Liste les equipes de `Shared/Teams/teams.json`
- Checkbox par equipe + validation de coherence (agents manquants dans `config/Agents/`)
- Alerte si des agents references n'existent pas dans le catalogue de production
- `POST /api/prod-teams/copy-from-config` copie le dossier complet + met a jour `teams.json`

**Table des equipes** : blocs par equipe avec :
- Nom, ID, dossier, channels Discord
- Nombre d'agents
- Carte agent par agent avec type, LLM, pipeline steps

#### 4.2.5 Types de projet (Production)

**Fichier source** : `config/Projects/*/project.json`

**Bouton "Copier depuis Configuration"** : ouvre modal `#modal-copy-projects`
- Liste les projets de `Shared/Projects/`
- Validation : le projet reference une equipe → l'equipe doit exister dans Production
- `POST /api/prod-projects/copy-from-config`

**Table** : ID, Nom, Description, Equipe, Workflows associes

#### 4.2.6 Models (Production)

**Fichier source** : `config/Models/{culture}/*.md`

**Layout** : Split-panel :
- **Select culture** : `#cfg-models-culture-select` — filtre par culture (fr-fr, en-us, etc.)
- **Panel gauche** : liste des fichiers `.md`
  - Bouton "+" pour ajouter un nouveau model
- **Panel droit** : editeur textarea du fichier selectionne
  - Bouton "Sauvegarder" → `PUT /api/prod-models/{name}`
  - Bouton "Supprimer" → `DELETE /api/prod-models/{name}`

**Bouton "Copier depuis Configuration"** : ouvre modal `#modal-copy-models` → `POST /api/prod-models/copy-from-config`

#### 4.2.7 Prompts (Production)

**Fichier source** : `config/Prompts/{culture}/*.md`

Identique a Models mais pour les prompts systeme.

- **Select culture** : `#cfg-prompts-culture-select`
- `PUT /api/prod-prompts/{name}`, `DELETE /api/prod-prompts/{name}`
- **Copier depuis Configuration** : `POST /api/prod-prompts/copy-from-config`

#### 4.2.8 Enregistrement (Production)

**Fichier source** : `config/git.json`

**Carte "Service Git"** :
- **Select "Service"** : GitHub, GitLab, Gitea, Forgejo, Bitbucket
- **Champs** : URL du service, Login, Token d'acces, Nom du depot
- **Boutons** :
  - **Enregistrer** : sauvegarde la config git (`PUT /api/git-svc/configs/config`)
  - **Init** : cree le depot distant + init local (`POST /api/git-svc/configs/create-repo` + `POST /api/git/configs/init`)
  - **Fetch** : recupere un depot existant (`POST /api/git-svc/configs/fetch-repo`)
  - **Commit** : stage + commit + push (`POST /api/git/configs/commit`)
  - **Reset** : reset hard sur origin (`POST /api/git/configs/reset-to-remote`)

**Carte "Depot Config"** :
- Branche courante
- Status git (output `git status --short`)
- **Versions** : table des 10 derniers commits avec hash, date, tags, sujet
  - Cliquer sur un commit → modal version browser ou rollback

---

## 5. Configuration

**Section** : `section-templates`
**Scope** : `Shared/` (configuration generale / templates)

### 5.1 En-tete

- **Titre** : "Configuration"
- **Description** : "Configuration generale (`Shared/`) -- modeles LLM, agents, equipes, prompts et services"
- **Boutons** : Rafraichir, Exporter (`Shared.zip`), Importer (`.zip` → `Shared/`)

### 5.2 Sous-onglets

| Onglet | ID tab | Fichiers source |
|---|---|---|
| Modeles LLM | `tpl-llm` | `Shared/llm_providers.json` |
| Services MCP | `tpl-mcp` | `Shared/Teams/mcp_servers.json` + catalogue CSV |
| Dockerfiles | `tpl-dockerfiles` | `Shared/Dockerfiles/` |
| Agents | `tpl-agents` | `Shared/Agents/*/` |
| Equipes | `tpl-teams` | `Shared/Teams/*/` |
| Types de projet | `tpl-projects` | `Shared/Projects/*/` |
| Prompts | `tpl-prompts` | `Shared/Prompts/{culture}/*.md` |
| Models | `tpl-models` | `Shared/Models/{culture}/*.md` |
| I18n | `tpl-i18n` | `Shared/i18n/{culture}.json` |
| Mail | `tpl-mail` | `Shared/mail.json` |
| Securite | `tpl-security` | `Shared/hitl.json` + API keys PostgreSQL |
| Divers | `tpl-misc` | `Shared/others.json` + `Shared/cultures.json` + `Shared/deliverable_types.json` |
| Enregistrement | `tpl-git` | `Shared/git.json` |

#### 5.2.1 Modeles LLM (Configuration)

Meme structure que Production mais operant sur `Shared/llm_providers.json` :
- **APIs** : `GET/PUT /api/templates/llm`, `POST /api/templates/llm/upload`, `POST /api/templates/llm/resolve`
- Pas de bouton "Copier depuis Configuration" (c'est la source)

#### 5.2.2 Services MCP (Configuration)

Meme structure que Production mais operant sur `Shared/Teams/mcp_servers.json` :
- **APIs** : `GET /api/templates/mcp/catalog`, `POST /api/templates/mcp/install/{id}`, `POST /api/templates/mcp/uninstall/{id}`, `PUT /api/templates/mcp/toggle/{id}`
- L'installation ecrit dans `Shared/Teams/mcp_servers.json` ET ajoute les variables manquantes au `.env`

#### 5.2.3 Dockerfiles (Configuration)

**Fichier source** : `Shared/Dockerfiles/Dockerfile.*`

**Layout** : Split-panel :
- **Panel gauche** (180px) : liste des Dockerfiles
  - Chaque entree montre le nom + badge "built"/"not built" selon si l'image Docker existe
- **Panel droit** : editeur CodeMirror (mode Dockerfile)
  - Deux onglets : Dockerfile / Entrypoint (shell)
  - **Boutons** : Sauvegarder, Supprimer, Build (lance `docker build` en streaming SSE)

**Nom des images** : `agflow-{label}:{hash8}` ou `hash8` = SHA256 des 8 premiers chars du contenu Dockerfile + entrypoint

**Build streaming** : `POST /api/templates/dockerfiles/{name}/build` retourne un flux SSE avec `{line, error}` puis `{done, ok, image}`

#### 5.2.4 Agents (Configuration)

**Fichier source** : `Shared/Agents/{agent_id}/`

Structure d'un agent dans `Shared/Agents/` :
```
{agent_id}/
  agent.json        # Config (name, description, type, llm, temperature, max_tokens, delivers_*, mcp_access)
  prompt.md          # Prompt systeme principal
  identity.md        # Identite de l'agent (optionnel)
  role_{name}.md     # Roles (0..N)
  mission_{name}.md  # Missions (0..N)
  skill_{name}.md    # Competences (0..N)
  {id}_assign.md     # Exemples d'assignation correcte (optionnel)
  {id}_unassign.md   # Exemples d'assignation incorrecte (optionnel)
  chat/              # Historique des conversations avec le LLM builder
```

**Layout** : Split-panel (`sa-split`) :
- **Panel gauche** (`#sa-left`) :
  - Barre de recherche/filtre en haut
  - Bouton "+ Nouvel agent"
  - Liste arborescente : agent_id → sous-items (prompt, identity, roles, missions, skills)
  - Section separatrice entre agents
  - Zone "Supprimer l'agent" en bas avec bouton danger
  - Bouton "Importer (.zip)"

- **Panel droit** (`#sa-right`) :
  - **En-tete** : nom de l'agent, description, boutons action
  - Selon l'item selectionne :
    - `agent.json` : formulaire avec tous les champs (name, description, type, llm, temperature, max_tokens, delivers_*, docker_mode, docker_image, mcp_access)
    - Fichier `.md` : textarea pleine hauteur avec boutons Sauvegarder/Supprimer
  - **Chat avec le LLM** : bouton chat qui ouvre une interface de conversation avec le meta-prompt `GenerateAgent.md` — genere/modifie automatiquement les fichiers de l'agent

**APIs** :
- `GET /api/shared-agents` → liste tous les agents
- `GET /api/shared-agents/{id}` → detail avec tous les fichiers
- `POST /api/shared-agents` → creer
- `PUT /api/shared-agents/{id}` → modifier
- `DELETE /api/shared-agents/{id}` → supprimer (rmtree)
- `PUT /api/shared-agents/{id}/files/{filename}` → ecrire un fichier .md
- `DELETE /api/shared-agents/{id}/files/{filename}` → supprimer un fichier .md
- `POST /api/shared-agents/{id}/chat` → chat avec GenerateAgent.md
- `POST /api/shared-agents/import` → importer un .zip

#### 5.2.5 Equipes (Configuration)

**Fichier source** : `Shared/Teams/teams.json` + `Shared/Teams/{directory}/`

**En-tete** :
- Bouton "+ Ajouter" : ouvre modal creation equipe

**Table des equipes** : un bloc par equipe avec :
- Nom, ID, dossier, description
- Nombre d'agents
- **Agents** : liste des agents enregistres dans `agents_registry.json`, avec :
  - Type (orchestrator, single, pipeline)
  - Pipeline steps (si applicable)
  - `delegates_to` (si applicable)
  - Boutons : editer, supprimer
- **Bouton "+ Ajouter un agent"** : dropdown filtrable des agents du catalogue `Shared/Agents/`
- **Bouton "Construire prompt orchestrateur"** : `POST /api/templates/teams/{dir}/orchestrator/build`
  - Genere `orchestrator_prompt.md` en appelant le LLM pour chaque agent (avec cache basee sur hash)
  - Utilise le template `Shared/Prompts/{culture}/translateOrchestrator.md`
  - Badge "Stale" si les fichiers sources des agents sont plus recents que le prompt
- **Bouton "Verifier la coherence"** : `POST /api/templates/teams/{dir}/coherence/check`
  - Genere un rapport Markdown via `CheckTeamCoherence.md`
  - Badge "Rapport disponible" si `report.md` existe
- **Bouton "Voir le rapport"** : `GET /api/templates/teams/{dir}/coherence/report`

**APIs equipes** :
- `GET /api/templates/teams` → liste (depuis `Shared/Teams/teams.json`)
- `PUT /api/templates/teams` → sauvegarder la liste + creer les dossiers manquants
- `GET /api/templates` → liste detaillee avec agents merges depuis `Shared/Agents/`

**APIs agents dans equipes** :
- `POST /api/templates/agents` → ajouter un agent a une equipe
- `PUT /api/templates/agents/{id}` → modifier (type, pipeline_steps, delegates_to)
- `DELETE /api/templates/agents/{id}?team_id=` → supprimer

**APIs workflow par equipe** :
- `GET /api/templates/workflow/{dir}` → lire `Workflow.json`
- `PUT /api/templates/workflow/{dir}` → ecrire + generer fichiers de phase
- `GET/PUT /api/templates/workflow-design/{dir}` → positions visuelles

#### 5.2.6 Types de projet (Configuration)

**Fichier source** : `Shared/Projects/{project_id}/`

Structure :
```
{project_id}/
  project.json       # {name, description, team}
  {workflow}.wrk.json # Workflow(s)
  chat/              # Traces des appels LLM
```

**Interface** :
- **Barre selecteur de projet** : input autocomplete avec dropdown
  - Boutons : editer, supprimer, "+ Projet", "+ Workflow", generer prompt orchestrateur
- **Contenu projet** : chips de workflows + editeur visuel de workflow
- **Workflow visuel** : editeur graphique de phases, agents, livrables, transitions
  - Drag-and-drop des phases
  - Configuration des livrables (agent, pipeline_step, type, categorie, description, depends_on)
  - Bouton baguette magique pour generer les descriptions via LLM
  - Bouton skill-match pour auto-selectionner roles/missions/skills par livrable
  - **Categories de livrables** : systeme hierarchique a 2 niveaux pour organiser les livrables (voir 5.2.6.1)

**APIs** :
- `GET/POST /api/templates/projects` → lister/creer
- `PUT/DELETE /api/templates/projects/{id}` → modifier/supprimer
- `POST /api/templates/projects/{id}/workflows` → creer un workflow
- `POST /api/templates/projects/{id}/workflows/generate` → generer un workflow via LLM (`CreateWorkflow.md`)
- `GET/PUT/DELETE /api/templates/projects/{id}/workflows/{name}` → CRUD workflow
- `GET/PUT /api/templates/project-workflow/{id}/{name}` → editeur visuel (donnees structurees)
- `GET/PUT /api/templates/project-workflow-design/{id}/{name}` → positions visuelles
- `POST /api/templates/projects/{id}/deliverable-skillmatch` → skill-match LLM
- `POST /api/templates/projects/{id}/orchestrator/build` → construire le prompt orchestrateur

##### 5.2.6.1 Categories de livrables

Systeme hierarchique a 2 niveaux (categorie / sous-categorie) pour organiser les livrables du workflow.

**Modele de donnees** (`Workflow.json`) :
```json
{
  "categories": [
    {
      "id": "analysis", "name": "Analyse",
      "children": [
        { "id": "functional", "name": "Fonctionnel" },
        { "id": "market", "name": "Marche" }
      ]
    },
    { "id": "technical", "name": "Technique", "children": [...] }
  ]
}
```

Chaque livrable a un champ optionnel `"category"` : `"parentId/childId"` (sous-categorie) ou `"parentId"` (categorie racine). Absent ou `""` = non categorise.

**Affichage sidebar** (proprietes du workspace, quand aucune phase n'est selectionnee) :
- Section repliable "Categories de livrables" avec section key `wk-cats`
- Arbre en lecture seule : categories en gras + sous-categories indentees
- Bouton crayon (✏) → ouvre la popup CRUD (`wfOpenCategoriesEditor()`)
- Si aucune categorie definie : texte "Aucune categorie"

**Popup CRUD** (`showModal`, classe `modal-confirm`) :
- Header : "Categories de livrables"
- Body : liste editable des categories
  - Pour chaque categorie : input nom (gras) + bouton "+" (ajouter sous-cat) + bouton "x" (supprimer)
  - Pour chaque sous-categorie : input nom indente + bouton "x"
  - Bouton "+ Ajouter une categorie" en bas
- Footer : Annuler / Appliquer
- Travaille sur un deep clone — Annuler ne modifie rien

**Gestion des IDs** :
- A la creation : ID auto-genere `cat_N` / `sub_N` (compteur incremental)
- L'ID ne change jamais apres creation → renommer ne casse pas les references
- Suppression d'une categorie utilisee : confirmation si des livrables la referencent

**Nettoyage des refs orphelines** (`_wfCatApply()`) :
- Filtre les categories/sous-categories sans nom
- Scan tous les livrables de toutes les phases
- Si `category` pointe vers un ID supprime → vide a `""`
- Toast warning : "N livrable(s) avaient une categorie supprimee"

**Dropdown dans l'editeur de livrable** :
- `<select>` pleine largeur insere apres le bloc type/required
- Utilise `<optgroup>` pour les categories avec enfants
- Categories sans enfants affichees comme `<option>` directe
- `onchange` → `_wfSetDelField(phaseId, delId, 'category', value)` (generique, pas de modification necessaire)

**Retrocompatibilite** :
- `data.categories` initialise a `[]` si absent dans le JSON → aucun impact sur les workflows existants
- Le backend (`workflow_engine.py`) ignore les cles racine inconnues

**Fonctions JS** :

| Fonction | Role |
|---|---|
| `_wfBuildCategoryOptions(currentValue)` | Genere HTML `<option>` + `<optgroup>` pour le dropdown |
| `_wfCategoryLabel(catValue)` | Retourne le label lisible ("Analyse / Fonctionnel") |
| `_wfRenderCategoryTree()` | Genere l'arbre HTML en lecture seule pour la sidebar |
| `wfOpenCategoriesEditor()` | Ouvre la popup CRUD (deep clone + modal) |
| `_wfCatRender()` | Re-render le body de la popup sans la fermer |
| `_wfCatAdd()` | Ajoute une categorie vide |
| `_wfCatRemove(idx)` | Supprime une categorie (avec confirm si referencee) |
| `_wfCatAddChild(catIdx)` | Ajoute une sous-categorie |
| `_wfCatRemoveChild(catIdx, childIdx)` | Supprime une sous-categorie |
| `_wfCatSetName(idx, name)` | Modifie le nom d'une categorie |
| `_wfCatSetChildName(catIdx, childIdx, name)` | Modifie le nom d'une sous-categorie |
| `_wfCountCategoryRefs(prefix)` | Compte les livrables referencant un prefix |
| `_wfCatApply()` | Ecrit le clone, nettoie les refs orphelines, ferme et re-render |

**CSS** :

| Classe | Usage |
|---|---|
| `.wf-cat-tree` | Container de l'arbre sidebar (font-size 0.78rem) |
| `.wf-cat-tree-item` | Categorie dans l'arbre (gras, text-primary) |
| `.wf-cat-tree-child` | Sous-categorie (indentee 1rem, text-secondary) |
| `.wf-cat-row` | Ligne dans la popup CRUD (flex, gap 0.4rem) |
| `.wf-cat-children` | Block sous-categories dans la popup (border-left, indent 1.2rem) |

#### 5.2.7 Prompts (Configuration)

**Fichier source** : `Shared/Prompts/{culture}/*.md`

Identique a Production > Prompts mais operant sur `Shared/Prompts/` :
- Select culture en haut a droite
- Split-panel : liste fichiers + editeur
- `GET /api/templates/prompts?culture=`, `PUT /api/templates/prompts/{name}?culture=`, `DELETE ...`

#### 5.2.8 Models (Configuration)

**Fichier source** : `Shared/Models/{culture}/*.md`

Identique a Prompts mais pour les fichiers modeles :
- `GET /api/templates/models?culture=`, `PUT /api/templates/models/{name}?culture=`, `DELETE ...`

#### 5.2.9 I18n

**Fichier source** : `Shared/i18n/{culture}.json`

- **Select culture** : filtre les traductions par culture
- **Split-panel** :
  - Panel gauche : liste des cles de traduction (filtrable)
  - Panel droit : editeur de la valeur
- **Bouton "+ Ajouter"** : ajoute une nouvelle cle
- Les cles de la culture par defaut sont listees comme reference

**APIs** :
- `GET /api/templates/i18n?culture=` → liste traductions + cles de reference
- `PUT /api/templates/i18n/{key}?culture=` → definir valeur
- `DELETE /api/templates/i18n/{key}?culture=` → supprimer

#### 5.2.10 Mail

**Fichier source** : `Shared/mail.json`

**Carte SMTP** :
- Liste des configurations SMTP (multi-serveurs)
- Chaque entree : name, host, port, TLS, SSL, user, password_env, from_address, from_name
- Bouton "+ Ajouter" / Editer → modal `#modal-smtp-edit` avec champs + presets

**Carte IMAP** :
- Liste des configurations IMAP
- Chaque entree : name, host, port, SSL, user, password_env
- Bouton "+ Ajouter" / Editer → modal `#modal-imap-edit` avec presets

**Carte Listener** (repliable) :
- Intervalle de polling (secondes)
- Expediteurs autorises (textarea, un par ligne)
- Patterns a ignorer (textarea, un par ligne)

**Carte Templates email** :
- Liste des templates (name, subject, body)
- Bouton "+ Ajouter" / Editer → modal `#modal-tpl-mail-edit`
- Variables disponibles : `{agent_name}`, `{question}`, `{context}`

**Carte Securite** (repliable) :
- Exiger TLS (toggle)
- Verifier expediteur (toggle)
- Taille max body

**Bouton global "Sauvegarder"** → `PUT /api/templates/mail`

#### 5.2.11 Securite

**Carte "Cles API"** (repliable) :
- Description : cles d'acces MCP SSE endpoint `http://<IP>:8123/mcp/{team_id}/sse`
- **Table** : nom, preview, equipes, agents, scopes, date creation, expiration, statut (revoque/actif)
- **Bouton "+ Nouvelle cle"** → modal `#modal-add-apikey`
- **Bouton "Revoquer"** → `POST /api/keys/{hash}/revoke`
- **Bouton "Supprimer"** → `DELETE /api/keys/{hash}`
- Statut de `MCP_SECRET` dans le `.env`

**Carte "Google OpenID Connect"** (repliable) :
- Checkbox "Activer Google Sign-In"
- Champs (affiches si active) : Client ID, Client Secret (var env), Domaines autorises
- Statut affiches (tag "Active"/"Desactive")

**Carte "Parametres generaux"** (repliable) :
- Expiration JWT (heures) : input nombre (1-720)
- Role par defaut : select (undefined / member)
- Checkbox "Autoriser l'inscription publique"

**Boutons** : Enregistrer (`PUT /api/templates/hitl-config`) / Annuler

#### 5.2.12 Divers

**Fichier source** : `Shared/others.json`, `Shared/cultures.json`, `Shared/deliverable_types.json`

**Carte "Domaines et adresses"** :
- URLs des services : Administration, Console HITL, API Gateway, Observabilite, PostgreSQL, Redis

**Carte "Emails de reinitialisation"** :
- Select SMTP (parmi ceux configures dans Mail)
- Select Template (parmi ceux configures dans Mail)
- Variables : `${UrlService}`, `${mail}`, `${pwd}`

**Carte "Cultures"** :
- Filtre textuel
- Grille de cultures (31 locales) avec toggle enabled/disabled
- `PUT /api/templates/cultures/{key}`

**Carte "Services"** :
- Types de livrables (delivers_docs, delivers_code, etc.)
- Table : cle, label, bouton supprimer
- Bouton "+ Ajouter" → modal creation

**Bouton "Sauvegarder"** → `PUT /api/templates/others`

#### 5.2.13 Enregistrement (Configuration)

Meme structure que Production > Enregistrement mais pour le scope `shared` :
- Git service config : `PUT /api/git-svc/shared/config`
- Operations : init, fetch, commit, push, reset
- Versions avec navigation et rollback

---

## 6. Secrets (.env)

**Section** : `section-secrets`

### 6.1 Interface

- **Titre** : "Secrets (.env)"
- **Boutons** :
  - **Rafraichir** : recharge le fichier
  - **+ Ajouter** : ouvre modal ajout (key, value, section_comment optionnel)
  - **Copier** : copie tout le contenu du `.env` dans le presse-papier
  - **Coller** : ouvre modal pour coller un bloc `KEY=VALUE` (merge intelligent)

### 6.2 Table

- **Filtre** : `#env-search` filtre par nom de cle
- **Colonnes** : Cle, Valeur (masquee par defaut avec `maskValue()`), Actions
- **Actions par entree** :
  - Afficher/masquer la valeur
  - Copier la valeur
  - Modifier (inline)
  - Supprimer (`POST /api/env/delete`)
- Les commentaires et lignes vides sont preserves

### 6.3 APIs

| Methode | Endpoint | Description |
|---|---|---|
| GET | `/api/env` | Lire toutes les entrees |
| GET | `/api/env/path` | Chemin du fichier `.env` |
| PUT | `/api/env` | Remplacer toutes les entrees |
| POST | `/api/env/add` | Ajouter une entree |
| POST | `/api/env/delete` | Supprimer une entree par cle |
| POST | `/api/env/merge` | Merge : ajouter nouvelles, MAJ existantes |

---

## 7. Channels

**Section** : `section-channels`

### 7.1 Interface

Configuration des canaux de communication (principalement Discord).

**Fichier source** : `Shared/discord.json`

**Champs** :
- Enabled (toggle)
- Default channel
- Bot token (env var)
- Guild ID
- Channels mapping
- Aliases
- Formatting options
- Timeouts

**APIs** :
- `GET /api/templates/discord` → lecture config Discord
- `PUT /api/templates/discord` → sauvegarde

---

## 8. Chat LLM

**Section** : `section-chat`

### 8.1 Interface

Interface de conversation directe avec un LLM configure.

**Layout** : `sa-chat-wrap` :
- **Zone messages** (`sa-chat-messages`) : bulles user (bleu, aligne droite) + assistant (gris, aligne gauche)
- **Barre d'input** (`sa-chat-input-bar`) : textarea + bouton envoyer

### 8.2 Configuration

- Utilise le provider defini par `admin_llm` dans `Shared/llm_providers.json`, sinon `default`
- Select optionnel pour choisir un autre provider
- Supporte tous les types : Anthropic, OpenAI, Azure, Google, Mistral, DeepSeek, Groq, Moonshot, Ollama

### 8.3 API

| Methode | Endpoint | Corps | Description |
|---|---|---|---|
| POST | `/api/chat` | `{messages, provider_id?, use_admin_llm?}` | Envoyer un message au LLM |

Le backend route selon le `type` du provider :
- `anthropic` : API Messages v1 (header `x-api-key`, `anthropic-version`)
- `google` : Generative Language API (cle en query param)
- `azure` : Azure OpenAI (header `api-key`, endpoint + deployment)
- Autres (openai, mistral, deepseek, groq, moonshot, ollama) : API chat/completions OpenAI-compatible

---

## 9. Validations (HITL)

**Section** : `section-hitl`

### 9.1 Interface

Liste des requetes HITL (Human-In-The-Loop) en attente de validation.

**Filtres** :
- Par statut : pending, answered, timeout, cancelled
- Par equipe

**Table** : pour chaque requete :
- ID, Thread, Agent, Equipe, Type (approval/question), Prompt, Statut, Reponse, Reviewer, Canal, Dates

**Actions** :
- **Repondre** : modal avec textarea → `POST /api/hitl/{id}/respond`
- **Annuler** : `POST /api/hitl/{id}/cancel`

### 9.2 APIs

| Methode | Endpoint | Description |
|---|---|---|
| GET | `/api/hitl?status=&team_id=&limit=` | Lister les requetes |
| GET | `/api/hitl/stats` | Statistiques par statut |
| POST | `/api/hitl/{id}/respond` | Repondre (response + reviewer) |
| POST | `/api/hitl/{id}/cancel` | Annuler une requete pending |

---

## 10. Utilisateurs

**Section** : `section-users`

### 10.1 Interface

Gestion des utilisateurs de la console HITL.

**Bouton "+ Creer un utilisateur"** : ouvre modal de creation

**Table** : pour chaque utilisateur :
- Email, Nom, Role (tag colore : admin=bleu, member=vert, undefined=rouge), Auth type (local/google)
- Equipes assignees
- Date creation, Dernier login
- Actif (toggle)
- Actions : Editer, Renvoyer email, Supprimer

### 10.2 Creation d'utilisateur

1. Backend genere un mot de passe temporaire (12 chars, min 1 majuscule, 1 minuscule, 1 chiffre, 1 special)
2. Email de bienvenue envoye via SMTP (config depuis `mail.json` + `others.json`)
3. Utilisateur insere en DB avec role choisi et hash bcrypt
4. Assignation aux equipes selectionnees

### 10.3 Modification

- Champs editables : display_name, role, is_active, equipes
- Le role ne peut pas etre change pour soi-meme (protection)
- Resync des `hitl_team_members` a chaque sauvegarde

### 10.4 APIs

| Methode | Endpoint | Description |
|---|---|---|
| GET | `/api/hitl/users` | Lister tous les utilisateurs + equipes |
| POST | `/api/hitl/users` | Creer (email, role, teams) → genere mdp + envoie email |
| PUT | `/api/hitl/users/{id}` | Modifier (display_name, role, is_active, teams) |
| DELETE | `/api/hitl/users/{id}` | Supprimer |
| POST | `/api/hitl/users/{id}/resend-reset` | Regenerer mdp + renvoyer email |

---

## 11. Monitoring

**Section** : `section-monitoring`

### 11.1 Events

**Proxy vers le gateway** : `GET /api/monitoring/events?n=&event_type=&agent_id=`

- Liste des evenements du bus interne du gateway (ring buffer 2000)
- 12 types : agent_start, agent_complete, agent_error, llm_call_start, llm_call_end, tool_call, pipeline_step_start, pipeline_step_end, human_gate_requested, human_gate_responded, agent_dispatch, phase_transition
- Filtres par type et par agent

### 11.2 Logs

**API** : `GET /api/monitoring/logs?service=&lines=`

- Services autorises : `langgraph-api`, `langgraph-discord`, `langgraph-mail`, `langgraph-admin`
- Nombre de lignes configurable (10-5000, defaut 200)
- Lit stdout + stderr du container Docker avec timestamps
- Affichage dans un terminal `<pre>` avec auto-scroll

### 11.3 Containers

**API** : `GET /api/monitoring/containers`

- Liste tous les containers Docker (`docker ps -a`)
- Pour chaque container : nom, status, image, ports, state
- **Actions** : `POST /api/monitoring/container/{name}/{action}` avec `action` = start/stop/restart
- Containers autorises : langgraph-api, langgraph-discord, langgraph-mail, langgraph-admin

### 11.4 Gateway Health

**API** : `GET /api/monitoring/gateway`

- Proxy vers `GET {GATEWAY_URL}/health`
- Retourne status + version si joignable, ou erreur

---

## 12. Scripts

**Section** : `section-scripts`

### 12.1 Interface

Liste et execution de scripts shell.

**Scripts autorises** : `start`, `stop`, `restart`, `build`

**API** : `GET /api/scripts` → liste avec existence

**Execution** : `POST /api/scripts/run` avec `{name}`
- Execute `bash {script}.sh` dans `PROJECT_DIR`
- Timeout 180 secondes
- Retourne `{stdout, stderr, code}`

---

## 13. API Endpoints

### 13.1 Authentification

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | Non | Connexion (username/password) |
| GET | `/auth/logout` | Non | Deconnexion (supprime cookie) |
| GET | `/api/version` | Non | Version + date derniere MAJ |

### 13.2 Secrets (.env)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/env` | Oui | Lire `.env` |
| GET | `/api/env/path` | Oui | Chemin + existence |
| PUT | `/api/env` | Oui | Remplacer tout |
| POST | `/api/env/add` | Oui | Ajouter une entree |
| POST | `/api/env/delete` | Oui | Supprimer par cle |
| POST | `/api/env/merge` | Oui | Merge (ajouter/MAJ) |

### 13.3 MCP (Production — config/)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/mcp/catalog` | Oui | Catalogue enrichi (installed, agents, env status) |
| POST | `/api/mcp/catalog` | Oui | Ajouter au catalogue |
| PUT | `/api/mcp/catalog/{id}` | Oui | Modifier dans le catalogue |
| DELETE | `/api/mcp/catalog/{id}` | Oui | Supprimer du catalogue + desinstaller |
| POST | `/api/mcp/install/{id}` | Oui | Installer (ecrire dans mcp_servers.json + .env) |
| POST | `/api/mcp/uninstall/{id}` | Oui | Desinstaller |
| PUT | `/api/mcp/toggle/{id}` | Oui | Activer/desactiver |
| GET | `/api/mcp/access` | Oui | Acces MCP par agent |
| PUT | `/api/mcp/access` | Oui | MAJ acces d'un agent |
| GET | `/api/mcp/servers` | Oui | Serveurs merges (config + shared) |
| GET | `/api/mcp/cfg-servers` | Oui | Serveurs config seulement |
| POST | `/api/mcp/copy-from-template` | Oui | Copier serveurs de Shared vers config |

### 13.4 MCP (Configuration — Shared/)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/templates/mcp` | Oui | Lire Shared MCP |
| PUT | `/api/templates/mcp` | Oui | Ecrire Shared MCP |
| GET | `/api/templates/mcp/catalog` | Oui | Catalogue enrichi Shared |
| POST | `/api/templates/mcp/install/{id}` | Oui | Installer dans Shared |
| POST | `/api/templates/mcp/uninstall/{id}` | Oui | Desinstaller de Shared |
| PUT | `/api/templates/mcp/toggle/{id}` | Oui | Toggle dans Shared |

### 13.5 LLM Providers (Production — config/)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/llm/providers` | Oui | Lire config LLM |
| POST | `/api/llm/providers/provider` | Oui | Ajouter un provider |
| PUT | `/api/llm/providers/provider/{id}` | Oui | Modifier (avec rename) |
| DELETE | `/api/llm/providers/provider/{id}` | Oui | Supprimer |
| PUT | `/api/llm/providers/default` | Oui | Definir le provider par defaut |
| PUT | `/api/llm/providers/admin` | Oui | Definir le LLM admin |
| PUT | `/api/llm/providers/throttling` | Oui | Ajouter/modifier throttling |
| DELETE | `/api/llm/providers/throttling/{env_key}` | Oui | Supprimer throttling |
| POST | `/api/llm/providers/upload` | Oui | Upload JSON (merge) |
| POST | `/api/llm/providers/resolve` | Oui | Resoudre conflits d'import |

### 13.6 LLM Providers (Configuration — Shared/)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/templates/llm` | Oui | Lire Shared LLM |
| PUT | `/api/templates/llm` | Oui | Ecrire Shared LLM |
| POST | `/api/templates/llm/upload` | Oui | Upload JSON (merge) |
| POST | `/api/templates/llm/resolve` | Oui | Resoudre conflits |

### 13.7 Agents (Production — config/Agents/)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/prod-agents` | Oui | Lister agents production |
| GET | `/api/prod-agents/{id}` | Oui | Detail agent |
| POST | `/api/prod-agents` | Oui | Creer agent |
| PUT | `/api/prod-agents/{id}` | Oui | Modifier agent |
| DELETE | `/api/prod-agents/{id}` | Oui | Supprimer agent |
| PUT | `/api/prod-agents/{id}/files/{filename}` | Oui | Ecrire fichier .md |
| DELETE | `/api/prod-agents/{id}/files/{filename}` | Oui | Supprimer fichier .md |
| POST | `/api/prod-agents/copy-from-config` | Oui | Copier depuis Shared/Agents/ |
| POST | `/api/prod-agents/import` | Oui | Importer .zip |

### 13.8 Agents (Configuration — Shared/Agents/)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/shared-agents` | Oui | Lister agents partages |
| GET | `/api/shared-agents/{id}` | Oui | Detail avec fichiers |
| POST | `/api/shared-agents` | Oui | Creer |
| PUT | `/api/shared-agents/{id}` | Oui | Modifier + invalidate orch |
| DELETE | `/api/shared-agents/{id}` | Oui | Supprimer |
| PUT | `/api/shared-agents/{id}/files/{filename}` | Oui | Ecrire fichier .md |
| DELETE | `/api/shared-agents/{id}/files/{filename}` | Oui | Supprimer fichier .md |
| POST | `/api/shared-agents/{id}/chat` | Oui | Chat LLM (GenerateAgent.md) |
| POST | `/api/shared-agents/import` | Oui | Importer .zip |

### 13.9 Agents dans equipes (Production — config/Teams/)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/agents` | Oui | Tous agents groupes par equipe |
| POST | `/api/agents` | Oui | Ajouter ref agent a une equipe |
| PUT | `/api/agents/{id}` | Oui | Modifier ref (type, steps, delegates_to) |
| DELETE | `/api/agents/{id}?team_id=` | Oui | Supprimer ref |
| PUT | `/api/agents/mcp-access/{dir}/{id}` | Oui | MCP access par agent |
| GET | `/api/agents/registry/{dir}` | Oui | Lire registry brut |
| PUT | `/api/agents/registry/{dir}` | Oui | Ecrire registry brut |
| POST | `/api/prod-team-agents` | Oui | Ajouter agent au registry d'une equipe prod (body: id, team_id, type, delegates_to) |
| PUT | `/api/prod-team-agents/{agent_id}` | Oui | Modifier agent dans le registry equipe prod |
| DELETE | `/api/prod-team-agents/{agent_id}?team_id=` | Oui | Supprimer agent du registry prod (sauf orchestrator) |

### 13.10 Agents dans equipes (Configuration — Shared/Teams/)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/templates/agents` | Oui | Ajouter agent a equipe template |
| PUT | `/api/templates/agents/{id}` | Oui | Modifier ref |
| DELETE | `/api/templates/agents/{id}?team_id=` | Oui | Supprimer ref |
| GET | `/api/templates/registry/{dir}` | Oui | Lire registry |
| PUT | `/api/templates/registry/{dir}` | Oui | Ecrire registry |
| PUT | `/api/templates/mcp-access/{dir}/{id}` | Oui | MCP access template |

### 13.11 Equipes

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/teams` | Oui | Equipes enrichies (agents merges) |
| POST | `/api/teams/{id}` | Oui | Creer equipe |
| PUT | `/api/teams/{id}` | Oui | Modifier equipe |
| DELETE | `/api/teams/{id}` | Oui | Supprimer (dossier + DB) |
| GET | `/api/templates` | Oui | Templates (Shared/Teams/) enrichis |
| GET | `/api/prod-teams` | Oui | Liste brute prod |
| PUT | `/api/prod-teams` | Oui | Sauvegarder liste prod |
| GET | `/api/prod-teams-detail` | Oui | Detail prod avec agents |
| POST | `/api/prod-teams/copy-from-config` | Oui | Copier Shared → config |
| GET | `/api/templates/teams` | Oui | Liste Shared |
| PUT | `/api/templates/teams` | Oui | Sauvegarder Shared |

### 13.12 Orchestrateur

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/templates/teams/{dir}/orchestrator/build` | Oui | Construire prompt orchestrateur |
| POST | `/api/templates/teams/{dir}/coherence/check` | Oui | Verifier coherence equipe |
| GET | `/api/templates/teams/{dir}/coherence/report` | Oui | Lire rapport coherence |

### 13.13 Workflows

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/workflow/{dir}` | Oui | Lire Workflow.json (prod) |
| PUT | `/api/workflow/{dir}` | Oui | Ecrire + generer phases (prod) |
| GET | `/api/templates/workflow/{dir}` | Oui | Lire (shared) |
| PUT | `/api/templates/workflow/{dir}` | Oui | Ecrire + generer phases (shared) |
| GET/PUT | `/api/workflow-design/{dir}` | Oui | Positions visuelles (prod) |
| GET/PUT | `/api/templates/workflow-design/{dir}` | Oui | Positions visuelles (shared) |

### 13.14 Projets

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/templates/projects` | Oui | Lister projets Shared |
| POST | `/api/templates/projects` | Oui | Creer projet |
| PUT | `/api/templates/projects/{id}` | Oui | Modifier |
| DELETE | `/api/templates/projects/{id}` | Oui | Supprimer |
| POST | `/api/templates/projects/{id}/workflows` | Oui | Creer workflow |
| POST | `/api/templates/projects/{id}/workflows/generate` | Oui | Generer via LLM |
| GET | `/api/templates/projects/{id}/workflows/{name}` | Oui | Lire workflow |
| PUT | `/api/templates/projects/{id}/workflows/{name}` | Oui | Modifier workflow |
| DELETE | `/api/templates/projects/{id}/workflows/{name}` | Oui | Supprimer workflow |
| GET/PUT | `/api/templates/project-workflow/{id}/{name}` | Oui | Editeur visuel |
| GET/PUT | `/api/templates/project-workflow-design/{id}/{name}` | Oui | Positions visuelles |
| POST | `/api/templates/projects/{id}/deliverable-skillmatch` | Oui | Skill-match LLM |
| POST | `/api/templates/projects/{id}/orchestrator/build` | Oui | Build orch prompt |
| GET | `/api/prod-projects` | Oui | Lister projets production |
| POST | `/api/prod-projects` | Oui | Creer (prod) |
| PUT | `/api/prod-projects/{id}` | Oui | Modifier (prod) |
| DELETE | `/api/prod-projects/{id}` | Oui | Supprimer (prod) |
| POST | `/api/prod-projects/copy-from-config` | Oui | Copier Shared → config |

### 13.15 Prompts et Models

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/templates/prompts?culture=` | Oui | Lister prompts Shared |
| GET | `/api/templates/prompts/{name}?culture=` | Oui | Lire prompt |
| PUT | `/api/templates/prompts/{name}?culture=` | Oui | Ecrire prompt |
| DELETE | `/api/templates/prompts/{name}?culture=` | Oui | Supprimer |
| GET | `/api/prod-prompts?culture=` | Oui | Lister prod |
| PUT | `/api/prod-prompts/{name}?culture=` | Oui | Ecrire prod |
| DELETE | `/api/prod-prompts/{name}?culture=` | Oui | Supprimer prod |
| POST | `/api/prod-prompts/copy-from-config?culture=` | Oui | Copier Shared → config |
| GET | `/api/templates/models?culture=` | Oui | Lister models Shared |
| GET | `/api/templates/models/{name}?culture=` | Oui | Lire model |
| PUT | `/api/templates/models/{name}?culture=` | Oui | Ecrire model |
| DELETE | `/api/templates/models/{name}?culture=` | Oui | Supprimer |
| GET | `/api/prod-models?culture=` | Oui | Lister prod |
| PUT | `/api/prod-models/{name}?culture=` | Oui | Ecrire prod |
| DELETE | `/api/prod-models/{name}?culture=` | Oui | Supprimer prod |
| POST | `/api/prod-models/copy-from-config?culture=` | Oui | Copier Shared → config |

### 13.16 Dockerfiles

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/templates/dockerfiles` | Oui | Lister Shared |
| GET | `/api/templates/dockerfiles/{name}` | Oui | Lire |
| PUT | `/api/templates/dockerfiles/{name}` | Oui | Ecrire (content + entrypoint_content) |
| DELETE | `/api/templates/dockerfiles/{name}` | Oui | Supprimer (+ entrypoint) |
| POST | `/api/templates/dockerfiles/{name}/build` | Oui | Build Docker (SSE streaming) |
| GET | `/api/dockerfiles` | Oui | Lister prod |
| GET | `/api/dockerfiles/{name}` | Oui | Lire prod |
| PUT | `/api/dockerfiles/{name}` | Oui | Ecrire prod |
| DELETE | `/api/dockerfiles/{name}` | Oui | Supprimer prod |
| POST | `/api/dockerfiles/{name}/build` | Oui | Build prod (SSE) |

### 13.17 Cultures, I18n, Deliverable Types

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/templates/cultures` | Oui | Lister cultures + defaut |
| PUT | `/api/templates/cultures/{key}` | Oui | Toggle enabled/disabled |
| GET | `/api/templates/i18n?culture=` | Oui | Traductions + cles reference |
| PUT | `/api/templates/i18n/{key}?culture=` | Oui | Definir traduction |
| DELETE | `/api/templates/i18n/{key}?culture=` | Oui | Supprimer traduction |
| GET | `/api/templates/deliverable-types` | Oui | Lister types de livrables |
| POST | `/api/templates/deliverable-types` | Oui | Creer type |
| DELETE | `/api/templates/deliverable-types/{key}` | Oui | Supprimer type |

### 13.18 Mail, Discord, HITL Config, Others

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/templates/mail` | Oui | Lire mail.json |
| PUT | `/api/templates/mail` | Oui | Ecrire mail.json |
| GET | `/api/templates/discord` | Oui | Lire discord.json |
| PUT | `/api/templates/discord` | Oui | Ecrire discord.json |
| GET | `/api/templates/hitl-config` | Oui | Lire hitl.json |
| PUT | `/api/templates/hitl-config` | Oui | Ecrire hitl.json |
| GET | `/api/templates/others` | Oui | Lire others.json |
| PUT | `/api/templates/others` | Oui | Ecrire others.json |

### 13.19 Outline

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/outline-config` | Oui | Lire outline.json |
| PUT | `/api/outline-config` | Oui | Ecrire outline.json |
| POST | `/api/outline/test-connection` | Oui | Tester connexion API Outline |
| GET | `/api/outline/documents/{thread_id}` | Oui | Documents trackes par thread |

### 13.20 Chat LLM

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/chat` | Oui | Envoyer messages au LLM |

### 13.21 Generation LLM (meta-prompts)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/agents/generate-prompt` | Oui | Generer prompt agent (createAgent.md) |
| POST | `/api/agents/generate-assign` | Oui | Generer exemples assignation |
| POST | `/api/agents/generate-unassign` | Oui | Generer exemples non-assignation |
| POST | `/api/agents/generate-mission` | Oui | Generer instruction step (Missions.md) |
| POST | `/api/agents/generate-description` | Oui | Generer description livrable |
| GET | `/api/prompts/templates/{name}` | Oui | Lire meta-prompt (legacy) |

### 13.22 Config Check

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/config/check` | Oui | Validation complete de la configuration |

### 13.23 API Keys (MCP SSE)

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/keys` | Oui | Lister cles API (depuis PostgreSQL) |
| POST | `/api/keys` | Oui | Generer cle HMAC-signee |
| POST | `/api/keys/{hash}/revoke` | Oui | Revoquer une cle |
| DELETE | `/api/keys/{hash}` | Oui | Supprimer une cle |

### 13.24 Monitoring

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/monitoring/gateway` | Oui | Health check gateway |
| GET | `/api/monitoring/containers` | Oui | Status containers Docker |
| POST | `/api/monitoring/container/{name}/{action}` | Oui | Start/stop/restart container |
| GET | `/api/monitoring/logs?service=&lines=` | Oui | Logs container |
| GET | `/api/monitoring/events?n=&event_type=&agent_id=` | Oui | Events gateway |

### 13.25 HITL

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/hitl?status=&team_id=&limit=` | Oui | Lister requetes HITL |
| GET | `/api/hitl/stats` | Oui | Stats par statut |
| POST | `/api/hitl/{id}/respond` | Oui | Repondre |
| POST | `/api/hitl/{id}/cancel` | Oui | Annuler |

### 13.26 Utilisateurs HITL

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/hitl/users` | Oui | Lister utilisateurs + equipes |
| POST | `/api/hitl/users` | Oui | Creer (genere mdp + email) |
| PUT | `/api/hitl/users/{id}` | Oui | Modifier |
| DELETE | `/api/hitl/users/{id}` | Oui | Supprimer |
| POST | `/api/hitl/users/{id}/resend-reset` | Oui | Renvoyer email de reset |

### 13.27 Export / Import

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/export/shared` | Oui | Telecharger Shared.zip |
| GET | `/api/export/configs` | Oui | Telecharger config.zip |
| POST | `/api/import/shared` | Oui | Importer .zip → Shared/ |
| POST | `/api/import/configs` | Oui | Importer .zip → config/ |

### 13.28 Git

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/git/{repo_key}/status` | Oui | Status + branche + log |
| POST | `/api/git/{repo_key}/init` | Oui | Init repo + remote + commit initial |
| POST | `/api/git/{repo_key}/pull` | Oui | Fetch + reset hard (force optional) |
| POST | `/api/git/{repo_key}/commit` | Oui | Stage + commit + push |
| POST | `/api/git/{repo_key}/push` | Oui | Push only (force optional) |
| POST | `/api/git/{repo_key}/reset` | Oui | Hard reset vers origin |
| POST | `/api/git/{repo_key}/reset-to-remote` | Oui | Fetch + reset hard |
| GET | `/api/git/{repo_key}/commits` | Oui | 10 derniers commits |
| POST | `/api/git/{repo_key}/checkout/{hash}` | Oui | Rollback contenu vers un commit |

`repo_key` = `configs` (→ `config/`) ou `shared` (→ `Shared/`)

### 13.29 Git Service

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/git-service/types` | Oui | Services supportes |
| GET | `/api/git-svc/{scope}/config` | Oui | Lire config git service |
| PUT | `/api/git-svc/{scope}/config` | Oui | Sauvegarder config |
| POST | `/api/git-svc/{scope}/sync-repo-config` | Oui | Sync credentials |
| POST | `/api/git-svc/{scope}/check-repo` | Oui | Verifier si repo existe |
| POST | `/api/git-svc/{scope}/create-repo` | Oui | Creer repo distant |
| POST | `/api/git-svc/{scope}/fetch-repo` | Oui | Cloner/fetch repo |
| GET | `/api/git/repo-config/{repo_key}` | Oui | Lire git.json |
| PUT | `/api/git/repo-config/{repo_key}` | Oui | Sauvegarder git.json |

### 13.30 Version Browser

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/git/{repo_key}/version-browse/{hash}` | Oui | Ouvrir session (clone temp) |
| GET | `/api/git/version-browse/{session}/tree?path=` | Oui | Lister fichiers |
| GET | `/api/git/version-browse/{session}/file?path=` | Oui | Lire fichier (max 100KB) |
| POST | `/api/git/version-browse/{session}/close` | Oui | Fermer session |

Sessions expirent apres 30 minutes. Nettoyage automatique des dossiers orphelins au demarrage.

### 13.31 Scripts

| Methode | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/scripts` | Oui | Lister scripts disponibles |
| POST | `/api/scripts/run` | Oui | Executer script (start/stop/restart/build) |

---

## 14. Fichiers de configuration

### 14.1 Scope Production (config/)

| Fichier | Chemin | Contenu |
|---|---|---|
| `teams.json` | `config/teams.json` | Liste equipes + channel_mapping |
| `llm_providers.json` | `config/llm_providers.json` | Providers LLM + throttling + default |
| `mcp_servers.json` | `config/mcp_servers.json` | Serveurs MCP installes |
| `outline.json` | `config/outline.json` | Config Outline (wiki) |
| `git.json` | `config/git.json` | Config git (path, login, password) |
| `agents_registry.json` | `config/Teams/{dir}/agents_registry.json` | Agents par equipe (ref vers Shared) |
| `agent_mcp_access.json` | `config/Teams/{dir}/agent_mcp_access.json` | MCP par agent par equipe |
| `Workflow.json` | `config/Teams/{dir}/Workflow.json` | Workflow par equipe (phases, transitions, categories, rules) |
| `*.md` | `config/Teams/{dir}/*.md` | Prompts agents (fallback) |
| `agent.json` | `config/Agents/{id}/agent.json` | Config agent production |
| `*.md` | `config/Agents/{id}/*.md` | Fichiers agent production |
| `*.md` | `config/Prompts/{culture}/*.md` | Prompts systeme production |
| `*.md` | `config/Models/{culture}/*.md` | Models production |
| `project.json` | `config/Projects/{id}/project.json` | Config projet production |
| `Dockerfile.*` | `config/Dockerfiles/` | Dockerfiles production |

### 14.2 Scope Configuration (Shared/)

| Fichier | Chemin | Contenu |
|---|---|---|
| `llm_providers.json` | `Shared/llm_providers.json` | Providers LLM (reference) |
| `cultures.json` | `Shared/cultures.json` | 31 cultures (enabled/disabled) |
| `deliverable_types.json` | `Shared/deliverable_types.json` | Types de livrables |
| `mail.json` | `Shared/mail.json` | Config SMTP/IMAP/templates email |
| `discord.json` | `Shared/discord.json` | Config Discord |
| `hitl.json` | `Shared/hitl.json` | Config HITL (auth, Google OAuth) |
| `others.json` | `Shared/others.json` | Password reset, domaines |
| `git.json` | `Shared/git.json` | Config git Shared |
| `teams.json` | `Shared/Teams/teams.json` | Liste equipes template |
| `mcp_servers.json` | `Shared/Teams/mcp_servers.json` | Serveurs MCP template |
| `mcp_catalog.csv` | `Shared/Teams/mcp_catalog.csv` | Catalogue MCP (29 serveurs) |
| `agents_registry.json` | `Shared/Teams/{dir}/agents_registry.json` | Registry equipe template |
| `agent_mcp_access.json` | `Shared/Teams/{dir}/agent_mcp_access.json` | MCP access template |
| `Workflow.json` | `Shared/Teams/{dir}/Workflow.json` | Workflow template |
| `orchestrator_prompt.md` | `Shared/Teams/{dir}/orchestrator_prompt.md` | Prompt orch genere (cache) |
| `orch_{agent_id}.md` | `Shared/Teams/{dir}/orch_{agent_id}.md` | Carte orch par agent |
| `report.md` | `Shared/Teams/{dir}/report.md` | Rapport coherence |
| `agent.json` | `Shared/Agents/{id}/agent.json` | Config agent catalogue |
| `prompt.md` | `Shared/Agents/{id}/prompt.md` | Prompt principal |
| `identity.md` | `Shared/Agents/{id}/identity.md` | Identite (optionnel) |
| `role_*.md` | `Shared/Agents/{id}/role_*.md` | Roles (0..N) |
| `mission_*.md` | `Shared/Agents/{id}/mission_*.md` | Missions (0..N) |
| `skill_*.md` | `Shared/Agents/{id}/skill_*.md` | Competences (0..N) |
| `{id}_assign.md` | `Shared/Agents/{id}/{id}_assign.md` | Exemples assignation |
| `{id}_unassign.md` | `Shared/Agents/{id}/{id}_unassign.md` | Exemples non-assignation |
| `*.md` | `Shared/Prompts/{culture}/*.md` | Prompts systeme + meta-prompts |
| `*.md` | `Shared/Models/{culture}/*.md` | Models (templates de documents) |
| `{culture}.json` | `Shared/i18n/{culture}.json` | Traductions par culture |
| `project.json` | `Shared/Projects/{id}/project.json` | Config projet |
| `*.wrk.json` | `Shared/Projects/{id}/*.wrk.json` | Workflows par projet |
| `Dockerfile.*` | `Shared/Dockerfiles/` | Dockerfiles template |
| `entrypoint.*.sh` | `Shared/Dockerfiles/` | Entrypoints associes |

### 14.3 Fichier .env

| Fichier | Chemin | Contenu |
|---|---|---|
| `.env` | Racine projet | Tous les secrets : cles API, tokens, mots de passe, URIs |

---

## 15. Modals et popups

### 15.1 Modal generique (inline)

Utilisee via `showModal(html, cssClass)` → injectee dans `#modal-container`.

| Modal | Cas d'utilisation |
|---|---|
| Confirmation | `confirmModal(message)` → Annuler/Confirmer |
| Ajout variable .env | Champs : Cle, Valeur, Commentaire section |
| Coller variables .env | Textarea format `KEY=VALUE` |

### 15.2 Modals LLM Providers

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | "+ Ajouter" provider | id, type (select 9 types), model, env_key, description, base_url, azure_endpoint, azure_deployment, api_version | Ajouter → `POST /api/llm/providers/provider` |
| (inline) | Editer provider | Memes champs pre-remplis | Sauvegarder → `PUT /api/llm/providers/provider/{id}` |
| (inline) | "+ Ajouter" throttling | env_key, RPM, TPM | Ajouter → `PUT /api/llm/providers/throttling` |
| `#modal-copy-llm` | "Copier depuis Configuration" | Checkboxes par provider absent | Copier → merge dans `config/llm_providers.json` |
| (inline) | Conflits import | Table : provider, existing vs imported, radio keep/overwrite | Resoudre → `POST /api/llm/providers/resolve` |

### 15.3 Modals MCP

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | "+ Installer un service" | Liste catalogue avec recherche, variables env a renseigner | Installer → `POST /api/mcp/install/{id}` |
| `#modal-copy-mcp` | "Copier depuis Configuration" | Checkboxes par serveur Shared absent | Copier → `POST /api/mcp/copy-from-template` |

### 15.4 Modals Agents

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | "+ Nouvel agent" | id, name, description, type, llm | Creer → `POST /api/shared-agents` |
| (inline) | Importer agent | File upload (.zip), optionnel rename | Importer → `POST /api/shared-agents/import` |
| `#modal-copy-agents` | "Copier depuis Configuration" | Checkboxes par agent Shared absent | Copier → `POST /api/prod-agents/copy-from-config` |

### 15.5 Modals Equipes

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | "+ Ajouter" equipe template | id, name, description | Creer → `PUT /api/templates/teams` |
| `#modal-copy-teams` | "Copier depuis Configuration" | Checkboxes par equipe + alerte agents manquants | Copier → `POST /api/prod-teams/copy-from-config` |

### 15.6 Modals Projets

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | "+ Projet" | id, name, description, team (select) | Creer → `POST /api/templates/projects` |
| (inline) | Editer projet | name, description, team | Sauvegarder → `PUT /api/templates/projects/{id}` |
| (inline) | "+ Workflow" | name, mode (vide ou genere par LLM) | Creer → `POST .../workflows` ou `.../workflows/generate` |
| `#modal-copy-projects` | "Copier depuis Configuration" | Checkboxes + alerte equipe manquante | Copier → `POST /api/prod-projects/copy-from-config` |
| (inline, `modal-confirm`) | Crayon "Categories" dans sidebar workflow | Liste editable : input nom categorie + bouton "+" sous-cat + "x" supprimer ; sous-categories indentees avec border-left ; bouton "+ Ajouter une categorie" | Appliquer → ecrit dans `_wf.data.categories`, nettoie refs orphelines, re-render |

### 15.7 Modals Prompts et Models

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | "+" nouveau prompt/model | Nom (doit finir par .md) | Creer fichier vide |
| `#modal-copy-prompts` | "Copier depuis Configuration" | Checkboxes par fichier | Copier → `POST /api/prod-prompts/copy-from-config` |
| `#modal-copy-models` | "Copier depuis Configuration" | Checkboxes par fichier | Copier → `POST /api/prod-models/copy-from-config` |

### 15.8 Modals Dockerfiles

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | "+" nouveau Dockerfile | Label (ex: `agent`, `worker`) | Cree `Dockerfile.{label}` + `entrypoint.{label}.sh` |
| `#modal-copy-dockerfiles` | "Copier depuis Configuration" | Checkboxes par Dockerfile | Copier Shared → config |
| (inline) | Build Dockerfile | Console SSE avec output ligne par ligne | Build Docker → flux SSE |

### 15.9 Modals Mail

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| `#modal-smtp-edit` | "+ Ajouter" / Editer SMTP | name, preset (select), host, port, TLS (toggle), SSL (toggle), user, password_env, from_address, from_name | Enregistrer → sauvegarde dans `mail.json` |
| `#modal-imap-edit` | "+ Ajouter" / Editer IMAP | name, preset, host, port, SSL (toggle), user, password_env | Enregistrer |
| `#modal-tpl-mail-edit` | "+ Ajouter" / Editer template | name, subject, body (textarea) | Enregistrer |

### 15.10 Modals Securite

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| `#modal-add-apikey` | "+ Nouvelle cle" | name, teams (multi-select), agents (multi-select), scopes (checkboxes), expires (select) | Generer → `POST /api/keys` |
| `#modal-show-apikey` | Apres generation | Token (readonly textarea, copier), config MCP exemple | Copier et fermer |

### 15.11 Modals Divers

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | "+ Ajouter" type livrable | key (delivers_xxx), label | Creer → `POST /api/templates/deliverable-types` |

### 15.12 Modals Git

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | Commit | Message de commit (textarea) | Commit + push → `POST /api/git/{repo}/commit` |
| (inline) | Force push | Confirmation "Des commits distants seront ecrases" | Push force → `POST /api/git/{repo}/push` |
| (inline) | Force pull | Confirmation "Modifications locales perdues" | Pull force → `POST /api/git/{repo}/pull` |
| (inline) | Rollback | Confirmation "Restaurer version {hash}" | Checkout → `POST /api/git/{repo}/checkout/{hash}` |
| (inline) | Version browser | Arborescence navigable + preview fichiers | Browse → `GET .../version-browse/{session}/tree` |

### 15.13 Modals Utilisateurs

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | "+ Creer" | email, role (select), equipes (multi-select) | Creer → `POST /api/hitl/users` |
| (inline) | Editer | display_name, role, is_active (toggle), equipes | Sauvegarder → `PUT /api/hitl/users/{id}` |
| Confirmation | Supprimer | Message "Supprimer l'utilisateur ?" | Supprimer → `DELETE /api/hitl/users/{id}` |

### 15.14 Modals HITL

| Modal ID | Declencheur | Champs | Actions |
|---|---|---|---|
| (inline) | Repondre | Textarea reponse, reviewer (pre-rempli "admin") | Repondre → `POST /api/hitl/{id}/respond` |
| Confirmation | Annuler | Message "Annuler cette requete ?" | Annuler → `POST /api/hitl/{id}/cancel` |

---

## Annexes

### A. Variables CSS principales

```css
--bg-primary: #0f172a;
--bg-secondary: #1e293b;
--bg-card: #1e293b;
--bg-input: #334155;
--text-primary: #f1f5f9;
--text-secondary: #94a3b8;
--accent: #3b82f6;
--accent-hover: #2563eb;
--danger: #ef4444;
--success: #22c55e;
--warning: #f59e0b;
--border: #334155;
```

### B. Meta-prompts utilises

| Fichier | Utilise par | Description |
|---|---|---|
| `GenerateAgent.md` | `/api/shared-agents/{id}/chat` | Chat builder d'agent |
| `createAgent.md` | `/api/agents/generate-prompt` | Generation prompt agent |
| `Missions.md` | `/api/agents/generate-mission` | Generation instruction de step |
| `Assignations.md` | `/api/agents/generate-assign` | Generation exemples assignation |
| `UnAssignation.md` | `/api/agents/generate-unassign` | Generation exemples non-assignation |
| `WriteDescription.md` | `/api/agents/generate-description` | Generation description livrable |
| `CreateWorkflow.md` | `/api/templates/projects/.../generate` | Generation workflow complet |
| `SkillMatcher.md` | `/api/templates/projects/.../skillmatch` | Matching roles/missions/skills |
| `translateOrchestrator.md` | `/api/templates/teams/.../orchestrator/build` | Generation carte orchestrateur |
| `CheckTeamCoherence.md` | `/api/templates/teams/.../coherence/check` | Verification coherence equipe |

### C. Toast notifications

| Type | Couleur | Cas d'utilisation |
|---|---|---|
| `success` | Vert | Operation reussie |
| `error` | Rouge | Erreur API ou validation |
| `info` | Bleu | Information generale |

Duree : 4 secondes, coin superieur droit, animation `slideIn`.

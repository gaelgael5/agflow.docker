# Console HITL (ag.flow Manager) — Specifications fonctionnelles

> **Version** : 2026-03-21
> **Port** : 8090
> **Stack** : FastAPI (Python) + Vanilla JS SPA
> **Base de donnees** : PostgreSQL (schema `project`)
> **Temps reel** : WebSocket + PG NOTIFY

---

## 1. Vue d'ensemble

### 1.1 Objectif

La console HITL (Human-In-The-Loop), aussi nommee **ag.flow Manager**, est l'interface web principale pour :

- **Repondre aux questions des agents IA** (approbations, questions ouvertes, validations de phase)
- **Gerer les projets** (creation, suivi, issues, dependencies, workflow)
- **Consulter les livrables** produits par les agents et les valider/rejeter
- **Gerer les membres** des equipes (invitation, roles, activation)
- **Discuter directement avec les agents** via un chat integre
- **Suivre l'activite** en temps reel (events, logs, metriques)

### 1.2 Architecture

```
Navigateur (SPA)
    |
    +--- REST API (FastAPI, port 8090)
    |       |
    |       +--- PostgreSQL (schema project.*)
    |       +--- Gateway LangGraph API (port 8123, via httpx)
    |       +--- SMTP (envoi emails de reset)
    |       +--- Google OAuth (verification tokens)
    |
    +--- WebSocket (/api/teams/{team_id}/ws)
            |
            +--- PG NOTIFY (hitl_chat, hitl_request)
```

### 1.3 Fichiers source

| Fichier | Role |
|---|---|
| `hitl/server.py` | Backend FastAPI complet |
| `hitl/static/index.html` | Page HTML unique (SPA shell) |
| `hitl/static/js/app.js` | Frontend JavaScript (SPA, ~2400 lignes) |
| `hitl/static/css/style.css` | Design system dark mode (inspire de Linear) |
| `hitl/static/reset-password.html` | Page de reset mot de passe |

---

## 2. Authentification

### 2.1 Modele d'authentification

L'application utilise des **JWT (JSON Web Tokens)** signes avec l'algorithme **HS256**. Le secret provient de :

1. Variable d'environnement `HITL_JWT_SECRET`
2. Fallback : `MCP_SECRET`
3. Fallback ultime : `"change-me-hitl-secret"`

Si le secret fait moins de 32 octets, il est hache via SHA-256 pour atteindre la taille minimale requise par RFC 7518.

### 2.2 Contenu du JWT

| Champ | Type | Description |
|---|---|---|
| `sub` | string | ID utilisateur (integer serialise) |
| `email` | string | Email de l'utilisateur |
| `role` | string | Role global : `undefined`, `member`, `admin` |
| `teams` | string[] | Liste des team_id auxquels l'utilisateur a acces |
| `exp` | datetime | Expiration (par defaut 24h, configurable via `hitl.json`) |

### 2.3 Authentification locale (email/mot de passe)

#### Inscription

1. L'utilisateur clique "Inscription" sur l'ecran de login
2. Saisie : **email** + **culture** (fr, en, es, de, it, pt)
3. `POST /api/auth/register` avec `{ email, culture }`
4. Le serveur genere un **mot de passe temporaire** (12 caracteres aleatoires)
5. Cree l'utilisateur en base avec `role = 'undefined'`, `auth_type = 'local'`
6. Envoie un **email de reinitialisation** avec le mot de passe temporaire (via SMTP configure dans `mail.json`)
7. L'utilisateur recoit un message : "Compte cree. Un email de reinitialisation vous sera envoye."
8. L'utilisateur est renvoye a l'ecran de login

**Note** : Le role `undefined` empeche toute connexion. Un administrateur doit valider le compte et assigner un role (`member` ou `admin`).

#### Connexion

1. Saisie : **email** + **mot de passe**
2. `POST /api/auth/login` avec `{ email, password }`
3. Verifications :
   - L'utilisateur existe en base
   - Le type d'auth est `local` (pas `google`)
   - Le mot de passe est verifie via bcrypt (tronque a 72 octets)
   - Le compte est actif (`is_active = true`)
   - Le role n'est pas `undefined`
4. En cas de succes : retourne `{ token, user: { id, email, display_name, role, teams } }`
5. Le token est stocke dans `localStorage` sous la cle `hitl_token`
6. Met a jour `last_login` en base

#### Reinitialisation de mot de passe

1. L'utilisateur accede a `/reset-password?mail=xxx&pwd=yyy` (lien recu par email)
2. Ou bien via `POST /api/auth/reset-password` avec `{ email, old_password, new_password }`
3. Verifications :
   - L'utilisateur existe
   - Le type d'auth est `local`
   - L'ancien mot de passe est correct
   - Le nouveau fait au moins 6 caracteres
4. Le hash bcrypt est mis a jour en base

#### Troncature bcrypt

Les mots de passe sont tronques a 72 octets (limite bcrypt) avant hachage et verification : `password.encode("utf-8")[:72].decode("utf-8", errors="ignore")`.

### 2.4 Authentification Google OAuth

#### Prerequis

- `google_oauth.enabled = true` dans `config/hitl.json`
- `google_oauth.client_id` renseigne
- Script Google Identity Services charge dans le HTML : `https://accounts.google.com/gsi/client`

#### Flux

1. Le frontend recupere le `client_id` via `GET /api/auth/google/client-id`
2. Le bouton Google est rendu via `google.accounts.id.renderButton()`
3. L'utilisateur clique "Sign in with Google"
4. Google retourne un ID token (credential)
5. `POST /api/auth/google` avec `{ credential }`
6. Le serveur verifie le token via `https://oauth2.googleapis.com/tokeninfo?id_token=...`
7. Verifications :
   - `aud` (audience) correspond au `client_id` configure
   - `email_verified` est `true`
   - Le domaine de l'email est dans `allowed_domains` (si configure)
8. Si l'utilisateur n'existe pas : creation avec `role = 'undefined'`, `auth_type = 'google'`, `password_hash = NULL`
9. Si le role est `undefined` : HTTP 403 "En attente de validation"
10. Sinon : retourne le JWT

#### Restriction par domaine

Si `google_oauth.allowed_domains` contient des valeurs (ex: `["company.com"]`), seuls les emails de ces domaines sont acceptes. Si la liste est vide, tous les domaines sont autorises.

### 2.5 Roles

| Role | Code | Acces |
|---|---|---|
| **En attente** | `undefined` | Aucun acces. Connexion refusee avec HTTP 403. |
| **Membre** | `member` | Acces aux equipes assignees. Peut repondre aux questions, gerer les issues, consulter les livrables. |
| **Administrateur** | `admin` | Acces complet a toutes les equipes. Peut inviter/supprimer des membres, reset des threads, gerer les roles. |

### 2.6 Deconnexion

1. Clic sur le bouton "logout" en bas de la sidebar
2. Supprime le token de `localStorage`
3. Ferme la connexion WebSocket
4. Affiche l'ecran de login

### 2.7 Seed administrateur

Au premier demarrage, si la table `hitl_users` est vide :

- Cree un admin avec `HITL_ADMIN_EMAIL` (defaut: `admin@langgraph.local`) et `HITL_ADMIN_PASSWORD` (defaut: `admin`)
- L'admin est automatiquement ajoute a toutes les equipes de `teams.json`

---

## 3. Pages et navigation

### 3.1 Structure de l'interface

L'application est un SPA (Single Page Application) compose de :

- **Ecran de login** (`#login-screen`) : formulaire email/password + bouton Google + lien inscription
- **Ecran d'inscription** (`#register-screen`) : formulaire email + culture
- **Application principale** (`#app`) : layout flex horizontal
  - **Sidebar gauche** (220px, collapsible a 52px)
  - **Zone principale** (header + contenu)

### 3.2 Sidebar

La sidebar est divisee en sections :

#### Section "Navigation" (globale)

| Item | Vue | Badge | Description |
|---|---|---|---|
| Inbox | `pm-inbox` | Nombre de notifications non lues | Notifications PM (mentions, assignments, reviews) |
| Issues | `pm-issues` | — | Toutes les issues par equipe |
| Reviews | `pm-reviews` | — | Pull requests |
| Pulse | `pm-pulse` | — | Metriques et sante des dependencies |

#### Section "Workspace"

| Item | Vue | Description |
|---|---|---|
| Projects | `pm-projects` | Liste des projets |
| Logs | `logs` | Logs Docker des services |

#### Section "Teams"

Pour chaque equipe de l'utilisateur, un groupe expansible avec :

| Sous-item | Vue | Description |
|---|---|---|
| Agents | `agents` | Liste des agents de l'equipe, avec chat integre |
| Livrables | `deliverables` | Livrables produits par les agents |
| Activite | `activity` | Timeline des events (agents + PM) |
| Members | `members` | Gestion des membres de l'equipe |

#### Pied de sidebar

- Avatar + nom de l'utilisateur connecte
- Bouton "logout"
- Version de l'application

#### Collapse

Clic sur le header "Production" collapse la sidebar a 52px (icones seulement, labels masques).

### 3.3 Recherche globale

Champ de recherche en haut de la sidebar avec raccourci `Cmd+K`. (Placeholder fonctionnel, pas de logique de recherche implementee cote serveur.)

---

## 4. Inbox (Notifications PM)

### 4.1 Description

La vue Inbox affiche les notifications du Production Manager liees a l'utilisateur courant.

### 4.2 Onglets de filtrage

| Onglet | Filtre |
|---|---|
| All | Toutes les notifications |
| Mentions | `type = 'mention'` |
| Assigned | `type = 'assign'` |
| Reviews | `type = 'review'` |

### 4.3 Elements d'une notification

| Element | Description |
|---|---|
| Pastille bleue | Indicateur non lu (visible si `read = false`) |
| Avatar | Initiales de l'auteur ou "System" |
| Texte principal | Contenu de la notification |
| Sous-texte | ID de l'issue liee |
| Temps relatif | "now", "5m", "2h", "3d" |

### 4.4 Actions

| Action | API | Description |
|---|---|---|
| Clic sur une notification | `PUT /api/pm/inbox/{id}/read` | Marque comme lue |
| "Mark all read" | `PUT /api/pm/inbox/read-all` | Marque toutes comme lues |

### 4.5 Types de notification

`mention`, `assign`, `comment`, `status`, `review`, `blocked`, `unblocked`, `dependency_added`

---

## 5. Issues

### 5.1 Vue liste

Affiche toutes les issues de l'equipe active, avec regroupement configurable.

### 5.2 Modes de regroupement

| Mode | Cle de groupe | Description |
|---|---|---|
| Status | `status` | Backlog, Todo, In Progress, In Review, Done |
| Team | `team_id` | Par equipe |
| Assignee | `assignee` | Par assignataire (ou "Unassigned") |
| Dependency | Calcule | Blocked / Blocking others / No dependencies |

### 5.3 Elements d'une ligne issue

| Element | Description |
|---|---|
| Badge priorite | 4 barres (P1 rouge, P2 orange, P3 jaune, P4 gris) |
| ID | Ex: "TEAM1-042" |
| Icone statut | Cercle pointille (backlog), cercle (todo), demi-cercle (in-progress), horloge (in-review), check (done) |
| Icone cadenas | Si bloquee par une autre issue |
| Indicateur "blocking" | Nombre d'issues bloquees par celle-ci |
| Titre | Texte de l'issue |
| Tags | 2 tags max visibles |
| Avatar assignataire | Si assigne |
| Temps | Temps relatif depuis creation |

### 5.4 Panel de detail

Clic sur une issue ouvre un panel coulissant a droite avec :

- **ID** de l'issue
- **Titre**
- **Banniere "Blocked"** si bloquee
- **Proprietes** : Status, Priority, Assignee, Team, Created
- **Tags** : liste complete
- **Dependencies** : liste des relations (blocks, blocked-by, relates-to, parent, sub-task, duplicates)
  - Chaque relation : badge type + ID cliquable + statut + titre + bouton supprimer
- **Bouton "Add dependency"** : ouvre le modal d'ajout de relation

### 5.5 Creation d'issue

Modal avec champs :

| Champ | Type | Obligatoire | Options |
|---|---|---|---|
| Title | text | Oui | — |
| Description | textarea | Non | — |
| Priority | select | Non | P1-Critical, P2-High, P3-Medium (defaut), P4-Low |
| Status | select | Non | Backlog, Todo (defaut), In Progress, In Review, Done |
| Assignee | text | Non | — |
| Tags | text | Non | Separes par virgules |

### 5.6 Modal d'ajout de relation

| Champ | Type | Options |
|---|---|---|
| Type | select | Blocks, Relates to, Parent of, Duplicates |
| Target Issue ID | text | Ex: "ENG-003" |
| Reason | text | Raison optionnelle |

---

## 6. Reviews (Pull Requests)

### 6.1 Description

Liste des pull requests avec filtrage par onglet.

### 6.2 Onglets

| Onglet | Filtre |
|---|---|
| All PRs | Toutes |
| Needs Review | `status = 'pending'` |
| Approved | `status = 'approved'` |
| Drafts | `status = 'draft'` |

### 6.3 Elements d'une ligne PR

| Element | Description |
|---|---|
| Avatar auteur | Initiales |
| ID | Identifiant de la PR |
| Titre | Texte de la PR |
| Auteur | Nom |
| Issue liee | ID de l'issue |
| Nombre de fichiers | Ex: "5 files" |
| Diff | "+42 / -18" (additions/deletions) |
| Badge statut | Pending (orange), Approved (vert), Changes (rouge), Draft (gris) |

---

## 7. Pulse (Metriques)

### 7.1 Description

Dashboard de metriques aggregees sur toutes les issues.

### 7.2 Composants

#### Cartes de metriques (row superieur)

| Metrique | Source | Note |
|---|---|---|
| Velocity | Calculee au runtime | Placeholder "---" |
| Burndown | Calculee au runtime | Placeholder "---" |
| Cycle Time | Calculee au runtime | Placeholder "---" |
| Throughput | Calculee au runtime | Placeholder "---" |

#### Distribution des statuts

Barre horizontale coloree segmentee par statut (done, in-review, in-progress, todo, backlog) avec legende et pourcentages.

#### Activite d'equipe

Liste des assignataires avec :
- Avatar + nom
- Barre de progression (done / total)
- Compteur "done" et "active"

#### Sante des dependencies

- Cartes : Blocked Issues / Blocking Issues / Dep. Chains
- Liste des goulots d'etranglement (issues qui bloquent le plus d'autres)

---

## 8. Projects

### 8.1 Liste des projets

Grille de cartes avec pour chaque projet :

| Element | Description |
|---|---|
| Pastille couleur | Couleur du projet |
| Nom | Nom du projet |
| Badge statut | On Track (vert), At Risk (orange), Off Track (rouge) |
| Barre de progression | Issues done / total |
| Indicateurs dependencies | Blocked / Blocking (si non zero) |
| Lead | Avatar + nom du lead |

### 8.2 Detail d'un projet

#### En-tete

- Breadcrumb "Projects > Nom du projet"
- Badge statut
- Bouton "+" pour creer une issue
- Meta : Lead, dates, nombre de membres, indicateurs blocked/blocking
- Boutons : "Lancer les agents" (lance le workflow) + "Mettre en pause"

#### Barre de workflow

5 phases visuelles (Discovery, Design, Build, Ship, Iterate). La phase courante est mise en evidence (fond bleu). Les phases terminees sont vertes. Les phases a venir sont grises.

#### Panel agents de la phase courante

Affiche les agents organises par groupes paralleles (A, B, C) avec leur statut :
- Cercle vert + check : complete
- Triangle bleu : en cours (avec icone coeur pulsant)
- Croix rouge : erreur
- Cercle vide : en attente

#### Pipeline visuel (status bar)

Barre segmentee par statut des issues du projet.

#### Onglets

| Onglet | Contenu |
|---|---|
| **Issues** | Issues du projet groupees par statut, avec panel de detail |
| **Dependencies** | Graphe SVG interactif des dependencies entre issues (noeuds + fleches) |
| **Team** | Grille des agents (cliquables pour chat) + liste des membres avec progression |
| **Activity** | Timeline fusionnee (PM activity + agent events) triee par date decroissante |
| **Workflow** | Vue detaillee par phase : agents, livrables, validations, remarques |

### 8.3 Onglet Workflow (detail)

Pour chaque phase (de la courante a la plus ancienne) :

- **En-tete** : icone + nom de phase + badge statut (TERMINEE / EN COURS / A VENIR) + bouton Reset
- **Agents** : par groupe parallele avec statut
- **Livrables** : chaque livrable defini dans `Workflow.json` avec :
  - Icone de statut (check vert = produit, point jaune = en attente, croix rouge = rejete)
  - Nom + agent responsable + type (DOC, CODE, DESIGN, AUTO, TACHES, SPECS, CONTRAT) + indicateur REQ/OPT
  - Boutons de validation : Approuver (check vert), Rejeter (croix rouge)
  - Bouton remarque (bulle) : ouvre un formulaire de remarque textuelle
  - Bouton editer (crayon) : mode edition du contenu markdown
  - Contenu expandable (details/summary) avec rendu Markdown

#### Banniere de transition de phase

Quand tous les livrables d'une phase sont produits, une banniere apparait en haut avec :
- Message "Phase X terminee"
- Bouton "Approuver > Phase suivante"
- Bouton "Refuser"

#### Reset de phase

Bouton "Reset" sur chaque phase + bouton "Reset total" en bas. Le reset :
1. Supprime les livrables sur disque (structure legacy + nouvelle)
2. Annule les HITL requests pending
3. Notifie le gateway pour reinitialiser l'etat
4. Rafraichit les badges HITL

### 8.4 Creation de projet (wizard en 4 etapes)

#### Etape 1 : Setup

| Champ | Type | Obligatoire |
|---|---|---|
| Project name | text | Oui |
| Team | selection de carte | Oui |
| Language | select (fr/en/es/de/it/pt) | Oui |
| Start date | date | Non |
| Target date | date | Non |

Lien "Or skip and create empty project" pour creation rapide.

#### Etape 2 : Sources

Trois modes :
- **Nouveau projet** : aucune source
- **Sources existantes** : upload de documents + analyse d'URL + clone de repo Git
- **Importer un projet** : upload d'archive (.zip, .tar.gz)

#### Etape 3 : AI Planning

L'IA analyse les sources et genere automatiquement des issues + relations. L'utilisateur peut interagir via chat pour affiner le plan.

#### Etape 4 : Review

Revue des issues generees, modification possible, puis creation du projet.

---

## 9. Agents

### 9.1 Liste des agents

Grille de cartes pour chaque agent de l'equipe, tire de `agents_registry.json`.

| Element | Description |
|---|---|
| Pastille online/offline | Vert si activite recente, gris sinon |
| Nom | Nom de l'agent |
| Tag ID | Identifiant technique (ex: `lead_dev`) |
| LLM | Modele utilise (ex: "claude-sonnet" ou "default (ollama)") |
| Pending | Nombre de questions HITL en attente |

### 9.2 Chat avec un agent

Clic sur une carte d'agent ouvre une vue chat :

- **En-tete** : bouton retour + nom + ID + LLM + bouton "Clear"
- **Historique** : messages affiches chronologiquement
  - Messages utilisateur : bulle a droite (bleu)
  - Messages agent : bulle a gauche avec rendu Markdown (tables, listes, code, JSON)
- **Champ de saisie** : textarea + bouton envoyer
- **Indicateur de chargement** : bulles animees pendant l'attente de reponse

Le chat utilise un `thread_id = "hitl-chat-{team_id}-{agent_id}"` distinct du workflow projet. Les messages sont persistes en base.

#### Temps reel

Le frontend s'abonne via WebSocket (`watch_chat` / `unwatch_chat`) pour recevoir les messages en temps reel via PG NOTIFY.

---

## 10. Livrables

### 10.1 Vue par equipe

Liste les projets qui ont des livrables sur disque, avec les phases disponibles.

### 10.2 Vue par projet

Affiche les livrables organises par phase, avec le contenu Markdown rendu.

### 10.3 Actions sur un livrable

| Action | Description |
|---|---|
| **Valider** | `POST /api/projects/{slug}/deliverables/{phase}/{agent_id}/validate` avec `verdict = "approved"` |
| **Rejeter** | Meme endpoint avec `verdict = "rejected"` |
| **Remarque** | `POST /api/projects/{slug}/deliverables/{phase}/{agent_id}/remark` — envoie une remarque textuelle + re-invoque l'agent via gateway |
| **Editer** | `PUT /api/projects/{slug}/deliverables/{phase}/{agent_id}/{key}` — ecrase le contenu Markdown |

---

## 11. Membres

### 11.1 Liste des membres

Tableau des membres de l'equipe active avec :

| Colonne | Description |
|---|---|
| ID | Identifiant |
| Email | Adresse email |
| Display name | Nom affiche |
| Global role | Role global (admin/member/undefined) |
| Team role | Role dans l'equipe |
| Last login | Date de derniere connexion (format relatif) |
| Active | Statut actif/inactif |

### 11.2 Invitation d'un membre

Modal avec champs :

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| Email | text | Oui | Email du membre |
| Nom | text | Non | Nom affiche |
| Mot de passe initial | text | Non | Defaut: "changeme" |
| Role | select | Non | member (defaut) / admin |

Si l'utilisateur existe deja en base, il est simplement ajoute a l'equipe. Sinon, un nouveau compte est cree avec `role = 'member'`.

### 11.3 Suppression d'un membre

Bouton de suppression qui retire le membre de l'equipe (admin requis). Ne supprime pas le compte utilisateur.

---

## 12. Logs

### 12.1 Description

Affiche les logs Docker des services LangGraph.

### 12.2 Services autorises

`langgraph-api`, `langgraph-discord`, `langgraph-mail`, `langgraph-hitl`, `langgraph-admin`

### 12.3 Parametres

| Parametre | Type | Defaut | Description |
|---|---|---|---|
| service | string | langgraph-api | Nom du service Docker |
| lines | int | 200 | Nombre de lignes (10-5000) |

---

## 13. Activite

### 13.1 Description

Timeline fusionnant deux sources :

1. **Activite PM** (`pm_activity`) : actions manuelles (creation d'issue, changement de statut, etc.)
2. **Events agents** (via gateway `/events`) : agent_start, agent_complete, agent_error, agent_dispatch, phase_transition, human_gate, tool_call

### 13.2 Elements d'une entree

| Element | Description |
|---|---|
| Date | JJ/MM |
| Heure | HH:MM:SS |
| Badge source | "AGENT" (bleu) ou "PM" (gris) |
| Icone | Selon le type d'event |
| Acteur | Agent ID ou nom d'utilisateur |
| Label | Type d'event |
| Detail | Description contextuelle |

### 13.3 Banniere "En attente"

Si des agents sont en cours d'execution (start sans complete/error), une banniere bleue s'affiche en haut avec la liste des agents actifs et le temps ecoule.

---

## 14. API Endpoints

### 14.1 Authentification

| Methode | Path | Auth | Corps requete | Description |
|---|---|---|---|---|
| POST | `/api/auth/login` | Non | `{ email, password }` | Connexion locale |
| POST | `/api/auth/register` | Non | `{ email, culture }` | Inscription (role undefined) |
| POST | `/api/auth/google` | Non | `{ credential }` | Connexion Google OAuth |
| GET | `/api/auth/google/client-id` | Non | — | Retourne le Client ID Google |
| GET | `/api/auth/me` | JWT | — | Profil de l'utilisateur courant |
| POST | `/api/auth/reset-password` | Non | `{ email, old_password, new_password }` | Changement de mot de passe |

#### Reponse `/api/auth/login` et `/api/auth/google`

```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": "1",
    "email": "user@example.com",
    "display_name": "User",
    "role": "member",
    "teams": ["team1"]
  }
}
```

### 14.2 Equipes

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/teams` | JWT | Liste des equipes de l'utilisateur |

Reponse : liste de `{ id, name, directory }`. Ne retourne que les equipes qui existent a la fois dans `hitl_team_members` ET `teams.json`.

### 14.3 Questions HITL

| Methode | Path | Auth | Parametres | Description |
|---|---|---|---|---|
| GET | `/api/teams/{team_id}/questions` | JWT | `?status=pending&limit=50` | Liste des questions HITL |
| GET | `/api/teams/{team_id}/questions/stats` | JWT | — | Compteurs par statut |
| GET | `/api/questions/{question_id}` | JWT | — | Detail d'une question |
| POST | `/api/questions/{question_id}/answer` | JWT | `{ response, action }` | Repondre a une question |

#### Actions possibles pour `answer`

| Action | Effet |
|---|---|
| `answer` | Reponse textuelle libre |
| `approve` | Approbation (response = "approved" si vide) |
| `reject` | Rejet (response = "rejected" si vide) |

Apres approbation d'une `phase_validation`, le serveur :
1. Annule les autres requests pending du meme thread/type
2. Notifie le gateway pour executer la transition de phase

#### Reponse d'une question

```json
{
  "id": "42",
  "thread_id": "project-team1-5",
  "agent_id": "requirements_analyst",
  "team_id": "team1",
  "request_type": "question",
  "prompt": "Quel framework frontend utiliser ?",
  "context": { "type": "phase_validation", "current_phase": "discovery", "next_phase": "design" },
  "channel": "web",
  "status": "pending",
  "response": null,
  "reviewer": null,
  "response_channel": null,
  "created_at": "2026-03-20T10:30:00+00:00",
  "answered_at": null,
  "expires_at": "2026-03-20T11:00:00+00:00",
  "reminded_at": null,
  "remind_count": 0,
  "project_slug": "performancetracker",
  "project_name": "PerformanceTracker"
}
```

### 14.4 Threads

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/threads` | JWT | Liste des threads connus (depuis hitl_requests) |
| POST | `/api/threads/reset` | JWT (admin) | Reset un thread via gateway |

### 14.5 Agents

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/teams/{team_id}/agents` | JWT | Liste des agents (depuis registry + stats) |

#### Reponse par agent

```json
{
  "id": "lead_dev",
  "name": "Lead Dev",
  "type": "single",
  "llm": "claude-sonnet",
  "pending": 2,
  "total": 15,
  "last_activity": "2026-03-20T14:30:00+00:00"
}
```

### 14.6 Chat agents

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/teams/{team_id}/agents/{agent_id}/chat` | JWT | Historique de chat (200 derniers messages) |
| POST | `/api/teams/{team_id}/agents/{agent_id}/chat` | JWT | Envoyer un message (invoque le gateway) |
| DELETE | `/api/teams/{team_id}/agents/{agent_id}/chat` | JWT | Effacer l'historique de chat |

Le `POST` :
1. Sauvegarde le message utilisateur en base
2. Appelle `POST /invoke` sur le gateway (direct_agent ou orchestrateur)
3. Sauvegarde la reponse de l'agent en base
4. Retourne `{ ok, reply }`

### 14.7 Membres

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/teams/{team_id}/members` | JWT | Liste des membres de l'equipe |
| POST | `/api/teams/{team_id}/members` | JWT | Inviter un membre |
| DELETE | `/api/teams/{team_id}/members/{user_id}` | JWT (admin) | Retirer un membre de l'equipe |

#### Corps invitation

```json
{
  "email": "membre@company.com",
  "display_name": "Prenom Nom",
  "password": "changeme",
  "role": "member"
}
```

### 14.8 Livrables

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/projects` | JWT | Liste des projets avec livrables sur disque |
| GET | `/api/projects/{slug}/deliverables` | JWT | Livrables d'un projet par phase |
| PUT | `/api/projects/{slug}/deliverables/{phase}/{agent_id}/{key}` | JWT | Modifier le contenu d'un livrable |
| POST | `/api/projects/{slug}/deliverables/{phase}/{agent_id}/verdict` | JWT | Verdict sur un livrable (legacy) |
| POST | `/api/projects/{slug}/deliverables/{phase}/{agent_id}/remark` | JWT | Soumettre une remarque |
| GET | `/api/projects/{slug}/deliverables/{phase}/{agent_id}/remarks` | JWT | Lire les remarques |
| POST | `/api/projects/{slug}/deliverables/{phase}/{agent_id}/validate` | JWT | Valider/rejeter + check phase |

#### Structure des livrables sur disque (nouvelle)

```
projects/{slug}/{team_id}/{workflow}/{iteration}:{phase}/{agent_id}/{key}.md
```

#### Structure legacy

```
projects/{slug}/deliverables/{phase}/{agent_id}.md
```

### 14.9 Production Manager — Projets

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/pm/projects` | JWT | Liste des projets PM |
| POST | `/api/pm/projects` | JWT | Creer un projet |
| GET | `/api/pm/projects/{id}` | JWT | Detail d'un projet (avec issues) |
| PUT | `/api/pm/projects/{id}` | JWT | Modifier un projet |
| DELETE | `/api/pm/projects/{id}` | JWT | Supprimer un projet |
| POST | `/api/pm/projects/launch-workflow` | JWT | Lancer le workflow agent |
| POST | `/api/pm/projects/{id}/pause-workflow` | JWT | Mettre en pause le workflow |
| GET | `/api/pm/projects/{id}/workflow-status` | JWT | Statut du workflow (proxy gateway) |
| POST | `/api/pm/projects/{id}/reset-phase` | JWT | Reset une phase et ses descendantes |
| GET | `/api/pm/projects/{id}/activity` | JWT | Historique d'activite |

#### Corps creation de projet

```json
{
  "name": "PerformanceTracker",
  "slug": "performancetracker",
  "description": "SaaS suivi performances sportives",
  "lead": "admin@langgraph.local",
  "team_id": "team1",
  "color": "#6366f1",
  "status": "on-track",
  "start_date": "2026-03-01",
  "target_date": "2026-06-30",
  "members": ["dev1@company.com"]
}
```

### 14.10 Production Manager — Issues

| Methode | Path | Auth | Parametres | Description |
|---|---|---|---|---|
| GET | `/api/pm/issues` | JWT | `?team_id=&project_id=&status=&assignee=` | Liste des issues |
| POST | `/api/pm/issues` | JWT | Corps `PMIssueCreate` | Creer une issue |
| GET | `/api/pm/issues/{id}` | JWT | — | Detail (avec relations) |
| PUT | `/api/pm/issues/{id}` | JWT | Corps `PMIssueUpdate` | Modifier une issue |
| DELETE | `/api/pm/issues/{id}` | JWT | — | Supprimer une issue |
| POST | `/api/pm/issues/bulk` | JWT | `{ issues, project_id, team_id }` | Creation en lot |

#### Identifiants d'issues

Les IDs sont generes sequentiellement par equipe : `{TEAM_PREFIX}-{SEQ:03d}` (ex: `TEAM1-001`). Un compteur par equipe est maintenu dans `pm_issue_counters`.

### 14.11 Production Manager — Relations

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/pm/issues/{id}/relations` | JWT | Relations (outgoing + incoming) |
| POST | `/api/pm/issues/{id}/relations` | JWT | Creer une relation |
| DELETE | `/api/pm/relations/{id}` | JWT | Supprimer une relation |
| POST | `/api/pm/relations/bulk` | JWT | Creation en lot avec mapping d'IDs |

#### Types de relations

| Type | Inverse affiche |
|---|---|
| `blocks` | `blocked-by` |
| `relates-to` | `relates-to` |
| `parent` | `sub-task` |
| `duplicates` | `duplicates` |

### 14.12 Production Manager — Reviews

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/pm/reviews` | JWT | Liste des PRs (`?status=`) |
| POST | `/api/pm/reviews` | JWT | Creer/upsert une PR |
| PUT | `/api/pm/reviews/{id}` | JWT | Modifier le statut d'une PR |

### 14.13 Production Manager — Inbox

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/pm/inbox` | JWT | Notifications de l'utilisateur (100 max) |
| PUT | `/api/pm/inbox/{id}/read` | JWT | Marquer une notification comme lue |
| PUT | `/api/pm/inbox/read-all` | JWT | Marquer toutes comme lues |

### 14.14 Production Manager — Pulse

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/pm/pulse` | JWT | Metriques globales |

#### Reponse

```json
{
  "status_distribution": { "backlog": 5, "todo": 3, "in-progress": 2, "in-review": 1, "done": 4 },
  "team_activity": [{ "name": "Alice", "total": 8, "completed": 4, "active": 2 }],
  "dependency_health": {
    "blocked": 2,
    "blocking": 3,
    "chains": 1,
    "bottlenecks": [{ "id": "TEAM1-005", "title": "Auth service", "status": "in-progress", "assignee": "Bob", "impact": 4 }]
  },
  "velocity": { "value": "---", "sub": "calculated at runtime" },
  "burndown": { "value": "---", "sub": "calculated at runtime" },
  "cycle_time": { "value": "---", "sub": "calculated at runtime" },
  "throughput": { "value": "---", "sub": "calculated at runtime" }
}
```

### 14.15 Production Manager — Fichiers projet

| Methode | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/pm/project-files/check` | JWT | Verifier si un projet existe sur disque |
| POST | `/api/pm/project-files/init` | JWT | Creer la structure de repertoires |
| POST | `/api/pm/project-files/{slug}/upload` | JWT | Uploader un document (max 50MB) |
| POST | `/api/pm/project-files/analyze-url` | JWT | Analyser une URL via LLM |
| POST | `/api/pm/project-files/clone-repo` | JWT | Cloner un repo Git (ou pull si deja clone) |
| POST | `/api/pm/project-files/import-archive` | JWT | Importer une archive (max 200MB) |
| GET | `/api/pm/project-files/{slug}/docs` | JWT | Lister les documents d'un projet |
| POST | `/api/pm/project-files/analyze` | JWT | Synthetiser les sources via LLM |

### 14.16 Production Manager — IA

| Methode | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/pm/ai/plan` | JWT | Generer des issues via LLM |

### 14.17 Workflow

| Methode | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/pm/sync-workflow` | JWT | Synchroniser les statuts d'issues avec le workflow |

### 14.18 Utilitaires

| Methode | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | Non | Sert `static/index.html` |
| GET | `/reset-password` | Non | Sert la page de reset password |
| GET | `/health` | Non | `{ status: "ok", service: "hitl-console" }` |
| GET | `/api/version` | Non | `{ version, last_update }` |
| GET | `/api/logs` | JWT | Logs Docker d'un service |
| GET | `/api/events` | JWT | Proxy vers gateway EventBus |

---

## 15. WebSocket

### 15.1 Connexion

```
ws[s]://{host}/api/teams/{team_id}/ws?token={jwt}
```

#### Authentification

Le token JWT est passe en query parameter. Si invalide :
- Code 4001 : Unauthorized (token invalide)
- Code 4003 : Forbidden (pas acces a l'equipe)

Le frontend ferme la connexion existante et en ouvre une nouvelle a chaque changement d'equipe.

### 15.2 Keepalive

Le serveur envoie un `{ type: "ping" }` toutes les 45 secondes d'inactivite. Le client repond `{ type: "pong" }`.

### 15.3 Events serveur vers client

| Type | Declencheur | Donnees | Action frontend |
|---|---|---|---|
| `ping` | Inactivite 45s | `{}` | Repondre `pong` |
| `new_question` | PG NOTIFY `hitl_request` | `{ id, agent_id, request_type, prompt, thread_id }` | Toast + notification browser + son + refresh badge + refresh inbox |
| `question_answered` | Apres reponse a une question | `{}` | Refresh badge + refresh inbox |
| `chat_message` | PG NOTIFY `hitl_chat` | Message complet | Ajout en temps reel dans le chat |
| `chat_activity` | PG NOTIFY `hitl_chat` | `{ agent_id }` | Refresh badges |
| `pm_inbox` | Nouvelle notification PM | `{}` | Refresh inbox badge + reload inbox |

### 15.4 Messages client vers serveur

| Type | Donnees | Description |
|---|---|---|
| `pong` | `{}` | Reponse au ping |
| `watch_chat` | `{ agent_id }` | S'abonner aux messages d'un agent |
| `unwatch_chat` | `{}` | Se desabonner du chat |

### 15.5 Reconnexion

Le client tente une reconnexion avec backoff exponentiel :
- Delai : `min(5000 * retryCount, 30000)` ms
- Maximum 10 tentatives
- Si code 4001/4003 : force le logout au lieu de reconnecter

### 15.6 Notifications navigateur

A la reception d'un `new_question` :
1. Affiche une notification browser (si permission accordee) avec titre "Validation requise" ou "Nouvelle question"
2. Joue un son (deux bips courts : 800Hz puis 1000Hz)
3. Affiche un toast dans l'interface

---

## 16. Base de donnees

Toutes les tables sont dans le schema `project`.

### 16.1 Table `hitl_users`

| Colonne | Type | Defaut | Description |
|---|---|---|---|
| `id` | SERIAL PRIMARY KEY | auto | Identifiant unique |
| `email` | TEXT UNIQUE NOT NULL | — | Email |
| `password_hash` | TEXT | NULL | Hash bcrypt (NULL pour Google) |
| `display_name` | TEXT | — | Nom affiche |
| `role` | TEXT | `'undefined'` | Role global : `undefined`, `member`, `admin` |
| `auth_type` | TEXT | `'local'` | Type d'auth : `local`, `google` |
| `culture` | TEXT | `'fr'` | Culture preferee |
| `is_active` | BOOLEAN | TRUE | Compte actif |
| `last_login` | TIMESTAMPTZ | NULL | Derniere connexion |

### 16.2 Table `hitl_team_members`

| Colonne | Type | Description |
|---|---|---|
| `user_id` | INTEGER (FK hitl_users) | Utilisateur |
| `team_id` | TEXT | Identifiant equipe |
| `role` | TEXT | Role dans l'equipe (`admin`, `member`) |
| PK | `(user_id, team_id)` | |

### 16.3 Table `hitl_requests`

| Colonne | Type | Description |
|---|---|---|
| `id` | SERIAL PRIMARY KEY | Identifiant |
| `thread_id` | TEXT | Thread LangGraph |
| `agent_id` | TEXT | Agent demandeur |
| `team_id` | TEXT | Equipe |
| `request_type` | TEXT | `question` ou `approval` |
| `prompt` | TEXT | Question ou resume |
| `context` | JSONB | Contexte additionnel (ex: `{ type: "phase_validation" }`) |
| `channel` | TEXT | Canal d'origine (discord, email, web) |
| `status` | TEXT | `pending`, `answered`, `timeout`, `cancelled` |
| `response` | TEXT | Reponse fournie |
| `reviewer` | TEXT | Email du revieweur |
| `response_channel` | TEXT | Canal de reponse |
| `created_at` | TIMESTAMPTZ | Date de creation |
| `answered_at` | TIMESTAMPTZ | Date de reponse |
| `expires_at` | TIMESTAMPTZ | Date d'expiration |
| `reminded_at` | TIMESTAMPTZ | Date de derniere relance |
| `remind_count` | INTEGER | Nombre de relances |

### 16.4 Table `hitl_chat_messages`

| Colonne | Type | Description |
|---|---|---|
| `id` | SERIAL PRIMARY KEY | Identifiant |
| `team_id` | TEXT | Equipe |
| `agent_id` | TEXT | Agent |
| `thread_id` | TEXT | Thread de chat (`hitl-chat-{team}-{agent}`) |
| `sender` | TEXT | Email de l'expediteur ou agent_id |
| `content` | TEXT | Contenu du message |
| `created_at` | TIMESTAMPTZ | Date |

Index : `(team_id, agent_id, thread_id, created_at)`

### 16.5 Table `pm_projects`

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| `id` | SERIAL PRIMARY KEY | — | Identifiant |
| `name` | TEXT NOT NULL | — | Nom |
| `slug` | TEXT | defaut `''` | Slug filesystem |
| `description` | TEXT | defaut `''` | Description |
| `lead` | TEXT NOT NULL | — | Email du lead |
| `team_id` | TEXT NOT NULL | — | Equipe |
| `color` | TEXT | defaut `'#6366f1'` | Couleur |
| `status` | TEXT | CHECK `on-track`, `at-risk`, `off-track` | Statut |
| `start_date` | DATE | — | Date de debut |
| `target_date` | DATE | — | Date cible |
| `created_by` | TEXT | — | Createur |
| `created_at` | TIMESTAMPTZ | NOW() | |
| `updated_at` | TIMESTAMPTZ | NOW() | |

### 16.6 Table `pm_project_members`

| Colonne | Type | Description |
|---|---|---|
| `project_id` | INTEGER (FK pm_projects, CASCADE) | Projet |
| `user_name` | TEXT | Nom d'utilisateur |
| `role` | TEXT CHECK `lead`, `member` | Role dans le projet |
| PK | `(project_id, user_name)` | |

### 16.7 Table `pm_issues`

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| `id` | TEXT PRIMARY KEY | — | Ex: "TEAM1-042" |
| `project_id` | INTEGER (FK pm_projects, SET NULL) | — | Projet |
| `title` | TEXT NOT NULL | — | Titre |
| `description` | TEXT | defaut `''` | Description |
| `status` | TEXT | CHECK `backlog`, `todo`, `in-progress`, `in-review`, `done` | Statut |
| `priority` | INTEGER | CHECK 1-4 (defaut 3) | 1=Critical, 4=Low |
| `assignee` | TEXT | — | Assignataire |
| `team_id` | TEXT NOT NULL | — | Equipe |
| `tags` | TEXT[] | defaut `'{}'` | Tags |
| `phase` | TEXT | — | Phase workflow |
| `created_by` | TEXT | — | Createur |
| `created_at` | TIMESTAMPTZ | NOW() | |
| `updated_at` | TIMESTAMPTZ | NOW() | |

Index : `project_id`, `status`, `team_id`, `assignee`

### 16.8 Table `pm_issue_counters`

| Colonne | Type | Description |
|---|---|---|
| `team_id` | TEXT PRIMARY KEY | Equipe |
| `next_seq` | INTEGER | Prochain numero de sequence (defaut 1) |

### 16.9 Table `pm_issue_relations`

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| `id` | SERIAL PRIMARY KEY | — | Identifiant |
| `type` | TEXT | CHECK `blocks`, `relates-to`, `parent`, `duplicates` | Type |
| `source_issue_id` | TEXT (FK pm_issues, CASCADE) | — | Issue source |
| `target_issue_id` | TEXT (FK pm_issues, CASCADE) | — | Issue cible |
| `reason` | TEXT | defaut `''` | Raison |
| `created_by` | TEXT | — | Createur |
| `created_at` | TIMESTAMPTZ | NOW() | |
| UNIQUE | `(type, source_issue_id, target_issue_id)` | | |

Index : `source_issue_id`, `target_issue_id`

### 16.10 Table `pm_pull_requests`

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| `id` | TEXT PRIMARY KEY | — | Identifiant de la PR |
| `title` | TEXT NOT NULL | — | Titre |
| `author` | TEXT NOT NULL | — | Auteur |
| `issue_id` | TEXT (FK pm_issues, SET NULL) | — | Issue liee |
| `status` | TEXT | CHECK `pending`, `approved`, `changes_requested`, `draft` | Statut |
| `additions` | INTEGER | defaut 0 | Lignes ajoutees |
| `deletions` | INTEGER | defaut 0 | Lignes supprimees |
| `files` | INTEGER | defaut 0 | Nombre de fichiers |
| `created_at` | TIMESTAMPTZ | NOW() | |
| `updated_at` | TIMESTAMPTZ | NOW() | |

### 16.11 Table `pm_inbox`

| Colonne | Type | Contrainte | Description |
|---|---|---|---|
| `id` | SERIAL PRIMARY KEY | — | Identifiant |
| `user_email` | TEXT NOT NULL | — | Destinataire |
| `type` | TEXT | CHECK : voir ci-dessous | Type de notification |
| `text` | TEXT NOT NULL | — | Contenu |
| `issue_id` | TEXT | — | Issue liee |
| `related_issue_id` | TEXT | — | Issue liee secondaire |
| `relation_type` | TEXT | — | Type de relation |
| `avatar` | TEXT | — | Initiales de l'auteur |
| `read` | BOOLEAN | defaut FALSE | Lu/non lu |
| `created_at` | TIMESTAMPTZ | NOW() | |

Types : `mention`, `assign`, `comment`, `status`, `review`, `blocked`, `unblocked`, `dependency_added`

Index : `(user_email, read, created_at DESC)`

### 16.12 Table `pm_activity`

| Colonne | Type | Description |
|---|---|---|
| `id` | SERIAL PRIMARY KEY | Identifiant |
| `project_id` | INTEGER (FK pm_projects, CASCADE) | Projet |
| `user_name` | TEXT NOT NULL | Auteur de l'action |
| `action` | TEXT NOT NULL | Type d'action |
| `issue_id` | TEXT | Issue liee |
| `detail` | TEXT | Detail textuel |
| `created_at` | TIMESTAMPTZ | NOW() |

Index : `(project_id, created_at DESC)`

### 16.13 Triggers PG NOTIFY

#### `notify_hitl_chat`

Declencheur : `AFTER INSERT ON hitl_chat_messages`
Canal : `hitl_chat`
Payload : `{ id, team_id, agent_id, thread_id, sender, content (4000 chars max), created_at }`

#### `notify_hitl_request`

Declencheur : `AFTER INSERT ON hitl_requests`
Canal : `hitl_request`
Payload : `{ id, team_id, agent_id, thread_id, request_type, prompt (500 chars max), status, created_at }`

---

## 17. Configuration

### 17.1 Fichier `config/hitl.json`

```json
{
  "auth": {
    "jwt_expire_hours": 24,
    "allow_registration": true,
    "default_role": "undefined"
  },
  "google_oauth": {
    "enabled": true,
    "client_id": "123456789-xxxxxxxx.apps.googleusercontent.com",
    "client_secret_env": "GOOGLE_CLIENT_SECRET",
    "allowed_domains": ["company.com"]
  }
}
```

| Cle | Type | Defaut | Description |
|---|---|---|---|
| `auth.jwt_expire_hours` | int | 24 | Duree de validite du JWT en heures |
| `auth.allow_registration` | bool | true | Autoriser l'inscription |
| `auth.default_role` | string | `"undefined"` | Role initial des nouveaux comptes |
| `google_oauth.enabled` | bool | false | Activer Google OAuth |
| `google_oauth.client_id` | string | `""` | Client ID Google (public, non sensible) |
| `google_oauth.client_secret_env` | string | `""` | Nom de la variable d'env pour le secret |
| `google_oauth.allowed_domains` | string[] | `[]` | Domaines email autorises (vide = tous) |

### 17.2 Fichier `config/others.json`

Utilise pour :
- `hosts.api` : URL du gateway LangGraph API (ex: `http://langgraph-api:8000`)
- `password_reset.smtp_name` : nom du serveur SMTP pour les emails de reset
- `password_reset.template_name` : nom du template email

### 17.3 Fichier `config/mail.json`

Configuration SMTP pour l'envoi d'emails :

```json
{
  "smtp": [{
    "name": "default",
    "host": "smtp.gmail.com",
    "port": 587,
    "user": "noreply@company.com",
    "password_env": "SMTP_PASSWORD",
    "use_ssl": false,
    "use_tls": true,
    "from_address": "noreply@company.com",
    "from_name": "ag.flow"
  }],
  "templates": [{
    "name": "reset",
    "subject": "[ag.flow] Reinitialisation mot de passe",
    "body": "Votre mot de passe temporaire : ${pwd}\nLien: ${UrlService}/reset-password?mail=${mail}&pwd=${pwd}"
  }]
}
```

Variables de substitution dans les templates : `${mail}`, `${pwd}`, `${UrlService}`

### 17.4 Variables d'environnement

| Variable | Defaut | Description |
|---|---|---|
| `DATABASE_URI` | `""` | URI PostgreSQL |
| `HITL_JWT_SECRET` | `MCP_SECRET` ou `"change-me-hitl-secret"` | Secret JWT |
| `HITL_ADMIN_EMAIL` | `"admin@langgraph.local"` | Email du compte admin initial |
| `HITL_ADMIN_PASSWORD` | `"admin"` | Mot de passe du compte admin initial |
| `HITL_PUBLIC_URL` | `"http://localhost:8090"` | URL publique (pour les liens de reset) |
| `GOOGLE_CLIENT_SECRET` | — | Secret Google OAuth (si active) |
| `LANGGRAPH_API_URL` | `"http://langgraph-api:8000"` | URL du gateway (fallback si pas dans others.json) |
| `AG_FLOW_ROOT` | `"/root/ag.flow"` | Racine des fichiers projet (livrables) |
| `CULTURE` | `"fr-fr"` | Culture par defaut pour les prompts localises |
| `SMTP_PASSWORD` | — | Mot de passe SMTP (nom de var configurable) |
| `ANTHROPIC_API_KEY` | — | Cle API Anthropic (pour AI Planning) |
| `OPENAI_API_KEY` | — | Cle API OpenAI (fallback pour AI Planning) |

---

## 18. Securite

### 18.1 Validation JWT

Chaque endpoint protege extrait le token du header `Authorization: Bearer {token}` via la dependance `get_current_user()`. Les verifications :

1. Presence du header `Authorization`
2. Decodage du JWT avec le secret HS256
3. Validation de l'expiration
4. Extraction de `user_id`, `email`, `role`, `teams`

### 18.2 Controle d'acces par role

| Endpoint | Acces membre | Acces admin | Detail |
|---|---|---|---|
| Questions d'une equipe | Si `team_id in user.teams` | Toujours | Filtre par equipe |
| Agents d'une equipe | Si `team_id in user.teams` | Toujours | |
| Membres d'une equipe | Si `team_id in user.teams` | Toujours | |
| Supprimer un membre | Non | Oui | `admin` requis |
| Reset de thread | Non | Oui | `admin` requis |
| Chat avec agent | Si `team_id in user.teams` | Toujours | |
| Inviter un membre | Si `team_id in user.teams` | Toujours | |

### 18.3 Verification du token Google

Le token Google est verifie **cote serveur** via l'endpoint public Google :

```
GET https://oauth2.googleapis.com/tokeninfo?id_token={credential}
```

Verifications :
1. Code HTTP 200
2. `aud` (audience) == `client_id` configure
3. `email_verified` == `"true"`
4. Domaine de l'email dans `allowed_domains` (si configure)

### 18.4 Protection bcrypt

- Algorithme : bcrypt via `passlib.context.CryptContext`
- Troncature a 72 octets (limite bcrypt)
- Verification immediate apres hachage lors du reset

### 18.5 Protection WebSocket

- Token JWT passe en query parameter (pas de header HTTP possible sur WebSocket)
- Verification avant `accept()` — mais la spec WebSocket impose d'accepter avant de fermer
- Codes de fermeture personnalises : 4001 (Unauthorized), 4003 (Forbidden)

### 18.6 Sanitisation des entrees

- Les slugs et identifiants de fichiers sont nettoyes via regex : `re.sub(r'[^a-z0-9_-]', '', value.lower())`
- Limite de taille pour les uploads : 50MB (documents), 200MB (archives)
- Le contenu des messages PG NOTIFY est tronque (`LEFT(content, 4000)`, `LEFT(prompt, 500)`)

### 18.7 Protection CSRF

Pas de protection CSRF explicite — le SPA utilise des tokens JWT dans les headers `Authorization`, ce qui est inherement protege contre les attaques CSRF classiques.

---

## 19. Design System

### 19.1 Theme

Mode sombre inspire de Linear avec typographie monospace (JetBrains Mono).

### 19.2 Palette de couleurs

| Token | Valeur | Usage |
|---|---|---|
| `--bg-primary` | `#0a0a0c` | Fond principal |
| `--bg-secondary` | `#111114` | Sidebar, cartes |
| `--bg-tertiary` | `#1a1a1f` | Inputs, zones sureleves |
| `--bg-hover` | `#1e1e24` | Survol |
| `--bg-active` | `#24242c` | Selection active |
| `--text-primary` | `#e8e8ec` | Texte principal |
| `--text-secondary` | `#9898a4` | Texte secondaire |
| `--text-tertiary` | `#6b6b78` | Labels, hints |
| `--text-quaternary` | `#45454f` | Texte tres discret |
| `--accent-blue` | `#5b8def` | Actions principales, liens |
| `--accent-green` | `#3ecf8e` | Succes, done, online |
| `--accent-orange` | `#f0a050` | Avertissement, todo |
| `--accent-yellow` | `#e8c44a` | In-progress |
| `--accent-red` | `#ef5555` | Erreur, blocked |
| `--accent-purple` | `#a78bfa` | Tags, relations |

### 19.3 Composants visuels

| Composant | Classe | Description |
|---|---|---|
| Sidebar item | `.sidebar-item` | Bouton de navigation (padding 7px 10px, border-radius 6px) |
| Metric card | `.metric-card` | Carte metriques avec fond secondary |
| Issue row | `.issue-row` | Ligne d'issue avec hover |
| PR row | `.pr-row` | Ligne de pull request |
| Notification row | `.notification-row` | Ligne de notification |
| Avatar | `.avatar` | Cercle avec initiales colores |
| Status dot | `.status-dot` | Pastille 6px online/offline |
| Priority badge | `.priority-badge` | 4 barres de hauteur croissante |
| Tag | `.tag` | Label colore avec fond transparent |
| Progress bar | `.progress-bar` | Barre de progression horizontale |
| Toast | `.toast` | Notification ephemere (3.5s) |
| Modal | `.modal-overlay` + `.modal` | Overlay centre avec fond assombri |
| Detail panel | `.detail-panel` | Panel coulissant a droite |

---

## 20. Demarrage et cycle de vie

### 20.1 Sequence de demarrage (serveur)

1. Chargement des variables d'environnement (`.env`)
2. Lecture de `hitl.json` pour la config auth/Google
3. Calcul du secret JWT (padding SHA-256 si < 32 octets)
4. **Lifespan** :
   - Tentative de connexion a PostgreSQL (10 essais, 3s entre chaque)
   - `_seed_admin()` : creation des tables PM, migration de schema, seed admin
   - Demarrage du thread PG LISTEN (hitl_chat + hitl_request)
5. Montage des fichiers statiques sur `/static`

### 20.2 Sequence de demarrage (client)

1. Chargement du HTML + CSS + JS
2. Verification du token en localStorage via `GET /api/auth/me`
3. Si valide : `onLoggedIn()` → chargement teams → sidebar → WebSocket → vue Inbox
4. Si invalide : affichage de l'ecran de login
5. Initialisation du bouton Google Sign-In (si client_id disponible)
6. Chargement de la version via `GET /api/version`

### 20.3 Auto-refresh

Certaines vues utilisent un refresh automatique via `setInterval` :

| Vue | Intervalle | Condition |
|---|---|---|
| Workflow tab | 8s si agents en cours, 60s sinon | Adaptatif |
| Activity tab | 12s (puis adaptatif) | |
| Dependencies tab | 12s | |

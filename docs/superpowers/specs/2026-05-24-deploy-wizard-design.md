# Deploy Wizard Redesign — Spec

## Contexte

Le wizard de déploiement actuel est linéaire : sélection machine → génération env → déploiement SSH. La nouvelle version introduit une machine à états côté backend, des étapes de scripts `before_deploy` exécutées séquentiellement avec streaming SSE des logs, et un dictionnaire de variables cumulatif entre les étapes.

**Contrainte fondamentale** : design API-first. Le wizard frontend n'est qu'un client parmi d'autres. Un appel API direct doit pouvoir déclencher le même workflow.

---

## Périmètre

Trois sous-projets enchaînés :

- **A** — Machine à états + schéma DB
- **B** — Backend : executor SSH + SSE streaming
- **C** — Frontend : wizard 3-onglets

---

## Section 1 — Machine à états et modèle de données

### États

```
draft → generated → executing_step → step_complete → before_complete → deploying → deployed
                                   ↘ step_failed ↗ (retry)
                                                               ↘ failed
```

| État | Signification |
|---|---|
| `draft` | Déploiement créé, pas encore généré |
| `generated` | `POST /generate` appelé, env calculé |
| `executing_step` | Un script before est en cours d'exécution |
| `step_complete` | Étape terminée avec succès, étape suivante disponible |
| `before_complete` | Tous les scripts before terminés, prêt au déploiement final |
| `step_failed` | Étape échouée, retry possible |
| `deploying` | `POST /deploy` appelé, SSH deploy en cours |
| `deployed` | Déploiement terminé avec succès |
| `failed` | Déploiement final échoué |

### Delta schéma DB

```sql
ALTER TABLE deployments
  ADD COLUMN current_step_index  INTEGER DEFAULT 0,
  ADD COLUMN accumulated_env     JSONB   DEFAULT '{}',
  ADD COLUMN step_logs           JSONB   DEFAULT '[]';
```

`step_logs` = tableau d'objets `{step_index, lines: string[], exit_code, started_at, ended_at}`.

`accumulated_env` : dictionnaire qui s'enrichit à chaque étape avec les variables de sortie parsées depuis la dernière ligne JSON du stdout du script.

### Endpoints API

| Méthode | Endpoint | Rôle | État avant | État après |
|---|---|---|---|---|
| `POST` | `/{id}/generate` | Calcule l'env dict depuis group vars | `draft` | `generated` |
| `POST` | `/{id}/execute-step` | Lance l'étape courante, SSE stream | `generated` \| `step_complete` | `executing_step` |
| `POST` | `/{id}/retry-step` | Relance l'étape échouée | `step_failed` | `executing_step` |
| `GET` | `/{id}/stream` | SSE log stream | any | — |
| `POST` | `/{id}/deploy` | SSH deploy final | `before_complete` | `deploying` → `deployed` \| `failed` |

`execute-step` retourne 409 si l'état n'est pas `generated` ou `step_complete` (idempotence, pas de double exécution concurrente).

---

## Section 2 — Frontend Wizard

### Structure des onglets

```
[ Configuration ] [ Exécution ] [ Logs ]
```

### Onglet Configuration

Deux blocs :

1. **Sélection de machine** (existant, inchangé)
2. **Variables du groupe** (nouveau) — table des variables du groupe avec valeur courante pré-remplie, éditable avant génération

Bouton **"Suivant"** (remplace "Generate") en bas de l'onglet.  
Au clic : `POST /{id}/generate` avec les vars du groupe en payload → bascule sur l'onglet Exécution.

### Onglet Exécution

Liste des étapes `before_deploy` ordonnées par `position` :

```
✓ Étape 1/3 — init-realm         Terminé
▶ Étape 2/3 — create-client      En attente
○ Étape 3/3 — configure-roles    À venir
────────────────────────────────────────────
  Script : create-client
  Machine : deploy-host (172.16.0.10)

  Variables requises :
  ✓ REALM_NAME = "agflow"
  ✓ KC_ADMIN_PASSWORD = ●●●●●
  ✗ CLIENT_SECRET → manquant

  [ Réessayer ]   [ Suivant ▶ ]
```

Règles :
- **"Suivant"** activé uniquement si toutes les vars requises de l'étape courante sont résolues.
- Au clic "Suivant" : ouvre SSE (`GET /{id}/stream`) **avant** d'appeler `POST /{id}/execute-step`, puis bascule sur l'onglet Logs.
- Succès (event `step_complete`) : retour onglet Exécution, étape cochée, bouton "Suivant" pour l'étape suivante.
- Dernier step terminé (event `before_complete`) : bouton **"Déployer"** visible.
- Échec (event `step_failed`) : badge rouge sur l'étape, bouton "Réessayer" → `POST /{id}/retry-step`.

### Onglet Logs

- Zone scrollable monospace fond sombre, auto-scroll désactivable manuellement.
- Selector en haut : "Étape 1 | Étape 2 | …" pour consulter l'historique des steps précédents (depuis `step_logs` en DB).
- Badge "En direct" pulsé quand SSE ouvert, "Archivé" quand step terminé.
- Le client SSE passe `?last_event_id=<offset>` pour rejouer depuis un offset en cas de reconnexion.

### Gestion du `accumulated_env`

Le frontend envoie les variables du groupe dans le payload de `POST /generate`. Le backend calcule l'env complet, stocke dans `accumulated_env`. Après chaque step, le backend extrait les output vars de la dernière ligne JSON stdout et les fusionne dans `accumulated_env`. Le frontend ne gère pas ce dictionnaire — il lit l'état depuis le backend.

---

## Section 3 — Backend : Executor SSH + SSE

### Module `deployment_executor.py`

Fichier : `backend/src/agflow/services/deployment_executor.py`

Responsabilité unique : exécuter un script sur une machine SSH et publier les logs.

```
execute_step(deployment_id, step_index, accumulated_env)
  1. Charge le script (group_script) et la machine (target_kind: deployment_host | fixed_machine)
  2. Résout l'env final : accumulated_env + secrets déchiffrés requis par le script
  3. Ouvre connexion SSH (asyncssh)
  4. Stream stdout/stderr ligne par ligne → publie dans Redis Stream "deploy:{id}:logs"
  5. À la fin : parse la dernière ligne stdout comme JSON → extrait les output vars
  6. Fusionne les output vars dans accumulated_env en DB
  7. Met à jour current_step_index et state (step_complete | step_failed | before_complete)
```

Les logs transitent par Redis Stream. Plusieurs consommateurs peuvent s'y abonner indépendamment (SSE, future API webhook, CLI).

### SSE Endpoint

```python
GET /api/admin/deployments/{id}/stream
```

- `EventSourceResponse` (starlette-sse)
- Consomme le Redis Stream `deploy:{id}:logs` depuis `last_event_id` ou depuis le début
- Format des events :

```
event: log
data: {"line": "...", "ts": 1716...}

event: step_complete
data: {"step_index": 1, "output_vars": {"CLIENT_ID": "abc"}}

event: step_failed
data: {"step_index": 1, "exit_code": 1}

event: stream_end
data: {}
```

- Ferme la connexion SSE sur event `stream_end`.

### Pas de Celery

L'executor tourne dans une tâche `asyncio` lancée par `execute-step`. Pas de worker séparé. Le Redis Stream sert de tampon fiable pour le replay SSE.

### Transitions d'état (résumé)

| Appelant | Transition |
|---|---|
| `POST /generate` | `draft` → `generated` |
| `POST /execute-step` | `generated` \| `step_complete` → `executing_step` |
| executor (succès, steps restants) | `executing_step` → `step_complete` |
| executor (succès, dernier step) | `executing_step` → `before_complete` |
| executor (échec) | `executing_step` → `step_failed` |
| `POST /retry-step` | `step_failed` → `executing_step` |
| `POST /deploy` | `before_complete` → `deploying` → `deployed` \| `failed` |

---

## Contraintes transversales

- Tout l'état est en DB — le wizard peut être rechargé/rafraîchi sans perte.
- Un déploiement en état `executing_step` refuse un second `execute-step` (409).
- `target_kind = deployment_host` → machine choisie dans l'onglet Configuration ; `fixed_machine` → machine configurée sur le script.
- Secrets résolus via Harpocrate à l'exécution, jamais stockés en clair dans `accumulated_env`.

# agflow.docker — Prompt de développement : Panneau d'administration & API

## Contexte

agflow.docker est une plateforme d'instanciation d'agents IA construite sur React/Next.js + FastAPI. Ce document décrit les 7 modules du panneau d'administration qui permettent de configurer les briques, les composer en agents complets déployables, les exposer via API, et superviser leur cycle de vie.

---

## Module 0 — Gestion des Secrets

Gestion centralisée des secrets et variables d'environnement de l'application. Les secrets alimentent la construction du fichier `.env` injecté dans les containers au lancement.

### Types de secrets

- **API Keys LLM** : ANTHROPIC_API_KEY, OPENAI_API_KEY, MISTRAL_API_KEY, GOOGLE_API_KEY, etc.
- **Clés de registres** : clés d'accès aux services de découverte (ex: YOOPS_API_KEY pour mcp-yoops.org)
- **Tokens d'intégration** : GITHUB_TOKEN, tokens MCP spécifiques
- **Secrets applicatifs** : clés internes, tokens de session, etc.

### Stockage

Les valeurs ne sont jamais affichées en clair après saisie (masquées par défaut, révélables temporairement). Stockage chiffré en base.

### Référencement par alias

Chaque secret est référencé par un nom de variable d'env (ex: `ANTHROPIC_API_KEY`). Les Dockerfiles et les Agents utilisent ces alias — jamais les valeurs en dur. Le `.env` est construit dynamiquement au moment du lancement du container en résolvant les alias vers les valeurs.

### Construction du .env

Au lancement d'un agent (Module 4 / Module 5), le système assemble le `.env` en collectant :
- Les secrets requis par le Dockerfile (paramètres déclarés dans Module 1)
- Les clés requises par les MCP sélectionnés (Module 3)
- Les overrides spécifiques à l'agent (Module 4)

Si un secret requis est manquant → erreur explicite avant lancement, pas de container démarré avec des variables vides.

### Scoping

- **Global** : secrets partagés par tous les agents (ex: ANTHROPIC_API_KEY commune)
- **Par agent** : override au niveau d'un agent spécifique (ex: une clé OpenAI dédiée à un agent particulier)

### UI

Tableau avec colonnes : Nom de variable, Valeur (masquée), Scope (global/agent), Utilisé par (liste des agents/Dockerfiles qui le référencent), Actions (éditer, supprimer, révéler temporairement). Bouton Tester pour vérifier la validité d'une clé (appel API de test si applicable).

### Convention d'indicateurs visuels

Partout dans l'application où un module référence un secret par nom de variable d'env, un indicateur visuel affiche son statut :
- 🔴 Rouge : variable manquante (non déclarée dans les secrets)
- 🟠 Orange : variable présente mais valeur vide
- 🟢 Vert : variable présente et remplie

Cette convention s'applique dans les Services de découverte (Module 3a), les paramètres Dockerfile (Module 1), la composition d'agent (Module 4), et partout où un secret est référencé.

---

## Module 1 — Dockerfiles (Infrastructure runtime)

Interface CRUD pour gérer les images Docker des agents CLI (aider, claude-code, codex, gemini, goose, mistral, open-code). Chaque agent dispose d'un **répertoire** contenant tous les fichiers nécessaires à la construction de son image.

### Répertoire de l'agent

On peut ajouter n'importe quel fichier dans le répertoire pour gérer la construction de l'image (Dockerfile, scripts .sh, fichiers de config, requirements.txt, etc.). L'éditeur affiche tous les fichiers du répertoire avec coloration syntaxique. Fichiers standard :

- **Dockerfile** : image de base, dépendances, installation de l'agent CLI, copie de l'entrypoint
- **Entrypoint (.sh)** : script bash standardisé (protocole de communication)
- **run.cmd.md** : commande de lancement documentée
- **Autres fichiers** : tout fichier nécessaire au build (configs, scripts auxiliaires, etc.)

Sidebar avec liste des agents et leurs fichiers associés.

### Actions

- **Sauvegarder** : persiste les fichiers en base
- **Compiler** : lance `docker build`, stream des logs en temps réel dans une modale, badge statut "Image compilée" / "Erreur"
- **Supprimer** : supprime le répertoire et ses fichiers associés

### Tagging déterministe des images

Le tag de l'image est toujours un hash calculé à partir du contenu du Dockerfile + tous les fichiers `.sh` du répertoire, pris par ordre alphabétique. Format : `agflow-{agent}:{hash}`. Cela garantit :
- **Reproductibilité** : même contenu = même tag, pas de rebuild inutile
- **Détection de changement** : si le hash n'a pas changé depuis le dernier build, l'image est déjà à jour
- **Traçabilité** : on sait exactement quel contenu a produit quelle image

### Protocole entrypoint standardisé

Chaque entrypoint suit le même contrat :

- **Entrée** : réception d'un JSON sur stdin contenant `task_id`, `instruction`, `timeout_seconds`, `model`
- **Sortie** : émission d'events JSON sur stdout via une fonction `emit_event(type, data)` :
  - `progress` : lignes de sortie intermédiaires de l'agent
  - `result` : résultat final avec `status` (success/failure) et `exit_code`

### Paramètres du Dockerfile

Les valeurs par défaut et variables d'environnement sont intégrées au fichier de paramétrage du Dockerfile :
- API_KEY_NAME, ANTHROPIC_API_KEY, OPENAI_API_KEY, WORKSPACE_PATH
- Syntaxe de templating `{VAR}` et fallback `${VAR:-default}`
- Ces paramètres sont surchargeables au niveau de l'Agent (Module 4) lors de la composition

### Fichier run.cmd.md

Fichier markdown dédié décrivant la commande de lancement en mode `docker run` direct. Séparé du Dockerfile pour clarifier les responsabilités : le Dockerfile construit l'image, le run.cmd.md décrit comment la lancer. Contient les flags Docker (network mode, stdin_open, tty, env vars, working_dir) sous forme documentée et exécutable.

### Volumes normalisés

Le Dockerfile déclare des mount points standardisés — des "slots" que l'Agent (Module 4) viendra remplir lors de la composition. Convention de mount points :

- `/app` → workspace de travail (code source, fichiers du projet)
- `/app/skills` → fichiers SKILL.md injectés depuis le Catalogue Skills
- `/app/config` → configuration de l'agent (rôle compilé, MCP config)
- `/app/output` → résultats produits par l'agent

Le Dockerfile normalise les chemins (il déclare les volumes). L'Agent (Module 4) détermine quels fichiers concrets monter dans ces volumes. C'est une séparation contrat (Dockerfile) / implémentation (Agent).

---

## Module 2 — Rôles (Personnalités agents)

Interface de gestion des profils/personnalités d'agents. Ce module gère les "rôles" — des entités de personnalité composables.

### Structure d'un rôle

**Informations (tab General)** :
- ID (slug unique, ex: `requirements_analyst`)
- Nom d'affichage (ex: `Analyst`)
- Description : texte en prose décrivant le rôle
- Paramètres LLM : Type (Single/Multi), Temperature, Max Tokens
- Type de services : checkboxes parmi Documentation, Code, Maquette/Design, Automatisme, Liste de taches, Specifications, Contrat
- Tab Runtime : configuration d'exécution spécifique

**Identité** :
- Texte en prose rédigé à la 2e personne du singulier ("Tu es un assistant qui agit en tant que cerveau synthétique...")
- C'est le noyau stable de personnalité de l'agent — posture, état d'esprit, philosophie, approche

**Prompt** :
- Deux variantes générées automatiquement à partir de l'assemblage identité + rôles + missions + compétences :
  - **Prompt agent (2e personne)** : "Tu es...", "Tu analyses...", "Tu transformes..." — injecté dans le container comme prompt système de l'agent. C'est le prompt que l'agent reçoit pour se comporter selon sa personnalité.
  - **Prompt orchestrateur (3e personne)** : "Il est...", "Il analyse...", "Il transforme..." — généré automatiquement par reformulation. Utilisé par l'orchestrateur pour décrire les capacités de chaque agent et décider qui assigner à quelle tâche. Ce prompt alimente aussi la description dans l'API de découverte des agents (Module 5b).
- La génération de la variante 3e personne est automatique (transformation LLM ou règle de réécriture) à chaque sauvegarde du rôle. Elle peut être éditée manuellement si la reformulation automatique n'est pas satisfaisante.

**Chat** :
- Interface conversationnelle intégrée pour co-construire le profil avec un LLM
- Message : "Discutez avec le LLM pour construire le profil de l'agent"
- Permet d'itérer sur la personnalité de façon interactive

### Sidebar arborescente

Trois sous-sections dynamiques, chacune contenant des fichiers markdown :

- **ROLES** : facettes comportementales composables (ex: `analyse_et_extraction`, `generation_strictement_normee`). Chaque rôle est un texte en prose 2e personne décrivant un comportement spécifique.
- **MISSIONS** : directives opérationnelles (ex: `transformation_sans_formatage`, `validation_stricte_des_limites`)
- **COMPETENCES** : capacités techniques (ex: `conformité_structurelle_absolue`, `déduction_logique_sans_compromis`, `traitement_sémantique_pur`)

### Convention de fichiers

- Icône 📄 = fichier `.md` éditable
- Icône 🔒 = fichier `.md` protégé en écriture (flag `protected` en base de données, même extension `.md`)
- Chaque sous-section a un bouton "+ Ajouter"
- On peut ajouter des répertoires/groupes pour organiser les documents différemment
- Sélection d'un item = highlight + croix de fermeture, contenu affiché dans le panneau principal

### Actions globales

- Dropdown de sélection de rôle en haut de la sidebar
- Boutons "+ Ajouter" et "Importer" pour créer ou importer des rôles
- Bouton "Sauvegarder" sur chaque vue de contenu
- Bouton "Supprimer agent" en bas de la sidebar

---

## Module 3 — Services de découverte et Catalogues (MCP + Skills)

Le système repose sur un registre externe polyvalent (ex: `mcp-yoops.org`) qui sert deux catalogues distincts via la même API et le même mécanisme d'authentification.

### 3a — Services de découverte MCP

Configuration des registres MCP externes. C'est la couche d'administration en amont des catalogues.

Chaque registre a :
- **Nom** (ex: `mcp-yoops.org`)
- **URL API** (ex: `https://mcp.yoops.org/api/v1`)
- **Clé API (.env)** : nom de la variable d'environnement à utiliser (ex: `YOOPS_API_KEY`). Le paramétrage stocke le nom de la variable, pas la valeur — la valeur est gérée dans le Module 0 (Secrets). Indicateur visuel de statut :
  - 🔴 Rouge : variable manquante (non déclarée dans les secrets)
  - 🟠 Orange : variable présente mais valeur vide
  - 🟢 Vert : variable présente et remplie
- **Status** : testable en temps réel

Actions : Tester (vérifier connectivité avec la clé), Editer, Supprimer. Bouton "+ Ajouter" pour brancher de nouveaux registres. Le système est multi-registres — on peut connecter plusieurs sources de découverte simultanément (ex: mcp-yoops.org, Smithery, Glama, PulseMCP).

Description du rôle : "Services externes qui décrivent les serveurs MCP disponibles et fournissent des recettes d'installation par cible (Claude Code, Codex, Gemini...)".

Section "Recherche MCP" en bas : champ texte avec placeholder "Ex: git, fetch, database..." + bouton Rechercher.

### 3b — Catalogue MCP

Vue des serveurs MCP installés dans l'application, alimentée par les registres de découverte.

- Serveurs groupés par repository source avec compteur de packages (ex: `modelcontextprotocol/servers` = 9 packages, `microsoft/playwright-mcp` = 1 package)
- Chaque serveur : nom court (bold), identifiant package (ex: `@modelcontextprotocol/server-filesystem`), actions configurer/supprimer
- Noms de repos = liens cliquables vers la source GitHub
- Dropdown de sélection du registre source en haut

**Paramètres MCP** :
- Si un serveur MCP nécessite des paramètres de configuration (chemins, credentials, options), ils sont renseignés ici au niveau global — c'est la configuration par défaut pour toute l'application
- Chaque paramètre référence un nom de variable d'env si c'est un secret (indicateurs 🔴🟠🟢, cf. Module 0)
- Ces paramètres globaux peuvent être **surchargés au niveau de l'agent** (Module 4) pour personnaliser le comportement d'un MCP selon l'agent qui l'utilise (ex: construction de fichier dans le répertoire de travail différent par agent)

**Modale de recherche MCP** :
- Champ de recherche texte
- Checkbox "Sémantique" pour activer la recherche vectorielle sur la base de 13K+ packages
- Résultats affichent : nom du repo, badge de type de transport (**sse** / **stdio** / **docker**), description courte, description longue dépliable, liens "Repo" et "Documentation", bouton "Ajouter" pour installer dans le catalogue local

### 3d — Instanciation globale des MCP

Les serveurs MCP sont instanciés **une seule fois au niveau de la plateforme**, pas dans chaque container agent. Les agents y accèdent comme des services partagés.

- Au démarrage de la plateforme (ou à l'ajout d'un MCP au catalogue) : le serveur MCP est lancé en tant que service global (container Docker dédié ou process selon le transport stdio/sse)
- Les agents se connectent aux MCP via le réseau interne (URL de service pour SSE, socket partagé pour stdio)
- La configuration de connexion est injectée dans le prompt/config de l'agent au moment du lancement
- Gestion du lifecycle des MCP globaux : démarrage, health check, redémarrage en cas de crash, arrêt propre
- Un MCP global peut être partagé par N agents simultanément

### 3c — Catalogue Skills

Même pattern UI que le Catalogue MCP (dropdown registre + bouton "Ajouter"), mais pour les Skills — packs de bonnes pratiques et instructions spécialisées (fichiers SKILL.md) attachables à un agent. Le registre yoops.org alimente les deux catalogues via la même API.

---

## Module 4 — Composition d'Agent (Builder visuel)

Écran central de la plateforme. Un agent est une entité nommée qui est composé avec les briques des autres modules en une unité déployable et testable.

### Structure d'un agent composé

- **ID propre** (slug unique) + **Nom d'affichage**
- **1 Dockerfile** (sélectionné depuis le Module 1) — le runtime d'exécution. L'image doit être compilée (buildée) avant de pouvoir être utilisée dans un agent. Si l'image n'est pas buildée ou si le hash a changé depuis le dernier build, un indicateur visuel le signale (🔴 pas buildée, 🟠 build obsolète, 🟢 image à jour). Le builder empêche le lancement d'un agent dont l'image n'est pas à jour.
- **1 Rôle** (sélectionné depuis le Module 2) — la personnalité complète (identité + rôles + missions + compétences)
- **N Services MCP** (sélectionnés depuis le Catalogue MCP, Module 3b) — les outils externes disponibles pour l'agent. Pour chaque MCP sélectionné, les paramètres globaux (définis dans Module 3b) sont hérités par défaut mais peuvent être **surchargés** au niveau de l'agent (ex: construction de fichier dans le répertoire de travail différent par agent, ou un serveur de base de données pointant vers une instance différente).
- **N Skills** (sélectionnées depuis le Catalogue Skills, Module 3c) — les packs de bonnes pratiques et savoir-faire

### Paramètres de lifecycle

- **Lancement** : variables d'environnement, timeout, model par défaut, workspace path, network mode
- **Destruction** : graceful shutdown timeout, force kill delay, cleanup des volumes

### Construction du répertoire de configuration

Avant le lancement d'un agent, le système assemble un **répertoire de configuration complet** qui contient tout ce qu'il faut pour que le container démarre et fonctionne. C'est une étape de build explicite, pas un assemblage à la volée.

**Processus de construction** :
1. Résolution de la composition : Dockerfile, Rôle, MCP, Skills, paramètres
2. Compilation du prompt système (2e personne) à partir de identité + rôles + missions + compétences
3. Collecte des fichiers Skills (SKILL.md) depuis le catalogue
4. Génération de la configuration MCP (serveurs, paramètres globaux + surcharges agent, endpoints de connexion)
5. Résolution des secrets (Module 0) → construction du fichier `.env`
6. Injection de la personnalisation mission si applicable
7. Écriture du répertoire final sur disque

**Structure du répertoire construit** :
- `/config/prompt.md` → prompt système compilé (identité + rôles + missions + compétences)
- `/config/mcp.json` → configuration des serveurs MCP accessibles (endpoints, paramètres résolus)
- `/config/tools.json` → catalogue des tools disponibles (MCP + tools consommateur)
- `/config/mission.md` → instructions de personnalisation mission (si applicable)
- `/config/.env` → variables d'environnement résolues (secrets, API keys, paramètres)
- `/skills/` → fichiers SKILL.md collectés
- `/workspace/` → répertoire projet monté

Ce répertoire est ensuite monté dans le container via les volumes normalisés du Dockerfile (Module 1). Le builder affiche visuellement le contenu du répertoire de configuration pour chaque agent.

Le répertoire de configuration est construit à la volée au moment du lancement de l'agent, à partir de la composition stockée en base. Il est éphémère — détruit avec le container. Il peut être reconstruit à tout moment à partir de la composition de l'agent. La base de données PostgreSQL sert à la gestion de la consommation des agents (traçabilité, sessions, états, métriques), pas au stockage des répertoires de configuration.

### Builder visuel

Interface riche type assembleur — pas un simple formulaire à dropdowns. Chaque brique (Docker, Rôle, MCP, Skill) est représentée visuellement. Le builder montre la composition complète de l'agent de façon lisible et manipulable d'un coup d'œil. Manipulation interactive (drag-and-drop ou sélection) pour ajouter/retirer des briques.

**Prérequis** : ce module nécessite une phase de maquettage UX/UI avant le développement. Les maquettes doivent couvrir : le layout du builder, la représentation visuelle de chaque type de brique, les interactions d'ajout/retrait/configuration, l'affichage du répertoire de configuration construit, et les états visuels (image non buildée, secrets manquants, etc.).

### Personnalisation par mission

Un agent peut être personnalisé pour des missions spécifiques. C'est une couche de surcharge contextuelle au-dessus de la configuration de base de l'agent :
- Le Rôle reste identique
- On injecte des instructions supplémentaires, contraintes, et données spécifiques à la mission
- Cela permet de customiser ce que l'on pousse à l'agent avant l'exécution d'une tâche

### Session de test

L'agent peut être instancié dans une session de test intégrée directement depuis le builder :
- Lance le container Docker avec la config complète (Rôle + MCP + Skills + paramètres)
- Ouvre une interface interactive pour envoyer des instructions
- Observe les réponses en temps réel (events progress/result streamés via WebSocket)
- Permet de valider le comportement de l'agent avant déploiement dans un workflow

### Duplication

Un agent peut être dupliqué pour créer une variante. La duplication copie l'intégralité de la composition (Docker, Rôle, MCP, Skills, paramètres) avec un nouvel ID/Nom, permettant de dériver des agents spécialisés à partir d'une base commune.

### Actions

Créer, Éditer, Dupliquer, Tester, Supprimer. Vue liste des agents avec résumé visuel de leur composition.

### Communication inter-agents

Dans une session de travail, les agents doivent pouvoir communiquer entre eux. Le mécanisme exact d'adressage sera défini ultérieurement, mais le principe est posé :

- Les prompts de personnalisation mission injectés dans l'agent normalisent le format des messages destinés à d'autres agents
- Le dispatcher intercepte ces messages et les route vers l'agent cible dans la même session
- Le format de message inter-agent est standardisé (identification de l'agent destinataire, payload, type de requête)
- Un agent peut solliciter un autre agent pour une sous-tâche et attendre sa réponse

### Tools normalisés

Le système doit être capable de réimplémenter les tools qu'on avait dans LangGraph (function calling). L'objectif est de normaliser un système de tools entre agflow.docker et ses consommateurs :

- Le consommateur (ex: LangGraph, ou tout autre orchestrateur) déclare des **tools** qu'il met à disposition des agents
- Chaque tool a un schéma normalisé : nom, description, paramètres d'entrée (JSON Schema), format de retour
- Quand un agent veut appeler un tool, il émet un event typé via le protocole stdout. Le dispatcher intercepte l'appel, le route vers le consommateur qui exécute le tool et retourne le résultat à l'agent
- Les MCP globaux (Module 3d) sont exposés comme des tools aux agents via ce même mécanisme normalisé
- Le catalogue des tools disponibles est injecté dans le prompt de l'agent au lancement (description des tools au format que l'agent CLI peut consommer)

**RAG (Retrieval-Augmented Generation)** :
- Les tools doivent inclure la possibilité de **consommer des RAG externes** : un agent peut interroger une base de connaissances vectorielle externe via un tool normalisé (query → résultats pertinents injectés dans le contexte)
- Possibilité d'**indexer des RAG externes** : alimenter une base vectorielle avec des documents (fichiers du workspace, documentation projet, etc.) pour la rendre disponible aux agents via les tools
- Les RAG sont exposés comme des tools standard (même schéma : nom, description, paramètres) — l'agent n'a pas besoin de savoir qu'il interroge un RAG vs un autre type de tool

---

## Module 5 — API publique (Pilotage des agents)

API REST + WebSocket exposant le pilotage complet des agents à des consommateurs externes. C'est l'interface programmatique d'ag.flow.

### 5a — Authentification & API Keys

- CRUD des API Keys : création, révocation, listing, rotation
- Chaque clé a : un nom, des permissions (scopes), une date d'expiration optionnelle, un rate limit
- Authentification par header `Authorization: Bearer <api_key>`
- Audit log de tous les appels API par clé

### 5b — Découverte des agents

- `GET /api/v1/agents` — Liste des types d'agents disponibles avec description, composition résumée (Docker, Rôle, MCP, Skills), paramètres acceptés
- `GET /api/v1/agents/{agent_id}` — Détail complet d'un agent avec sa fiche descriptive
- Les propriétés détaillées seront ajoutées ultérieurement

### 5c — Sessions de travail

- `POST /api/v1/sessions` — Création d'une session de travail. Une session est un espace isolé qui contient N agents/missions. Retourne un `session_id`.
- `GET /api/v1/sessions/{session_id}` — État de la session (agents actifs, durée, ressources)
- `DELETE /api/v1/sessions/{session_id}` — Suppression de la session. Détruit tous les containers agents associés, cleanup des volumes et ressources.

### 5d — Agents dans une session (instanciation par mission)

- `POST /api/v1/sessions/{session_id}/agents` — Création d'un agent dans la session. Paramètres : `agent_id` (le type d'agent), personnalisation mission (instructions supplémentaires, contraintes, données contextuelles). Lance le container Docker avec la config complète. Retourne un `instance_id`.
- `GET /api/v1/sessions/{session_id}/agents` — Liste des agents actifs dans la session
- `DELETE /api/v1/sessions/{session_id}/agents/{instance_id}` — Destruction de l'agent (graceful shutdown → force kill → cleanup)

### 5e — Architecture de communication (MOM central)

Toutes les entrées et sorties des agents passent par un **middleware orienté messages (MOM)** qui est le bus central de communication. Rien ne communique directement avec les containers — tout transite par le MOM.

**Pattern** :
```
Producteurs → MOM (bus central) → Consommateurs
```

**Producteurs (entrée vers l'agent)** :
- API REST (`POST /message`)
- WebSocket client
- Autre agent (communication inter-agents)
- Orchestrateur externe (LangGraph, etc.)
- Appels tools (retour de résultat)

**MOM (bus central)** :
- Reçoit tous les messages, les persiste (traçabilité), et les route vers les bonnes sorties
- File d'attente par agent/instance (garantie d'ordre, pas de perte)
- Messages durables — si un consommateur est déconnecté, les messages sont bufferisés et livrés à la reconnexion
- Technologie : **Redis Streams** avec consumer groups. Lib Python : `redis.asyncio`. Chaque instance d'agent a son propre stream. Les consumer groups permettent de brancher N consommateurs (WebSocket, traçabilité, inter-agents) sur le même stream avec ACK (pas de perte de messages). Redis déployé en container Docker sur l'infrastructure.

**Consommateurs (sortie depuis le MOM)** :
- **stdin container** : le dispatcher lit la file de l'agent et pousse vers le stdin du container Docker
- **WebSocket client** : les events stdout de l'agent sont publiés sur le MOM, puis poussés vers les WebSocket connectées
- **API REST polling** : `GET /messages` lit depuis le MOM/base
- **Inter-agents** : un message destiné à un autre agent est routé vers sa file dans le MOM
- **Tools/RAG** : les appels tools émis par l'agent transitent par le MOM vers le handler de tools, qui retourne le résultat via le MOM
- **Persistance** : un consommateur dédié persiste tous les messages en base pour la traçabilité (Module 5f)

**Format de message normalisé** :
Tous les messages sur le bus suivent le même schéma : `session_id`, `instance_id`, `direction` (in/out), `type` (instruction/progress/result/tool_call/tool_result/agent_message/llm_call/error), `payload`, `timestamp`, `source` (API key, agent_id, system).

**Endpoints API** :
- `WebSocket /api/v1/sessions/{session_id}/agents/{instance_id}/stream` — Canal bidirectionnel temps réel. Se branche sur le MOM comme producteur et consommateur.
- `POST /api/v1/sessions/{session_id}/agents/{instance_id}/message` — Envoie un message ponctuel via le MOM
- `GET /api/v1/sessions/{session_id}/agents/{instance_id}/messages` — Lecture de l'historique depuis la base (persisté par le consommateur de traçabilité)

### 5f — Traçabilité

- Un consommateur dédié sur le MOM persiste **tous** les messages (in/out, tools, inter-agents, erreurs) en base (asyncpg)
- Chaque message : timestamp, session_id, instance_id, direction (in/out), type, payload complet, source
- `GET /api/v1/sessions/{session_id}/agents/{instance_id}/messages` — Historique des échanges, filtrable par type et direction
- `GET /api/v1/sessions/{session_id}/messages` — Historique consolidé de toute la session
- La traçabilité de l'activité interne de l'agent (Module 6h) passe aussi par le MOM — les events `llm_call`, `tool_call`, `mcp_call`, `file_change` sont des messages comme les autres

### 5g — Accès Docker (Debug / Inspection)

- `WebSocket /api/v1/sessions/{session_id}/agents/{instance_id}/exec` — Shell interactif dans le container via aiodocker exec. WebSocket bidirectionnel (terminal dans le navigateur).
- `GET /api/v1/sessions/{session_id}/agents/{instance_id}/logs` — Logs du container (stdout/stderr), streamable
- `GET /api/v1/sessions/{session_id}/agents/{instance_id}/files` — Browse du filesystem du container (workspace)
- Garde-fous : timeout sur les sessions exec, audit log de toutes les commandes, permissions par scope d'API key

---

## Module 6 — Supervision & Lifecycle interne des agents

Système de supervision qui gère l'état réel des containers agents indépendamment des connexions clients. C'est un service backend persistant (daemon/worker) qui tourne en continu.

### 6a — États d'un agent

Machine à états complète pour chaque instance d'agent :

- `CREATING` → container en cours de lancement
- `RUNNING` → container actif, connecté, en attente ou en traitement
- `BUSY` → agent en cours d'exécution d'une tâche
- `DISCONNECTED` → la connexion client (WebSocket) a été perdue, mais le container tourne encore. Timer de grâce avant décision.
- `RECONNECTING` → un client se reconnecte à un agent existant (récupération de session)
- `ORPHAN` → aucune connexion client depuis plus de X secondes/minutes (configurable). L'agent est candidat au garbage collection.
- `STOPPING` → graceful shutdown en cours
- `STOPPED` → container arrêté proprement
- `FAILED` → le container a crashé ou le process interne a retourné une erreur fatale

Toutes les transitions sont persistées en base avec timestamp pour audit.

### 6b — Détection de déconnexion / reconnexion

- **Heartbeat** : ping/pong configurable sur la WebSocket (ex: toutes les 10s). Si N pings consécutifs sans réponse → état `DISCONNECTED`.
- **Health check container** : vérification périodique via aiodocker (le container tourne-t-il ? le process principal est-il vivant ?). Si le container est mort mais l'état en base dit `RUNNING` → correction vers `FAILED`.
- **Reconnexion** : un client peut se reconnecter à un agent `DISCONNECTED` ou `RUNNING` via le même `instance_id`. Le serveur rattache la WebSocket au container existant, renvoie l'historique des messages manqués (depuis la dernière déconnexion), et reprend le streaming. L'agent ne redémarre pas.
- **Fenêtre de reconnexion** : configurable par agent (ex: 5 minutes). Passé ce délai sans reconnexion → transition vers `ORPHAN`.

### 6c — Gestion des orphelins

Un agent `ORPHAN` est un container qui tourne sans qu'aucun client ne le pilote. Le garbage collector les détecte.

Politique configurable par agent ou globalement :
- `KILL_IMMEDIATE` — détruire immédiatement
- `GRACE_PERIOD` — attendre encore N minutes puis détruire
- `KEEP_ALIVE` — ne pas détruire (agents long-running intentionnels), mais alerter

Avant destruction : sauvegarder l'état final (logs, derniers messages, exit code) en base pour traçabilité. Nettoyage complet : stop container → remove container → cleanup volumes temporaires.

### 6d — Garbage Collector (Worker de supervision)

Service asyncio en boucle (intervalle configurable, ex: 30s). À chaque tick :

- Scan des agents en base
- Réconciliation avec l'état réel Docker (via aiodocker)
- Détection des incohérences (container mort mais état `RUNNING`, container inconnu qui tourne, etc.)
- Détection des sessions abandonnées : si tous les agents d'une session sont `ORPHAN` ou `STOPPED`, la session est marquée pour cleanup
- Métriques exposées : nombre d'agents par état, orphelins détectés/détruits, containers zombies réconciliés, durée moyenne des sessions

### 6e — Réconciliation au démarrage

Au (re)démarrage du service ag.flow :
- Scan de tous les containers Docker avec le label `agflow-*`
- Réconciliation avec l'état en base
- Cleanup des containers orphelins d'une session précédente
- Reprise des agents encore viables

### 6f — Nettoyage des images Docker

Les compilations successives depuis le Module 1 génèrent des images taguées `agflow-{agent}:{short-sha}`. Sans nettoyage, elles s'accumulent.

- **Politique de rétention** : configurable par agent ou globalement — garder les N dernières images (ex: 3), garder les images des X derniers jours, garder uniquement l'image actuellement utilisée par au moins un agent composé (Module 4).
- **Images orphelines** : une image est orpheline si elle n'est référencée par aucun agent composé actif ET n'est pas la dernière image compilée pour son Dockerfile. Le garbage collector (6d) inclut ce scan dans son cycle.
- **Protection** : une image utilisée par un container actif (`RUNNING`, `BUSY`, `DISCONNECTED`) ne peut jamais être supprimée. Vérification via aiodocker avant toute suppression.
- **Layers dangling** : le GC exécute périodiquement un `docker image prune` pour les layers intermédiaires non référencées.
- **Nettoyage manuel** : depuis le Module 1 (Dockerfiles), bouton pour voir la liste des images compilées pour un agent avec taille, date, statut (active/orpheline), et action de suppression manuelle.
- **Métriques** : espace disque récupéré, nombre d'images purgées, alertes si espace disque sous un seuil configurable.

### 6g — Nettoyage des containers stoppés

Les containers en état `STOPPED` ou `FAILED` restent présents sur le système Docker après leur arrêt.

- **Sauvegarde avant suppression** : avant de supprimer un container stoppé, le GC s'assure que les logs finaux, le dernier état, l'exit code et les messages in/out ont bien été persistés en base (Module 5f — Traçabilité). Pas de suppression tant que la sauvegarde n'est pas confirmée.
- **Politique de rétention** : configurable — délai après arrêt avant suppression (ex: garder 1h pour debug post-mortem, ou supprimer immédiatement). Option de rétention prolongée pour les containers `FAILED` (utile pour l'inspection via `docker exec` / `docker logs` post-crash).
- **Volumes associés** : à la suppression du container, nettoyage des volumes temporaires montés (workspace). Les volumes marqués comme persistants (résultats à conserver) sont exclus.
- **Containers fantômes** : le GC détecte les containers Docker avec label `agflow-*` qui n'ont aucune correspondance en base (créés manuellement, ou suite à un crash du service avant enregistrement). Ces containers sont loggués puis supprimés.
- **Nettoyage manuel** : depuis la session de test (Module 4) ou l'API (Module 5), possibilité de forcer le nettoyage d'un container spécifique.
- **Métriques** : containers purgés par cycle, espace disque/mémoire libéré, containers fantômes détectés.

### 6h — Traçabilité de l'activité interne de l'agent

Le Module 5f trace les messages in/out entre le dispatcher et l'agent. Cette section couvre la traçabilité de **ce qui se passe à l'intérieur** du container pendant l'exécution.

**Événements tracés** :
- **Appels LLM** : modèle appelé, prompt envoyé (ou hash/résumé), réponse reçue, tokens consommés (input/output), latence, coût estimé
- **Appels tools** : quel tool appelé, paramètres d'entrée, résultat retourné, durée d'exécution, succès/échec
- **Appels MCP** : quel serveur MCP sollicité, quelle méthode, paramètres, réponse, latence
- **Communication inter-agents** : messages envoyés à d'autres agents, réponses reçues, agent destinataire/expéditeur
- **Fichiers** : fichiers créés, modifiés ou supprimés dans le workspace, diffs si possible
- **Erreurs** : exceptions, timeouts, échecs de connexion MCP, rate limits LLM

**Mécanisme de collecte** :
- L'entrypoint émet des events typés supplémentaires sur stdout (au-delà de `progress` et `result`) : `llm_call`, `tool_call`, `mcp_call`, `file_change`, `error`
- Le dispatcher collecte ces events et les persiste en base avec le même schéma que la traçabilité Module 5f (timestamp, session_id, instance_id, type, payload)
- Le protocole entrypoint standardisé est enrichi pour supporter ces types d'events additionnels

**Consultation** :
- `GET /api/v1/sessions/{session_id}/agents/{instance_id}/activity` — Timeline de l'activité interne, filtrable par type d'événement
- Vue dans l'UI : timeline visuelle de l'activité de l'agent pendant une session de test (Module 4) ou en production
- Agrégations : total tokens consommés, nombre d'appels LLM/tools/MCP, coût estimé par session/agent

---

## Contraintes techniques transversales

- **Frontend** : React + TypeScript strict
- **Backend** : FastAPI
- **Base de données** : PostgreSQL comme persistence centrale, accès via asyncpg (pas SQLAlchemy). Tout est géré en base — pas de fichiers sur disque pour la configuration.
- **Logging** : structlog JSON
- **Temps réel** : WebSocket pour le streaming vers les clients (logs, events, shell) — branché sur le MOM
- **Docker** : aiodocker pour toute interaction Docker (pas de subprocess bloquant)
- **Internationalisation** : i18n sur tous les labels
- **Qualité** : pas de fichier > 300 lignes, tests unitaires pour chaque composant
- **Identifiants** : identifiants stables (slugs) sur chaque entité pour permettre la composition inter-modules
- **Communication** : **Redis Streams** comme bus central (MOM) de toutes les communications agents. Lib Python : `redis.asyncio`. Consumer groups avec ACK pour la durabilité. Un stream par instance d'agent, N consommateurs par stream (WebSocket, REST, inter-agents, tools, traçabilité). Redis déployé en container Docker. Toutes les entrées/sorties transitent par le bus.

### PostgreSQL comme source de vérité

Toute la configuration et l'état de la plateforme sont stockés en PostgreSQL :

- **Module 0 (Secrets)** : secrets chiffrés (pgcrypto), alias, scopes, associations agents
- **Module 1 (Dockerfiles)** : contenu des Dockerfiles, entrypoints, run.cmd.md, paramètres, historique des builds, tags d'images compilées
- **Module 2 (Rôles)** : identité, rôles/missions/compétences (contenu markdown), paramètres LLM, flags de protection, arborescence des sous-sections
- **Module 3 (Catalogues)** : registres de découverte (URLs, clés), serveurs MCP installés, skills installées, métadonnées de transport
- **Module 4 (Agents)** : composition (FK vers Dockerfile, Rôle, MCP, Skills), paramètres lifecycle, mapping volumes, personnalisations mission
- **Module 5 (API)** : API keys, sessions de travail, instances d'agents, historique complet des messages in/out (traçabilité), audit logs
- **Module 6 (Supervision)** : états des agents (machine à états avec transitions horodatées), métriques GC, politiques de rétention

Les fichiers markdown (rôles, missions, compétences, skills) sont stockés comme contenu texte en base — pas comme fichiers sur le filesystem. Le filesystem Docker n'est utilisé que pour les volumes runtime des containers (workspace, output) et les images Docker elles-mêmes.

Notification inter-services via `PG NOTIFY` / `LISTEN` pour les événements temps réel (changement d'état d'un agent, build terminé, etc.) sans dépendance à un broker externe.
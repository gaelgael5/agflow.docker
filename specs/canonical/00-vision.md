# 00 — Vision et périmètre

## Vocation

**agflow.docker** est une plateforme d'orchestration de ressources conteneurisées et d'agents IA. Sa vocation tient en trois lignes :

1. **Instancier dans des conteneurs Docker** les ressources nécessaires à un projet : wiki, dépôt Git, base de données, broker de messages, MCP server, etc.
2. **Faire communiquer ces conteneurs entre eux** au sein du projet auquel ils appartiennent.
3. **Ouvrir des sessions** dans lesquelles un ou plusieurs **agents IA** (Claude Code, Aider, Codex, Gemini, etc.) conversent avec ces ressources pour produire du travail.

L'administrateur compose, l'opérateur déploie, l'orchestrateur externe (ou l'opérateur lui-même) consomme l'API publique pour exécuter des workflows.

## Modèle conceptuel central

```
                  ┌─────────────────────────────────────────────┐
                  │   Ressource projet (template / blueprint)   │
                  │   = configuration d'un ensemble de services │
                  └─────────────────────────────────────────────┘
                                       │
                          provisionner │
                                       ▼
                  ┌─────────────────────────────────────────────┐
                  │   Instance projet (project_runtime)          │
                  │   = conteneurs Docker effectivement déployés │
                  │     sur une cible Docker / Swarm / K3s       │
                  └─────────────────────────────────────────────┘
                                       │
                          y attacher   │
                                       ▼
                  ┌─────────────────────────────────────────────┐
                  │   Session                                    │
                  │   = exécution active avec ≥ 1 agent          │
                  │   • peut référencer une instance projet      │
                  │     → les agents ont accès à ses ressources  │
                  │   • peut être indépendante (sandbox, one-shot)│
                  └─────────────────────────────────────────────┘
                                       │
                          loger        │
                                       ▼
                  ┌─────────────────────────────────────────────┐
                  │   Agent (en session)                         │
                  │   = un conteneur d'agent IA en cours d'exéc  │
                  │     reçoit des « work » via l'API           │
                  └─────────────────────────────────────────────┘
```

Tout part de l'idée que **les ressources sont des conteneurs Docker** et que **les projets groupent les ressources qui doivent communiquer**. Les sessions sont l'unité d'exécution temporelle ; les agents sont les acteurs intelligents qui agissent dans ces sessions.

## Cas d'usage prototypiques

1. **Workflow piloté par ag.flow** : un workflow externe orchestre plusieurs étapes ; pour chaque étape qui nécessite un agent IA, il appelle l'API publique d'agflow.docker, ouvre une session liée à un project_runtime, instancie un agent, lui passe une instruction, et reçoit le résultat via un hook signé HMAC.
2. **Sandbox d'un développeur** : un développeur ouvre une session avec un agent Claude Code sans projet associé, lui demande de modifier du code dans son workspace temporaire, récupère les fichiers générés.
3. **Plateforme produit** : un projet « espace de travail intégré » assemble un wiki Outline, un dépôt Gitea, un kanban et un agent assistant ; chaque utilisateur reçoit une instance projet dédiée déployée sur une machine attribuée, et y connecte des sessions d'agents.

## Principes directeurs

### Qualité de code

Le code de la plateforme est **propre, prévisible, testé**. Les compromis « quick-and-dirty » sont interdits ; quand une fonctionnalité est trop large pour être faite proprement, elle est découpée et seule la part faisable proprement est livrée.

### Sécurité par défaut

- Tous les secrets transitent par **Harpocrate** (coffre-fort externe end-to-end encrypted). La base de données ne stocke que des références.
- Toute communication d'agent vers le workflow externe est **signée HMAC**.
- Toute connexion SSH machine utilise **clés** (RSA ou Ed25519) chiffrées au repos, jamais des mots de passe en clair.

### Isolation par projet

Les conteneurs d'un même projet partagent un **réseau Docker dédié** ; ceux de projets différents ne se voient pas. Une instance projet déployée pour un utilisateur expose des préfixes de hostname qui évitent les collisions entre utilisateurs.

### Indépendance vis-à-vis de l'orchestrateur externe

agflow.docker fonctionne **autonome** : son panneau d'administration permet d'instancier des ressources, ouvrir des sessions, lancer des tâches one-shot sans dépendre d'ag.flow. L'intégration ag.flow est une consommation de l'API publique, pas une dépendance.

### Code as configuration

Tout artefact configurable (Dockerfile d'agent, rôle, template, recette produit, script de déploiement) est versionné dans la base et exportable en archive ZIP. Les recettes produits et les scripts de groupe utilisent **Jinja2 sandboxed** pour la génération.

## Hors-scope

- **Hébergement de modèles LLM** : agflow.docker appelle des providers IA externes (Anthropic, OpenAI, Mistral, etc.) configurés par l'administrateur. Il n'embarque pas et n'héberge pas de modèle.
- **Catalogue MCP propriétaire** : les MCP servers et skills sont découverts via des registres externes (par défaut `mcp.yoops.org`) configurables.
- **Authentification multi-tenant complète** : un utilisateur appartient à une instance d'agflow.docker ; le multi-tenant inter-organisations est délégué à Keycloak ou à un déploiement séparé.
- **Build de conteneurs depuis du source arbitraire** : la plateforme construit des images d'agents depuis des Dockerfiles versionnés par l'administrateur. La construction d'images depuis du code source arbitraire est hors-scope.
- **Gestion fine de cluster Kubernetes** : agflow.docker peut déployer ses ressources sur K3s ou K8s, mais ne fournit pas d'interface d'administration du cluster lui-même (`kubectl`, opérateurs, etc.).

## Public visé

- **Administrateurs de la plateforme** : composent les agents, gèrent les secrets, configurent les coffres et les providers IA, supervisent les sessions.
- **Opérateurs de projet** : créent et déploient des instances projet, déclenchent les wizards de déploiement, suivent les restaurations.
- **Développeurs intégrateurs** : consomment l'API publique V1 pour piloter agflow.docker depuis un workflow externe.
- **Agents IA d'onboarding** (Claude, Codex, etc.) : assimilent cette spec en premier quand on les fait travailler sur le projet.

# agflow.docker — Spécification canonique

**Statut** : référence vivante de la plateforme.
**Public** : développeurs, agents IA d'onboarding, opérateurs, architectes.
**Format** : lecture séquentielle des fichiers numérotés ou navigation thématique.

---

## En une phrase

**agflow.docker** est une plateforme d'orchestration qui instancie dans des conteneurs Docker les ressources nécessaires à un projet (services métier comme un wiki, un dépôt Git, une base de données, etc.) et qui ouvre des sessions où des agents IA conversent avec ces ressources pour produire un travail.

L'administrateur compose les briques (agents, services, scripts), groupe les ressources d'un projet, et déploie le tout sur l'infrastructure Docker de son choix (Docker simple, Docker Swarm ou Kubernetes / K3s). L'API publique permet à un orchestrateur externe (typiquement `ag.flow`) d'utiliser la plateforme pour exécuter des workflows.

---

## Table des matières

| # | Fichier | Sujet |
|---|---|---|
| — | [README.md](./README.md) | Ce fichier — index + entrée du document |
| 00 | [00-vision.md](./00-vision.md) | Vocation, périmètre, principes directeurs, hors-scope |
| 01 | [01-glossaire.md](./01-glossaire.md) | Vocabulaire : ressource, projet, session, agent, work, etc. |
| 02 | [02-architecture.md](./02-architecture.md) | Stack technique, layout du code, services internes, infrastructures cibles |
| 03 | [03-modele-de-donnees.md](./03-modele-de-donnees.md) | Schéma de la base PostgreSQL, tables principales et leurs rôles |
| 04 | [04-modules-admin.md](./04-modules-admin.md) | Les 8 modules du panneau d'administration (M0 à M7) |
| 05 | [05-cycle-execution.md](./05-cycle-execution.md) | Cycle de vie session → agent → work → résultat → hook |
| 06 | [06-deploiement.md](./06-deploiement.md) | Wizard de déploiement, modes Docker / Swarm / K3s, machines cibles |
| 07 | [07-securite.md](./07-securite.md) | Auth UI (Keycloak + admin local), API (clés natives), secrets (Harpocrate), HMAC, certificats |
| 08 | [08-api-publique.md](./08-api-publique.md) | API publique V1 (`/api/v1/*`) consommée par les clients externes |
| 09 | [09-integration-ag-flow.md](./09-integration-ag-flow.md) | Contrat d'intégration avec le workflow service ag.flow (correlation_id, hooks signés) |
| 10 | [10-backup-restore.md](./10-backup-restore.md) | Backups classiques, PITR (pgbackrest), git-sync configuration, restore wizard |
| 11 | [11-observabilite.md](./11-observabilite.md) | Logs Loki + Grafana, supervision M6, dashboards, tests fonctionnels |
| 12 | [12-conventions.md](./12-conventions.md) | Standards de code, workflow git, conventions de tests |
| 13 | [13-catalogues.md](./13-catalogues.md) | Templates Jinja2, scripts, AI providers, image registries, avatars, service types, apps |
| 14 | [14-contrats-api-agents.md](./14-contrats-api-agents.md) | Contrats OpenAPI attachés aux agents, profils de mission, génération des fichiers de runtime |
| 15 | [15-parcours-end-to-end.md](./15-parcours-end-to-end.md) | Sept scénarios end-to-end illustrant l'usage opérationnel de la plateforme |

---

## Comment lire ce document

**Pour une IA qui découvre le projet** : lire dans l'ordre 00 → 12. Chaque fichier est rédigé pour être lu indépendamment, mais l'ordre numérique présente les concepts du plus général au plus spécifique. Le glossaire (01) doit être assimilé tôt.

**Pour un humain expérimenté du projet** : commencer par le sujet qui change, puis croiser avec le glossaire si un terme paraît ambigu.

**Pour le code** : le fichier 03 (modèle de données) et 02 (architecture) sont les plus proches de l'implémentation. L'API exacte est documentée dans l'OpenAPI généré à `https://docker-agflow.yoops.org/openapi.json` ; cette spec décrit l'intention et les concepts, pas chaque endpoint.

---

## Principes éditoriaux

- **Source de vérité unique** : ce document remplace toute spec antérieure. Si vous trouvez un autre document qui contredit celui-ci, ce document a raison ; signalez la contradiction pour qu'elle soit résolue.
- **Vivant** : tout changement d'architecture ou de comportement met à jour cette spec dans le même chantier que le code.
- **Sans historique** : ce document décrit le système **tel qu'il est**, pas comment il en est arrivé là. L'historique vit dans les commits et les plans (`docs/superpowers/plans/`).
- **Cohérent** : le vocabulaire d'un fichier est exactement celui des autres. Si un mot est défini dans le glossaire, on l'utilise uniquement avec ce sens.

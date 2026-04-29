# Cas 04 — Projet, ressources partagées et MCP externes

## Contexte

La session n'est plus ad hoc : elle est **rattachée à un projet** préalablement créé
dans agflow. Le projet contient des ressources partagées (fichiers, spécifications,
livrables d'itérations précédentes). Les agents instanciés dans cette session peuvent :

- **Lire** les ressources du projet pour alimenter leur travail,
- **Écrire** leurs livrables sur le projet,
- **Interroger** un MCP externe (par ex. recherche web, documentation de bibliothèque)
  via un outil MCP installé sur l'agent.

Ce cas couvre donc le **contexte persistant** (projet) et l'**outillage externe**
(MCP), qui sont les deux dimensions manquantes des cas précédents pour un usage réel
au-delà de la démo.

## Acteurs

| Acteur | Rôle |
|--------|------|
| `App` | Application cliente |
| `Sessions` | API publique d'agflow |
| `Bus` | MOM bus |
| `AgentA` | Agent équipé d'un MCP de recherche et d'un outil d'écriture fichier |
| `Project` | Ressources partagées du projet (fichiers en lecture/écriture, état persistant) |
| `MCP` | Registre/serveur MCP externe (ex : `mcp.yoops.org` pour recherche doc) |

## Workflow

```mermaid
sequenceDiagram
    autonumber
    actor App as App
    participant Sessions as Sessions
    participant Bus as Bus
    participant AgentA as AgentA
    participant Project as Project
    participant MCP as MCP

    Note over App,Project: Le projet existe déjà avec ses ressources initiales<br/>(fichiers de spec, livrables précédents)

    App->>Sessions: Ouvrir une session liée au projet (project_id)
    Sessions-->>App: session_id
    Note over Sessions,Project: La session hérite du scope projet :<br/>les agents y auront accès en lecture/écriture

    App->>Sessions: Instancier AgentA (avec outils MCP + écriture fichier)
    Sessions-->>App: instance_a_id
    Note over AgentA,Project: AgentA voit les ressources du projet au démarrage

    App->>Sessions: Soumettre demande (ex : "documente la fonctionnalité X")
    Sessions->>Bus: Publier
    Bus-->>AgentA: Livrer
    Sessions-->>App: ack

    AgentA->>Project: Lire les specs existantes
    Project-->>AgentA: Contenu des specs

    AgentA->>MCP: Rechercher référence documentaire externe
    MCP-->>AgentA: Résultats de recherche
    Note over AgentA: Le MCP est un service externe ;<br/>son appel sort du périmètre agflow

    AgentA->>AgentA: Synthèse (specs projet + résultats MCP)

    AgentA->>Project: Écrire le livrable (nouveau fichier ou mise à jour)
    Project-->>AgentA: Confirmation d'écriture

    AgentA->>Bus: Publier le résultat final (référence au livrable écrit)

    loop Polling
        App->>Sessions: Interroger les messages (instance_a_id)
        Sessions-->>App: Résultat + référence du livrable produit
    end

    App->>Sessions: Fermer la session
    Sessions-->>App: session fermée
    Note over Project: Les ressources écrites persistent dans le projet<br/>au-delà de la fin de la session
```

## Points clés

- **La session hérite du scope projet** : instancier un agent dans une session "projet" lui donne implicitement les permissions de lecture/écriture sur les ressources de ce projet. L'application n'a pas à gérer d'ACL finement — c'est le projet qui porte la confiance.
- **Les livrables survivent à la session** : fermer la session ne supprime pas ce que l'agent a écrit sur le projet. La session est un contexte d'exécution, le projet est le conteneur persistant.
- **Le MCP est hors périmètre agflow** : les appels MCP ne transitent pas par le bus interne. Ils sont la responsabilité de l'agent (qui gère auth, retry, timeout vis-à-vis du MCP). Depuis l'App, seul le résultat consolidé est visible.
- **Sources multiples dans un résultat** : le résultat final peut référencer à la fois des ressources du projet (livrables produits) et des éléments récupérés via MCP. L'application doit être prête à consommer un résultat structuré.
- **Concurrence sur le projet** : si deux agents d'une même session écrivent sur la même ressource, l'ordre et la résolution de conflit dépendent du type de ressource (append-only, overwrite, lock). Ce n'est pas traité dans le happy path.
- **Prérequis plateforme** : le projet, ses ressources initiales, et l'outil MCP (avec ses secrets) doivent être configurés en amont côté admin. Ces étapes de setup sont hors workflow applicatif.

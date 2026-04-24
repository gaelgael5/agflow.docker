# Scénario A01 — Bootstrap de la plateforme (opérateur)

## Contexte

Avant qu'une application cliente puisse ouvrir une session et instancier un agent,
l'opérateur de la plateforme doit préparer le **minimum viable** : un administrateur
authentifié, au moins un secret de LLM valide, un dockerfile buildé, un rôle, un agent
composé, et une API key livrée au client. Ce scénario décrit ce parcours dans l'ordre
minimal — toute étape omise rend un cas applicatif (01+) inexécutable.

## Acteurs

| Acteur | Rôle |
|--------|------|
| `Operator` | Administrateur humain qui configure la plateforme |
| `Admin API` | Endpoints admin d'agflow (`/api/admin/*`) |
| `Registry` | Registre MCP externe optionnel (non requis ici) |
| `Client` | Application cliente qui recevra l'API key en fin de parcours |

## Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator
    participant AdminAPI as Admin API
    actor Client as Client

    Operator->>AdminAPI: Se connecter (email/password ou SSO)
    AdminAPI-->>Operator: JWT admin

    Note over Operator: Étape 1 — Secrets plateforme
    Operator->>AdminAPI: Créer un secret ANTHROPIC_API_KEY (ou équivalent)
    AdminAPI-->>Operator: Secret stocké chiffré
    Operator->>AdminAPI: Tester le secret (validation auprès du provider)
    AdminAPI-->>Operator: Validation OK

    Note over Operator: Étape 2 — Image d'agent
    Operator->>AdminAPI: Créer un dockerfile (métadonnées)
    AdminAPI-->>Operator: dockerfile_id
    Operator->>AdminAPI: Uploader les fichiers (Dockerfile, entrypoint, Dockerfile.json)
    AdminAPI-->>Operator: Fichiers enregistrés
    Operator->>AdminAPI: Lancer un build
    AdminAPI-->>Operator: Build en cours
    Note over AdminAPI: Build Docker asynchrone
    AdminAPI-->>Operator: Build succeeded, image taggée

    Note over Operator: Étape 3 — Persona
    Operator->>AdminAPI: Créer un rôle (id, display_name, description)
    AdminAPI-->>Operator: role_id
    Operator->>AdminAPI: Ajouter sections et documents (persona, règles, exemples)
    AdminAPI-->>Operator: Rôle complet

    Note over Operator: Étape 4 — Composition de l'agent
    Operator->>AdminAPI: Créer un agent (slug, dockerfile_id, role_id, env vars)
    AdminAPI-->>Operator: agent_id
    Operator->>AdminAPI: Ajouter au moins un profil de mission
    AdminAPI-->>Operator: Profil créé

    Note over Operator: Étape 5 — Clé API pour le client
    Operator->>AdminAPI: Créer une API key (scopes, rate limit, expiration)
    AdminAPI-->>Operator: Clé brute affichée une seule fois
    Operator-->>Client: Transmission sécurisée de la clé (hors agflow)

    Note over Client: Le client peut maintenant exécuter les cas 01+
```

## Points clés

- **Ordre strict** : on ne peut pas composer un agent sans dockerfile + rôle. On ne peut pas livrer une clé API à un client si les scopes mentionnent des capacités inexistantes.
- **Le secret LLM conditionne tout** : sans clé LLM valide, l'agent démarrera son container mais échouera au premier appel. Le test de secret est essentiel avant la composition.
- **Build asynchrone** : le build d'image peut durer plusieurs minutes. L'opérateur suit l'état via l'historique des builds (endpoint dédié). Tant que le build n'est pas `success`, l'agent ne peut pas être instancié en session.
- **Clé API vue une seule fois** : la valeur brute de l'API key n'est retournée qu'à la création. Si perdue, la clé doit être révoquée et recréée. L'opérateur doit livrer au client un canal de transmission sécurisé (password manager, gestionnaire de secrets).
- **Scopes minimaux** : livrer `agents:read agents:run messages:read messages:write` couvre les cas 01-05. Pour le cas 04 (projet + ressources), ajouter les scopes associés.
- **Hors scope ici** : MCP (voir A02), projet + ressources (voir A03), infrastructure (machines SSH, K3s), supervision runtime.

## Ce que ça débloque côté client

- Cas 01 — Demande minimale à un agent
- Cas 02 — Deux agents en parallèle
- Cas 03 — Communication inter-agents
- Cas 05 — Streaming live
- Cas 06 — Session longue avec extension
- Cas 07 — Découverte du catalogue
- Cas 09 — Post-mortem logs et fichiers

Les cas 04 et 08 demandent en plus les scénarios A02 (MCP) et A03 (projets).

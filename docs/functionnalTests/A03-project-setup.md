# Scénario A03 — Création d'un projet et de ses ressources

## Contexte

Pour qu'une application puisse rattacher ses sessions à un projet et que ses agents
accèdent à des ressources partagées (fichiers, specs, livrables historiques), l'opérateur
doit **créer le projet** et **le peupler** en amont. Une session liée à un projet
inexistant est refusée ; un projet sans ressources initiales est utilisable mais ne
profite pas de la valeur du contexte persistant.

Ce scénario est le complément du A01 (plateforme) et du A02 (MCP). Il est nécessaire
pour atteindre le cas applicatif 04.

## Acteurs

| Acteur | Rôle |
|--------|------|
| `Operator` | Administrateur |
| `Admin API` | Endpoints admin d'agflow |
| `Project Store` | Stockage des ressources projet (fichiers, instances, groupes) |

## Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator
    participant AdminAPI as Admin API
    participant ProjectStore as Project Store

    Note over Operator: Étape 1 — Création du projet
    Operator->>AdminAPI: Créer un projet (id, display_name, environment)
    AdminAPI->>ProjectStore: Persister la métadonnée projet
    ProjectStore-->>AdminAPI: Projet créé
    AdminAPI-->>Operator: project_id

    Note over Operator: Étape 2 — Groupes logiques (optionnel)
    Operator->>AdminAPI: Créer un groupe dans le projet (ex: "backend", "docs")
    AdminAPI->>ProjectStore: Enregistrer le groupe
    AdminAPI-->>Operator: group_id
    Note over Operator: Les groupes permettent de cloisonner<br/>les ressources d'un gros projet

    Note over Operator: Étape 3 — Ressources initiales
    loop Pour chaque ressource à peupler
        Operator->>AdminAPI: Ajouter une ressource (fichier de spec, livrable initial)
        AdminAPI->>ProjectStore: Écrire la ressource
        ProjectStore-->>AdminAPI: Ressource disponible
    end
    AdminAPI-->>Operator: Projet peuplé

    Note over Operator: Étape 4 — Activation pour les clients
    Operator->>AdminAPI: Vérifier l'état final du projet (ressources, groupes)
    AdminAPI-->>Operator: Vue consolidée
    Note over Operator: Le projet est prêt à être cité en project_id<br/>par les sessions du client

    Note over Operator: Étape 5 — (Optionnel) Revue de sécurité
    Operator->>AdminAPI: Lister les API keys clientes qui auront accès
    AdminAPI-->>Operator: Liste des clés (scope + owner)
    Note over Operator: L'opérateur contrôle qui peut<br/>référencer le project_id dans ses sessions
```

## Points clés

- **Projet = conteneur persistant** : contrairement à une session (éphémère), les ressources d'un projet survivent à toutes les sessions qui l'utilisent. C'est le lieu où les agents déposent leurs livrables durables.
- **Groupes facultatifs** : pour un petit projet, les ressources peuvent être à plat. Les groupes deviennent utiles quand le projet couvre plusieurs domaines (backend / frontend / docs) et qu'on veut restreindre certains agents à un sous-ensemble.
- **Ressources pré-existantes vs générées** : l'opérateur peut peupler le projet à la main (spec initiale, modèles, données de référence). Les agents ajouteront ensuite leurs livrables. Les deux coexistent.
- **Pas d'ACL par utilisateur sur le projet** : actuellement, tous les clients avec les bons scopes peuvent rattacher une session à n'importe quel projet. Pour affiner ça, il faudra la future table `session_users` (hors périmètre).
- **Suppression destructive** : supprimer un projet détruit ses ressources. Pas de corbeille pour l'instant. À manipuler avec soin côté UI admin.
- **Pas obligatoire pour démarrer** : les cas 01-03, 05-09 se passent de projet. Le projet ne devient nécessaire que si on veut du contexte persistant entre sessions.

## Ce que ça débloque côté client

- Cas 04 — Projet, ressources et MCP (la partie ressources du flux)
- Patterns multi-sessions sur un même projet (itérations successives, reprise de travail)

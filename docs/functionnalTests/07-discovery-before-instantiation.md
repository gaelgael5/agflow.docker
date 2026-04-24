# Cas 07 — Découverte du catalogue avant instanciation

## Contexte

Une application qui intègre agflow pour la première fois (ou qui veut s'adapter
dynamiquement à l'état du catalogue) ne peut pas hard-coder la liste des agents ni
leurs capacités. Elle doit **découvrir** ce qui est disponible, choisir un agent qui
matche son besoin, vérifier qu'il a les scopes et les outils attendus, puis instancier.

Ce cas couvre la **phase de reconnaissance** avant toute action. Il est particulièrement
utile pour une UI qui présente à l'utilisateur final la liste d'agents disponibles, ou
pour un client qui tourne face à plusieurs déploiements agflow potentiellement
hétérogènes.

## Acteurs

| Acteur | Rôle |
|--------|------|
| `App` | Application cliente en phase de découverte |
| `Sessions` | API publique d'agflow (endpoints de découverte + lifecycle) |

## Workflow

```mermaid
sequenceDiagram
    autonumber
    actor App as App
    participant Sessions as Sessions

    App->>Sessions: Lister les scopes disponibles
    Sessions-->>App: Liste des scopes (ex: agents:read, agents:run, files:write)
    Note over App: L'App vérifie que sa clé couvre ce dont elle a besoin

    App->>Sessions: Lister les rôles disponibles
    Sessions-->>App: Liste des rôles (blueprints : code-reviewer, doc-writer...)

    App->>Sessions: Lister les agents du catalogue
    Sessions-->>App: Liste des agents (id, nom, rôle, timeout, tags)

    Note over App: L'App filtre selon son besoin (ex: rôle "code-reviewer")

    App->>Sessions: Consulter le détail d'un agent candidat
    Sessions-->>App: Détail (rôle, outils MCP, skills, profils de mission, timeout)

    Note over App: L'App vérifie les bindings MCP/skills<br/>et choisit un profil de mission

    App->>Sessions: Ouvrir une session
    Sessions-->>App: session_id

    App->>Sessions: Instancier l'agent choisi (+ profil de mission si pertinent)
    Sessions-->>App: instance_id
    Note over App: L'App est maintenant dans le flux standard (cas 01-04)
```

## Points clés

- **Scopes avant tout** : une application qui n'a pas le scope requis recevra une erreur d'autorisation au moment d'instancier l'agent. Il est plus ergonomique de vérifier les scopes en amont et d'afficher un message clair (ou de demander un upgrade de clé).
- **Rôle = blueprint, agent = composition** : un rôle est un gabarit (persona + sections de prompt). Un agent est la composition concrète d'un rôle avec un Dockerfile et des outils. L'application choisit toujours un agent (pas un rôle).
- **Profils de mission** : certains agents exposent plusieurs variantes d'utilisation (ex : `strict`/`lenient` pour un code reviewer). Découvrir les profils permet à l'application de sélectionner le bon ton ou la bonne rigueur.
- **Catalogue dynamique** : ajouter/retirer un agent côté admin est visible immédiatement dans la découverte. Une application robuste rafraîchit sa liste régulièrement, pas uniquement au démarrage.
- **Pas de session requise pour découvrir** : les endpoints de découverte ne consomment aucune session. Ils peuvent être appelés avant même de savoir si on va instancier quoi que ce soit.
- **Retombée pédagogique pour l'utilisateur final** : exposer la description d'un rôle ou d'un agent dans l'UI aide l'utilisateur à comprendre pourquoi tel agent est proposé plutôt que tel autre.

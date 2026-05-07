# Brief Claude Code — Implémentation Storage SDK

## Contexte

ag.flow est une plateforme d'orchestration d'agents IA. Ce brief concerne l'implémentation du **Storage SDK** : une bibliothèque Python interne permettant à tous les services ag.flow de lire et écrire des fichiers versionnés en base de données PostgreSQL.

Le SDK remplace l'accès direct au disque qui était utilisé jusqu'ici, et permet de centraliser la gestion des fichiers (templates Jinja2, Dockerfiles, scripts, avatars, rôles agents, etc.) dans PostgreSQL.

## Objectif

Implémenter le fichier `storage_sdk.py` et appliquer la migration SQL correspondante.

## Fichiers de référence

- `storage_sdk_spec.md` : spécification complète de chaque méthode avec son algo
- `migration_storage.sql` : script SQL à appliquer (tables, triggers, indexes)
- `storage_sdk.py` : implémentation de référence à intégrer dans le projet

## Contraintes techniques

- **asyncpg uniquement** — pas de SQLAlchemy, pas d'ORM
- **Async-first** — toutes les méthodes sont `async`
- **Pas de fichier > 300 lignes** — si le SDK dépasse cette limite, le découper en `storage_sdk/core.py`, `storage_sdk/mime.py`, etc. avec un `storage_sdk/__init__.py` qui réexporte tout
- **Python 3.11+** — utiliser `from __future__ import annotations` pour les types
- **structlog** pour les logs si des logs sont ajoutés

## Tâches

### 1. Migration SQL

Appliquer `migration_storage.sql` dans le fichier `init.sql` existant du projet ou dans le dossier `migrations/` selon la convention du projet.

Vérifier que :
- Les trois tables sont créées avec `IF NOT EXISTS`
- Les triggers `set_updated_at` sont en place sur les trois tables
- Les indexes sont créés

### 2. Intégration du SDK

Placer `storage_sdk.py` à l'emplacement approprié selon la structure du projet (ex: `app/sdk/storage_sdk.py` ou `shared/storage_sdk.py`).

Le SDK s'instancie avec une connexion asyncpg :
```python
from storage_sdk import StorageSDK
storage = StorageSDK(db)
```

### 3. Tests

Écrire des tests pour les méthodes suivantes (pytest + asyncpg en mode test) :

- `create_folder_path` : vérifier la création récursive et l'idempotence
- `write_document` : vérifier la création, puis la mise à jour (même nom, contenu différent)
- `read_document` : vérifier la lecture après écriture
- `delete_node` : vérifier la suppression en cascade d'un folder avec enfants
- `write_node_on_disk` : vérifier la matérialisation sur disque d'un folder avec fichiers mixtes (text + binary)

### 4. Cas limites à gérer

- `write_document` avec un `name` sans extension (ex: `Dockerfile`) → doit être traité comme `kind=1` (texte)
- `create_folder_path` avec un path vide ou `/` → lever une `ValueError`
- `read_node` sur un UUID inexistant → retourner `None` sans exception
- `write_node_on_disk` sur un node `kind=1` ou `kind=2` sans folder parent → créer `target_path` si inexistant

## Ce qu'il ne faut pas faire

- Ne pas ajouter de dépendance externe autre qu'asyncpg et pathlib
- Ne pas implémenter de cache — c'est à la couche appelante d'en décider
- Ne pas gérer les transactions dans le SDK — c'est à l'appelant de passer une connexion dans une transaction si besoin
- Ne pas exposer de route FastAPI dans ce fichier — c'est un SDK, pas un service

## Définition de done

- [ ] Migration SQL appliquée et vérifiée
- [ ] `storage_sdk.py` intégré au projet et importable
- [ ] Tous les tests passent
- [ ] Aucune écriture directe sur disque dans le code applicatif (hors `write_node_on_disk`)

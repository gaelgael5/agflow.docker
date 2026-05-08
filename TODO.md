# Backlog technique

## Migration secrets infra → Harpocrate

**Objectif** : supprimer `AGFLOW_INFRA_KEY` (Fernet local) et stocker tous les secrets infra dans Harpocrate. Les tables Postgres ne doivent plus contenir de valeurs chiffrées localement.

**Périmètre** :

| Service | Secrets actuellement en base (Fernet) | Action |
|---|---|---|
| `infra_certificates_service` | `private_key`, `passphrase` (table `infra_certificates`) | Stocker dans Harpocrate, garder uniquement une référence (nom de clé) en base |
| `infra_machines_service` | `password` (table `infra_machines`) | Idem |
| `infra_swarm_clusters_service` | `worker_encrypted`, `manager_encrypted` (table `infra_swarm_clusters`) | Idem |

**Principe** : remplacer les colonnes `*_encrypted` par une colonne `*_secret_name` (ex: `INFRA_CERT_42_PRIVATE_KEY`) qui est le nom du secret dans Harpocrate. La valeur est résolue à la demande via `vault_client.get_secret()`.

**Dépendances** :
- `vault_client.py` déjà en place
- Nécessite une migration SQL (supprimer colonnes Fernet, ajouter colonnes ref)
- Nécessite une procédure de migration des données existantes (re-chiffrer dans Harpocrate)
- `AGFLOW_INFRA_KEY` peut être retiré de `config.py` et `.env.example` une fois terminé

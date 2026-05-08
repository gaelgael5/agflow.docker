# Backup / restore Postgres — agflow.docker

Scripts pour dumper et restaurer la base `agflow` du LXC 201.

## Backup

```bash
# Dump dans /root/agflow.docker/backups/ côté CT
./scripts/db/backup.sh

# + rapatrie le fichier dans ./backups/ en local
./scripts/db/backup.sh --download

# Avec un label dans le nom (ex: avant un déploiement risqué)
./scripts/db/backup.sh --label pre-migration-090
```

Format du nom : `agflow-YYYYMMDD-HHMMSS[-label].sql.gz` (timestamp UTC).

Le dump est créé avec `pg_dump --clean --if-exists --no-owner --no-privileges`,
donc rejouable sur n'importe quelle base Postgres compatible sans toucher aux
ownerships.

## Restore

```bash
# Depuis un fichier déjà présent côté CT
./scripts/db/restore.sh agflow-20260502-153012.sql.gz

# Depuis un fichier local (l'upload puis restaure)
./scripts/db/restore.sh ./backups/agflow-20260502-153012.sql.gz --upload
```

⚠️ **Le restore est destructif** : toutes les tables existantes sont DROP
puis recréées (le dump contient `--clean --if-exists`). Le script :

1. Stop le backend (libère les connexions actives qui bloqueraient le DROP)
2. Pipe le `gunzip` dans `psql` avec `ON_ERROR_STOP=1`
3. Restart le backend

Une confirmation explicite (`yes`) est demandée avant de toucher à la base.

## Lister les backups

```bash
ssh pve "pct exec 201 -- ls -lht /root/agflow.docker/backups"
```

## Rétention

Aucune purge automatique. Si tu veux limiter, ajoute un cron côté CT :

```bash
# Garde les 30 derniers, supprime le reste
ls -t /root/agflow.docker/backups/agflow-*.sql.gz | tail -n +31 | xargs -r rm
```

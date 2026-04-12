-- 020_seed_new_standard_files
--
-- Module 1 spec (home.md §94-99 "Paramètres du Dockerfile" and §101-103
-- "Fichier run.cmd.md") requires two additional standard files in every
-- dockerfile directory:
--
--   * run.cmd.md     — docker run command documentation (seeded empty)
--   * Dockerfile.json — default parameters with env-var templating
--
-- This migration backfills existing dockerfiles that predate the expanded
-- STANDARD_FILES set. New dockerfiles get these files via
-- dockerfile_files_service.seed_standard_files().

INSERT INTO dockerfile_files (dockerfile_id, path, content)
SELECT d.id, 'run.cmd.md', '# Commande de lancement

Exemple de lancement direct via `docker run`. Au runtime, l''orchestrateur
agflow construit cette commande à partir de la composition de l''agent
(Module 4) et des paramètres déclarés dans `Dockerfile.json`.

```bash
docker run -it --rm \
    --name agent-<slug> \
    --network bridge \
    --init \
    --stop-signal SIGTERM \
    --stop-timeout 30 \
    -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    -v "${WORKSPACE_PATH:-./workspace}:/app/workspace" \
    -v "./config:/app/config:ro" \
    -v "./skills:/app/skills:ro" \
    -v "./output:/app/output" \
    -w /app \
    --memory 2g \
    --cpus 1.5 \
    agflow-<slug>:<hash>
```

## Mount points normalisés

| Chemin container | Rôle |
|---|---|
| `/app/workspace` | Code source et fichiers du projet |
| `/app/config` | Configuration compilée (prompt, MCP, mission) — lecture seule |
| `/app/skills` | Fichiers SKILL.md injectés depuis le catalogue — lecture seule |
| `/app/output` | Résultats produits par l''agent |
'
FROM dockerfiles d
WHERE NOT EXISTS (
    SELECT 1 FROM dockerfile_files f
    WHERE f.dockerfile_id = d.id AND f.path = 'run.cmd.md'
);

INSERT INTO dockerfile_files (dockerfile_id, path, content)
SELECT d.id, 'Dockerfile.json', '{
  "Arguments": {
    "API_KEY_NAME": "ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}",
    "OPENAI_API_KEY": "${OPENAI_API_KEY}",
    "WORKSPACE_PATH": "${WORKSPACE_PATH:-./workspace}"
  }
}
'
FROM dockerfiles d
WHERE NOT EXISTS (
    SELECT 1 FROM dockerfile_files f
    WHERE f.dockerfile_id = d.id AND f.path = 'Dockerfile.json'
);

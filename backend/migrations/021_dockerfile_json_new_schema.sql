-- 021_dockerfile_json_new_schema
--
-- Replaces the content of Dockerfile.json files that still follow the flat
-- {"Arguments": {...}} shape with the new nested schema:
--
--   {
--     "docker":  { Container, Network, Runtime, Resources, Environments, Mounts },
--     "Params":  { <template variables> }
--   }
--
-- Only rows matching the legacy shape (top-level "Arguments" key, no "docker"
-- key) are rewritten, so this migration is idempotent and safe to re-run.

UPDATE dockerfile_files
SET content = '{
  "docker": {
    "Container": {
      "Name": "agent-{slug}-{id}",
      "Image": "agflow-{slug}:{hash}"
    },
    "Network": {
      "Mode": "bridge"
    },
    "Runtime": {
      "Init": true,
      "StopSignal": "SIGTERM",
      "StopTimeout": 30,
      "WorkingDir": "/app"
    },
    "Resources": {
      "Memory": "2g",
      "Cpus": "1.5"
    },
    "Environments": {
      "ANTHROPIC_API_KEY": "{API_KEY_NAME}"
    },
    "Mounts": [
      { "source": "{WORKSPACE_PATH}", "target": "/app/workspace", "readonly": false },
      { "source": "./config",         "target": "/app/config",    "readonly": true  },
      { "source": "./skills",         "target": "/app/skills",    "readonly": true  },
      { "source": "./output",         "target": "/app/output",    "readonly": false }
    ]
  },
  "Params": {
    "API_KEY_NAME":   "ANTHROPIC_API_KEY",
    "WORKSPACE_PATH": "${WORKSPACE_PATH:-./workspace}"
  }
}
',
    updated_at = NOW()
WHERE path = 'Dockerfile.json'
  AND content::jsonb ? 'Arguments'
  AND NOT (content::jsonb ? 'docker');

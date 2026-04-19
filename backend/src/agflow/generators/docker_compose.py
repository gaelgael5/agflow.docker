"""Docker Compose generator.

Produces docker-compose.yml + .env + README.md from a product recipe.
"""
from __future__ import annotations

import re
from typing import Any

from agflow.generators.base import GeneratedArtifact


class DockerComposeGenerator:
    name = "docker_compose"

    def generate(
        self,
        recipe: dict[str, Any],
        instance_name: str,
        resolved_secrets: dict[str, str],
        resolved_variables: dict[str, str],
        options: dict[str, Any] | None = None,
    ) -> list[GeneratedArtifact]:
        services = recipe.get("services", [])
        if not services:
            # config_only product — no compose needed
            return [self._readme(recipe, instance_name, resolved_variables, resolved_secrets)]

        compose = self._compose(recipe, instance_name, services, resolved_variables)
        env = self._env(services, resolved_secrets, resolved_variables)
        readme = self._readme(recipe, instance_name, resolved_variables, resolved_secrets)

        return [compose, env, readme]

    def _resolve_template(self, text: str, variables: dict[str, str]) -> str:
        """Resolve {{ variable }} patterns."""
        def replacer(m: re.Match[str]) -> str:
            key = m.group(1).strip()
            # Handle services.X.host → container name
            if key.startswith("services.") and key.endswith(".host"):
                svc_id = key.split(".")[1]
                return svc_id
            return variables.get(key, m.group(0))
        return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replacer, text)

    def _compose(
        self,
        recipe: dict[str, Any],
        instance_name: str,
        services: list[dict[str, Any]],
        variables: dict[str, str],
    ) -> GeneratedArtifact:
        lines = [f"# Generated for {instance_name}", f"# Product: {recipe.get('display_name', recipe['id'])}", ""]
        lines.append("services:")

        for svc in services:
            svc_name = f"{instance_name}-{svc['id']}"
            image = svc.get("image", "")
            lines.append(f"  {svc_name}:")
            lines.append(f"    image: {image}")
            lines.append(f"    container_name: {svc_name}")

            # Ports
            ports = svc.get("ports", [])
            if ports:
                lines.append("    ports:")
                for p in ports:
                    lines.append(f'      - "{p}:{p}"')

            # Env
            env_template = svc.get("env_template", {})
            if env_template:
                lines.append("    environment:")
                for k, v in env_template.items():
                    resolved = self._resolve_template(str(v), variables)
                    lines.append(f"      {k}: {resolved}")

            # Volumes
            volumes = svc.get("volumes", [])
            if volumes:
                lines.append("    volumes:")
                for vol in volumes:
                    lines.append(f"      - {vol['name']}:{vol['mount']}")

            # Healthcheck
            hc = svc.get("healthcheck")
            if hc and hc.get("type") == "http":
                lines.append("    healthcheck:")
                lines.append(f"      test: ['CMD', 'wget', '-q', '--spider', 'http://localhost:{hc['port']}{hc['path']}']")
                lines.append("      interval: 30s")
                lines.append("      timeout: 10s")
                lines.append("      retries: 3")

            # Dependencies
            deps = svc.get("requires_services", [])
            if deps:
                lines.append("    depends_on:")
                for dep in deps:
                    lines.append(f"      {instance_name}-{dep}:")
                    lines.append("        condition: service_started")

            # Network
            lines.append("    networks:")
            lines.append("      - agflow")

            lines.append("")

        # Volumes
        all_volumes = []
        for svc in services:
            for vol in svc.get("volumes", []):
                all_volumes.append(vol["name"])
        if all_volumes:
            lines.append("volumes:")
            for v in all_volumes:
                lines.append(f"  {v}:")
            lines.append("")

        # Network
        lines.append("networks:")
        lines.append("  agflow:")
        lines.append("    external: true")
        lines.append("")

        return GeneratedArtifact(
            filename="docker-compose.yml",
            content="\n".join(lines),
            artifact_type="compose",
        )

    def _env(
        self,
        services: list[dict[str, Any]],
        secrets: dict[str, str],
        variables: dict[str, str],
    ) -> GeneratedArtifact:
        lines = ["# Generated environment variables", ""]

        # Collect all ${VAR} references from env_templates
        seen: set[str] = set()
        for svc in services:
            for v in svc.get("env_template", {}).values():
                for m in re.finditer(r"\$\{(\w+)\}", str(v)):
                    var = m.group(1)
                    if var not in seen:
                        seen.add(var)
                        value = secrets.get(var, "")
                        lines.append(f"{var}={value}")

        return GeneratedArtifact(
            filename=".env",
            content="\n".join(lines) + "\n",
            artifact_type="env",
        )

    def _readme(
        self,
        recipe: dict[str, Any],
        instance_name: str,
        variables: dict[str, str],
        secrets: dict[str, str],
    ) -> GeneratedArtifact:
        lines = [
            f"# {recipe.get('display_name', recipe['id'])} — {instance_name}",
            "",
            f"**Produit** : {recipe.get('display_name', '')}",
            f"**Description** : {recipe.get('description', '')}",
            "",
        ]

        if variables:
            lines.append("## Variables")
            lines.append("")
            for k, v in variables.items():
                lines.append(f"- `{k}` = `{v}`")
            lines.append("")

        secrets_req = recipe.get("secrets_required", [])
        if secrets_req:
            lines.append("## Secrets requis")
            lines.append("")
            for s in secrets_req:
                name = s.get("name", "")
                status = "✅ configuré" if secrets.get(name) else "❌ à configurer"
                lines.append(f"- `{name}` — {s.get('description', '')} [{status}]")
            lines.append("")

        services = recipe.get("services", [])
        if services:
            lines.append("## Déploiement")
            lines.append("")
            lines.append("```bash")
            lines.append("# Copier les fichiers sur le serveur")
            lines.append(f"scp docker-compose.yml .env user@server:~/{instance_name}/")
            lines.append(f"ssh user@server 'cd ~/{instance_name} && docker compose up -d'")
            lines.append("```")
            lines.append("")
        else:
            lines.append("## Configuration (SaaS)")
            lines.append("")
            lines.append("Ce produit est un service SaaS. Aucun déploiement nécessaire.")
            lines.append("Configurez les secrets et activez l'instance dans l'UI.")
            lines.append("")

        return GeneratedArtifact(
            filename="README.md",
            content="\n".join(lines),
            artifact_type="readme",
        )

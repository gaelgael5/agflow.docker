"""Manual generator — produces only a README with all details."""
from __future__ import annotations

from typing import Any

from agflow.generators.base import GeneratedArtifact


class ManualGenerator:
    name = "manual"

    def generate(
        self,
        recipe: dict[str, Any],
        instance_name: str,
        resolved_secrets: dict[str, str],
        resolved_variables: dict[str, str],
        options: dict[str, Any] | None = None,
    ) -> list[GeneratedArtifact]:
        lines = [
            f"# {recipe.get('display_name', recipe['id'])} — Manuel d'installation",
            "",
            f"**Instance** : {instance_name}",
            f"**Description** : {recipe.get('description', '')}",
            "",
        ]

        # Variables
        if resolved_variables:
            lines.append("## Variables de configuration")
            lines.append("")
            lines.append("| Variable | Valeur |")
            lines.append("|----------|--------|")
            for k, v in resolved_variables.items():
                lines.append(f"| `{k}` | `{v}` |")
            lines.append("")

        # Secrets
        secrets_req = recipe.get("secrets_required", [])
        if secrets_req:
            lines.append("## Secrets requis")
            lines.append("")
            lines.append("| Secret | Description | Statut |")
            lines.append("|--------|-------------|--------|")
            for s in secrets_req:
                name = s.get("name", "")
                desc = s.get("description", "")
                status = "✅" if resolved_secrets.get(name) else "❌"
                lines.append(f"| `{name}` | {desc} | {status} |")
            lines.append("")

        # Services
        services = recipe.get("services", [])
        if services:
            lines.append("## Services")
            lines.append("")
            for svc in services:
                lines.append(f"### {svc['id']}")
                lines.append("")
                lines.append(f"- **Image** : `{svc.get('image', '')}`")
                ports = svc.get("ports", [])
                if ports:
                    lines.append(f"- **Ports** : {', '.join(str(p) for p in ports)}")
                deps = svc.get("requires_services", [])
                if deps:
                    lines.append(f"- **Dépendances** : {', '.join(deps)}")
                env = svc.get("env_template", {})
                if env:
                    lines.append("- **Variables d'environnement** :")
                    for k, v in env.items():
                        lines.append(f"  - `{k}` = `{v}`")
                vols = svc.get("volumes", [])
                if vols:
                    lines.append("- **Volumes** :")
                    for vol in vols:
                        lines.append(f"  - `{vol['name']}` → `{vol['mount']}`")
                lines.append("")
        else:
            lines.append("## Configuration SaaS")
            lines.append("")
            lines.append("Ce produit est un service SaaS. Configurez les secrets et activez l'instance.")
            lines.append("")

        return [GeneratedArtifact(
            filename="README.md",
            content="\n".join(lines),
            artifact_type="readme",
        )]

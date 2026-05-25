# backend/src/agflow/services/placeholder_parsers.py
"""Parsers purs des placeholders d'input. Aucun I/O — testables sans mocks.

Reconnaît 4 syntaxes :
- ${env-machine://<machine>:<VAR>}  — variable d'env d'une machine distante
- ${vault://api:<NAME>}              — secret Harpocrate
- ${env://<NAME>}                    — variable globale platform_secrets
- ${VAR} / $VAR                      — variable du .env de déploiement (MAJUSCULES)

Le pattern UNKNOWN_BRACE_RE sert à détecter les ${...} résiduels qui ne
matchent aucun des 4 patterns ci-dessus (erreur de saisie probable).
"""

from __future__ import annotations

import re

ENV_MACHINE_RE = re.compile(r"\$\{env-machine://([^:}]+):([^}]+)\}")
VAULT_REF_RE = re.compile(r"\$\{vault://[^:}]+:([^}]+)\}")
ENV_REF_RE = re.compile(r"\$\{env://([^}]+)\}")
SIMPLE_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]*)")
# Détecte tout ${...} restant après les 4 substitutions ci-dessus.
UNKNOWN_BRACE_RE = re.compile(r"\$\{([^}]+)\}")


def parse_env_machine_ref(value: str | None) -> tuple[str, str] | None:
    """Retourne (machine_name, var_name) si la valeur est entièrement une ref env-machine, sinon None."""
    if not value:
        return None
    m = re.fullmatch(
        r"\s*\$\{env-machine://([^:}]+):([^}]+)\}\s*",
        value,
    )
    return (m.group(1), m.group(2)) if m else None


def parse_env_text(env_text: str | None) -> dict[str, str]:
    """Parse un .env text vers dict[name, value]. Ignore blanks et commentaires."""
    result: dict[str, str] = {}
    for line in (env_text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip()
    return result

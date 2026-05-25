# backend/src/agflow/services/input_resolver.py
"""Résolveur unifié des placeholders d'input pour les group_scripts.

Orchestre les 4 syntaxes (env-machine://, vault://, env://, ${VAR}) dans
un ordre figé. Politique fail-fast à l'exécution ; variante collect-all
pour le check de pré-déploiement.

Voir docs/superpowers/specs/2026-05-25-env-machine-resolver-design.md
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import structlog

from agflow.services import infra_env_vars_service, infra_machines_service
from agflow.services.placeholder_parsers import (
    ENV_MACHINE_RE,
    ENV_REF_RE,
    SIMPLE_VAR_RE,
    UNKNOWN_BRACE_RE,
    VAULT_REF_RE,
    parse_env_text,
)

_log = structlog.get_logger(__name__)

UnresolvedKind = Literal[
    "value_empty",
    "var_not_in_env",
    "platform_secret_missing",
    "machine_not_found",
    "env_machine_var_not_found",
    "env_machine_var_empty",
    "unknown_ref",
]


class UnresolvedPlaceholderError(Exception):
    """Levée quand une référence dans un input_value ne peut être résolue.

    L'objet porte assez d'information pour générer un message humain
    précis et pour catégoriser l'erreur dans la réponse API du check.
    """

    def __init__(
        self,
        *,
        kind: UnresolvedKind,
        ref: str,
        detail: str,
        var_name: str | None = None,
    ) -> None:
        self.kind = kind
        self.ref = ref
        self.detail = detail
        self.var_name = var_name
        var_part = f", var={var_name}" if var_name is not None else ""
        ref_part = f", ref={ref}" if ref else ""
        super().__init__(f"{kind}: {detail}{var_part}{ref_part}")


async def resolve_input_values(
    input_values: dict[str, str],
    *,
    target_machine_id: UUID,
    env_text: str,
    platform_secrets_map: dict[str, str],
) -> dict[str, str]:
    """Resout les input_values d'un group_script (fail-fast)."""
    env_map = parse_env_text(env_text)
    env_machine_cache: dict[str, dict[str, str]] = {}

    resolved: dict[str, str] = {}
    for var_name, raw in input_values.items():
        resolved[var_name] = await _resolve_single(
            var_name=var_name,
            raw=raw,
            env_map=env_map,
            platform_secrets_map=platform_secrets_map,
            env_machine_cache=env_machine_cache,
        )
    return resolved


def _detect_unknown_refs(value: str, var_name: str) -> None:
    """Detecte les ${...} qui ne matchent aucun des 4 patterns connus. Leve si trouve."""
    for m in UNKNOWN_BRACE_RE.finditer(value):
        full = m.group(0)
        if (
            ENV_MACHINE_RE.fullmatch(full)
            or VAULT_REF_RE.fullmatch(full)
            or ENV_REF_RE.fullmatch(full)
            or SIMPLE_VAR_RE.fullmatch(full)
        ):
            continue
        raise UnresolvedPlaceholderError(
            kind="unknown_ref",
            ref=full,
            detail=f"reference non reconnue '{m.group(1)}' dans '{var_name}'",
            var_name=var_name,
        )


async def _resolve_single(
    *,
    var_name: str,
    raw: str,
    env_map: dict[str, str],
    platform_secrets_map: dict[str, str],
    env_machine_cache: dict[str, dict[str, str]],
) -> str:
    value = raw or ""
    if not value.strip():
        raise UnresolvedPlaceholderError(
            kind="value_empty",
            ref="",
            detail=f"valeur vide pour '{var_name}'",
            var_name=var_name,
        )

    # Detecter d'emblee les ${...} non reconnus dans la valeur d'origine
    _detect_unknown_refs(value, var_name)

    # Etape 1 — env-machine:// avec sentinelles pour eviter la recursion.
    # Les valeurs resolues depuis env-machine sont substituees via des jetons
    # opaques, et restaurees apres les etapes 2-4 afin que leur contenu
    # ne soit jamais reparse comme placeholder.
    value, env_machine_resolved = await _substitute_env_machine_sentinel(
        value,
        var_name,
        env_machine_cache,
    )

    # Etapes 2-4 — s'appliquent uniquement aux parties NON issues de env-machine
    value = _substitute_vault(value, var_name, platform_secrets_map)
    value = _substitute_env_ref(value, var_name, platform_secrets_map)
    value = _substitute_simple_var(value, var_name, env_map)

    # Restauration des valeurs env-machine (pas de recursion)
    for sentinel, resolved_val in env_machine_resolved.items():
        value = value.replace(sentinel, resolved_val)

    return value


async def _substitute_env_machine_sentinel(
    value: str,
    var_name: str,
    cache: dict[str, dict[str, str]],
) -> tuple[str, dict[str, str]]:
    """Remplace les refs ${env-machine://m:V} par des sentinelles opaques.

    Retourne (valeur_avec_sentinelles, {sentinelle: valeur_resolue}).
    Les sentinelles sont restaurees apres les etapes vault/env/simple-var
    pour eviter toute recursion sur le contenu resolu.
    """
    out = value
    sentinel_map: dict[str, str] = {}

    for idx, m in enumerate(list(ENV_MACHINE_RE.finditer(value))):
        machine_name, ref_var = m.group(1), m.group(2)
        if machine_name not in cache:
            machine = await infra_machines_service.get_by_name(machine_name)
            if machine is None:
                raise UnresolvedPlaceholderError(
                    kind="machine_not_found",
                    ref=m.group(0),
                    detail=f"machine '{machine_name}' inconnue",
                    var_name=var_name,
                )
            cache[machine_name] = await infra_env_vars_service.resolve_for_machine(machine.id)

        env_vars = cache[machine_name]
        if ref_var not in env_vars:
            raise UnresolvedPlaceholderError(
                kind="env_machine_var_not_found",
                ref=m.group(0),
                detail=f"variable '{ref_var}' absente sur la machine '{machine_name}'",
                var_name=var_name,
            )
        if not env_vars[ref_var]:
            raise UnresolvedPlaceholderError(
                kind="env_machine_var_empty",
                ref=m.group(0),
                detail=f"variable '{ref_var}' vide sur la machine '{machine_name}'",
                var_name=var_name,
            )
        sentinel = f"\x00ENV_MACHINE_{idx}\x00"
        sentinel_map[sentinel] = env_vars[ref_var]
        out = out.replace(m.group(0), sentinel, 1)

    return out, sentinel_map


def _substitute_vault(value: str, var_name: str, secrets: dict[str, str]) -> str:
    out = value
    for m in list(VAULT_REF_RE.finditer(value)):
        name = m.group(1)
        secret = secrets.get(name)
        if not secret:
            raise UnresolvedPlaceholderError(
                kind="platform_secret_missing",
                ref=m.group(0),
                detail=f"secret '{name}' introuvable dans le coffre",
                var_name=var_name,
            )
        out = out.replace(m.group(0), secret)
    return out


def _substitute_env_ref(value: str, var_name: str, secrets: dict[str, str]) -> str:
    out = value
    for m in list(ENV_REF_RE.finditer(value)):
        name = m.group(1)
        secret = secrets.get(name)
        if not secret:
            raise UnresolvedPlaceholderError(
                kind="platform_secret_missing",
                ref=m.group(0),
                detail=f"variable globale '{name}' introuvable",
                var_name=var_name,
            )
        out = out.replace(m.group(0), secret)
    return out


def _substitute_simple_var(value: str, var_name: str, env_map: dict[str, str]) -> str:
    out = value
    for m in list(SIMPLE_VAR_RE.finditer(value)):
        name = m.group(1) or m.group(2)
        if name is None:
            continue
        env_val = env_map.get(name)
        if not env_val:
            raise UnresolvedPlaceholderError(
                kind="var_not_in_env",
                ref=m.group(0),
                detail=f"variable '{name}' introuvable dans le .env",
                var_name=var_name,
            )
        out = out.replace(m.group(0), env_val)
    return out

# backend/src/agflow/services/input_resolver.py
"""Résolveur unifié des placeholders d'input pour les group_scripts.

Orchestre les 4 syntaxes (env-machine://, vault://, env://, ${VAR}) dans
un ordre figé. Politique fail-fast à l'exécution ; variante collect-all
pour le check de pré-déploiement.

Voir docs/superpowers/specs/2026-05-25-env-machine-resolver-design.md
"""

from __future__ import annotations

from typing import Literal

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

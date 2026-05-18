"""Rendering Jinja récursif pour les jsonb workflow.

Parcourt récursivement les valeurs string d'un dict/list et applique Jinja2
dessus avec SandboxedEnvironment (défense en profondeur : pas d'accès aux
attributs spéciaux Python même si l'admin déclare du Jinja malicieux).

Variables non-string (int, bool, None) passent à travers sans modification.
"""
from __future__ import annotations

from typing import Any

from jinja2 import StrictUndefined
from jinja2.exceptions import SecurityError, TemplateError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment


class JinjaRenderError(Exception):
    """Erreur de rendu Jinja (var manquante, sandbox violation, syntax)."""


_env = SandboxedEnvironment(
    undefined=StrictUndefined,
    autoescape=False,  # JSON values, pas du HTML
)


def render_jsonb_jinja(value: Any, context: dict[str, Any]) -> Any:
    """Render récursif. Strings → Jinja. Dict et list → récursion sur les valeurs.

    Les clés de dict ne sont PAS rendues : on suppose que les clés jsonb sont
    statiques (noms de paramètres figés). Tout autre type (int, bool, None) →
    passthrough sans modification.
    """
    if isinstance(value, str):
        try:
            return _env.from_string(value).render(**context)
        except UndefinedError as exc:
            raise JinjaRenderError(f"jinja undefined var: {exc}") from exc
        except SecurityError as exc:
            raise JinjaRenderError(f"jinja sandbox violation: {exc}") from exc
        except TemplateError as exc:
            raise JinjaRenderError(f"jinja template error: {exc}") from exc
    if isinstance(value, dict):
        return {k: render_jsonb_jinja(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_jsonb_jinja(v, context) for v in value]
    return value

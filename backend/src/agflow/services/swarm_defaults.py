"""Defaults Swarm pour les blocs `deploy:` injectes dans les services rendus.

Resolution : recipe.services[*].deploy (optionnel) deep-merge sur _DEFAULT_DEPLOY.
Le resultat est passe verbatim au template Jinja qui le dumpe via le filtre to_yaml.
"""

from __future__ import annotations

import copy


def deep_merge(base: dict, override: dict | None) -> dict:
    """Deep-merge: override prend priorite, dicts imbriques sont mergees
    recursivement, listes sont remplacees (pas concatenees).

    Aucune mutation des inputs. Retourne toujours un nouveau dict.
    """
    result = copy.deepcopy(base)
    if not override:
        return result
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
    return result

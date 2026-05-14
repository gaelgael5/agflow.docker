"""Modèles de données du SDK Git Sync.

Utilise `dataclasses` + `enum.Enum` (stdlib) pour rester autonome : le SDK
ne doit pas tirer Pydantic dans son scope minimal (il sera copié tel quel
dans d'autres modules qui peuvent ou non utiliser Pydantic).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import StrEnum

from sdk.git_sync.exceptions import DependencyResolveError


class AuthMode(StrEnum):
    """Modes d'authentification supportés pour le repo Git distant."""

    SSH_KEY = "ssh_key"
    PAT_HTTPS = "pat_https"
    BASIC_HTTPS = "basic_https"


@dataclass(frozen=True)
class TableRef:
    """Référence à une table PostgreSQL (schema + nom)."""

    schema: str
    table: str

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.table}"

    @property
    def csv_name(self) -> str:
        return f"{self.schema}.{self.table}.csv"

    @property
    def tmp_name(self) -> str:
        # Convention spec : `tmp_<schema>_<table>` — le `.` du full_name
        # devient `_` pour rester un identifiant SQL valide.
        return f"tmp_{self.schema}_{self.table}"


@dataclass
class GitConfig:
    """Configuration d'un repo Git pour export/import.

    `auth_secret_ref` peut être :
      - une référence Harpocrate `${vault://path}` résolue lazy par le SDK
      - une valeur littérale (uniquement pour dev/test — jamais en prod)

    `excluded_columns` est un mapping `"<schema>.<table>" -> [col, ...]`.
    Les colonnes `GENERATED ALWAYS` et identity sont toujours exclues
    automatiquement, indépendamment de ce mapping.
    """

    repo_url: str
    auth_mode: AuthMode
    auth_secret_ref: str
    module_name: str
    commit_author_name: str
    commit_author_email: str
    branch: str = "main"
    target_commit: str | None = None
    excluded_columns: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class DependencyGraph:
    """Graphe de dépendances FK entre tables PostgreSQL.

    `edges` est une liste de paires `(dependent, depends_on)` : le premier
    élément référence le second (FK). Le tri topologique place
    `depends_on` avant `dependent` — donc en partant des feuilles (tables
    sans dépendance sortante) vers les racines.
    """

    tables: list[TableRef]
    edges: list[tuple[TableRef, TableRef]]

    @property
    def ordered(self) -> list[TableRef]:
        """Tri topologique stable (Kahn) : ordre d'insertion en base.

        Stable au sens où des nodes de même rang sont sortis dans leur
        ordre d'apparition dans `self.tables`. Lance `DependencyResolveError`
        si un cycle est détecté.
        """
        if not self.tables:
            return []

        by_name = {t.full_name: t for t in self.tables}
        in_degree: dict[str, int] = {t.full_name: 0 for t in self.tables}
        successors: dict[str, list[str]] = defaultdict(list)

        for dependent, depends_on in self.edges:
            # On ne touche pas aux compteurs si une des deux tables n'est
            # pas dans la liste — les edges externes sont ignorés.
            if dependent.full_name not in in_degree:
                continue
            if depends_on.full_name not in in_degree:
                continue
            in_degree[dependent.full_name] += 1
            successors[depends_on.full_name].append(dependent.full_name)

        # File FIFO peuplée dans l'ordre d'apparition pour préserver la
        # stabilité quand plusieurs nodes ont in_degree == 0.
        queue: deque[str] = deque(
            t.full_name for t in self.tables if in_degree[t.full_name] == 0
        )
        result: list[TableRef] = []

        while queue:
            name = queue.popleft()
            result.append(by_name[name])
            # Successeurs traités dans l'ordre déterministe pour stabilité.
            for succ in successors[name]:
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if len(result) != len(self.tables):
            unresolved = [
                name for name, deg in in_degree.items() if deg > 0
            ]
            raise DependencyResolveError(
                f"cycle détecté dans le graphe de dépendances : {unresolved}"
            )

        return result

    @property
    def ordered_reverse(self) -> list[TableRef]:
        """Ordre inverse — pour suppressions et DROP."""
        return list(reversed(self.ordered))


@dataclass(frozen=True)
class TablePreview:
    table: TableRef
    to_insert: int
    to_update: int
    to_delete: int


@dataclass(frozen=True)
class ImportPreview:
    tables: list[TablePreview]


@dataclass
class SyncResult:
    success: bool
    commit_sha: str | None
    tables_exported: list[TableRef]
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    success: bool
    tables_processed: list[TableRef]
    rows_inserted: dict[str, int] = field(default_factory=dict)
    rows_updated: dict[str, int] = field(default_factory=dict)
    rows_deleted: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

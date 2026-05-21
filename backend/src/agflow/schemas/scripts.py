from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ── Script (fichier .sh en BDD) ──────────────────────────

InputStatus = Literal["keep", "clean", "replace"]


class ScriptInputVariable(BaseModel):
    name: str
    description: str = ""
    default: str = ""


class ScriptOutputVariable(BaseModel):
    """Variable de sortie déclarée par un script.

    À l'exécution, le script doit produire en dernière ligne de son stdout
    un JSON contenant la valeur attendue, accessible via `path` (dot-notation).
    Exemple : `path="result.hostname"` extrait `parsed["result"]["hostname"]`.
    """
    name: str
    description: str = ""
    path: str = ""


class ScriptRow(BaseModel):
    id: UUID
    name: str
    description: str
    content: str
    execute_on_types_named: UUID | None = None
    execute_on_types_named_name: str | None = None
    input_variables: list[ScriptInputVariable] = []
    output_variables: list[ScriptOutputVariable] = []
    created_at: datetime
    updated_at: datetime


class ScriptSummary(BaseModel):
    """Script without the full content (for listing)."""
    id: UUID
    name: str
    description: str
    execute_on_types_named: UUID | None = None
    execute_on_types_named_name: str | None = None
    input_variables: list[ScriptInputVariable] = []
    output_variables: list[ScriptOutputVariable] = []
    created_at: datetime
    updated_at: datetime


class ScriptCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    content: str = ""
    execute_on_types_named: UUID | None = None
    input_variables: list[ScriptInputVariable] = Field(default_factory=list)
    output_variables: list[ScriptOutputVariable] = Field(default_factory=list)


class ScriptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    execute_on_types_named: UUID | None = None
    input_variables: list[ScriptInputVariable] | None = None
    output_variables: list[ScriptOutputVariable] | None = None


# ── Group → Script reference ─────────────────────────────

Timing = Literal["before", "after"]


TriggerOp = Literal["equals", "not_equals", "is_null"]


class TriggerRule(BaseModel):
    variable: str
    op: TriggerOp
    value: str = ""


TargetKind = Literal["fixed_machine", "deployment_host"]


class GroupScriptRow(BaseModel):
    id: UUID
    group_id: UUID
    group_name: str = ""
    script_id: UUID
    script_name: str
    target_kind: TargetKind = "fixed_machine"
    machine_id: UUID | None = None
    machine_name: str = ""
    timing: Timing
    position: int
    env_mapping: dict[str, str]
    input_values: dict[str, str]
    input_statuses: dict[str, InputStatus] = {}
    trigger_rules: list[TriggerRule] = []
    created_at: datetime
    updated_at: datetime


class GroupScriptCreate(BaseModel):
    script_id: UUID
    target_kind: TargetKind = "fixed_machine"
    machine_id: UUID | None = None
    timing: Timing
    position: int = 0
    env_mapping: dict[str, str] = Field(default_factory=dict)
    input_values: dict[str, str] = Field(default_factory=dict)
    input_statuses: dict[str, InputStatus] = Field(default_factory=dict)
    trigger_rules: list[TriggerRule] = Field(default_factory=list)


class GroupScriptUpdate(BaseModel):
    script_id: UUID | None = None
    target_kind: TargetKind | None = None
    machine_id: UUID | None = None
    timing: Timing | None = None
    position: int | None = None
    env_mapping: dict[str, str] | None = None
    input_values: dict[str, str] | None = None
    input_statuses: dict[str, InputStatus] | None = None
    trigger_rules: list[TriggerRule] | None = None

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { useDockerfiles } from "@/hooks/useDockerfiles";
import { useRoles } from "@/hooks/useRoles";
import { useMCPCatalog, useSkillsCatalog } from "@/hooks/useCatalogs";
import {
  useAgent,
  useAgents,
  useConfigPreview,
} from "@/hooks/useAgents";
import type {
  AgentCreatePayload,
  AgentMCPBinding,
  AgentSkillBinding,
  ConfigPreview,
  NetworkMode,
} from "@/lib/agentsApi";

type EnvEntry = { key: string; value: string };

interface FormState {
  slug: string;
  display_name: string;
  description: string;
  dockerfile_id: string;
  role_id: string;
  env_entries: EnvEntry[];
  timeout_seconds: number;
  workspace_path: string;
  network_mode: NetworkMode;
  graceful_shutdown_secs: number;
  force_kill_delay_secs: number;
  mcp_bindings: AgentMCPBinding[];
  skill_bindings: AgentSkillBinding[];
}

const EMPTY_FORM: FormState = {
  slug: "",
  display_name: "",
  description: "",
  dockerfile_id: "",
  role_id: "",
  env_entries: [],
  timeout_seconds: 3600,
  workspace_path: "/workspace",
  network_mode: "bridge",
  graceful_shutdown_secs: 30,
  force_kill_delay_secs: 10,
  mcp_bindings: [],
  skill_bindings: [],
};

function envObjectToEntries(obj: Record<string, string>): EnvEntry[] {
  return Object.entries(obj).map(([key, value]) => ({ key, value }));
}

function envEntriesToObject(entries: EnvEntry[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of entries) {
    if (e.key.trim()) out[e.key.trim()] = e.value;
  }
  return out;
}

export function AgentEditorPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === "new";

  const { agent, isLoading: agentLoading, updateMutation } = useAgent(
    isNew ? undefined : id,
  );
  const { createMutation, deleteMutation, duplicateMutation } = useAgents();
  const { dockerfiles } = useDockerfiles();
  const { roles } = useRoles();
  const { mcps } = useMCPCatalog();
  const { skills } = useSkillsCatalog();
  const previewQuery = useConfigPreview(isNew ? undefined : id);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [preview, setPreview] = useState<ConfigPreview | null>(null);

  useEffect(() => {
    if (!isNew && agent) {
      setForm({
        slug: agent.slug,
        display_name: agent.display_name,
        description: agent.description,
        dockerfile_id: agent.dockerfile_id,
        role_id: agent.role_id,
        env_entries: envObjectToEntries(agent.env_vars),
        timeout_seconds: agent.timeout_seconds,
        workspace_path: agent.workspace_path,
        network_mode: agent.network_mode,
        graceful_shutdown_secs: agent.graceful_shutdown_secs,
        force_kill_delay_secs: agent.force_kill_delay_secs,
        mcp_bindings: agent.mcp_bindings,
        skill_bindings: agent.skill_bindings,
      });
    }
  }, [isNew, agent]);

  const availableMCPs = useMemo(() => mcps ?? [], [mcps]);
  const availableSkills = useMemo(() => skills ?? [], [skills]);

  const mcpName = (mcpId: string): string =>
    availableMCPs.find((m) => m.id === mcpId)?.name ?? mcpId;
  const skillName = (sid: string): string =>
    availableSkills.find((s) => s.id === sid)?.name ?? sid;

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function addEnv() {
    updateField("env_entries", [...form.env_entries, { key: "", value: "" }]);
  }

  function removeEnv(idx: number) {
    updateField(
      "env_entries",
      form.env_entries.filter((_, i) => i !== idx),
    );
  }

  function setEnv(idx: number, field: keyof EnvEntry, value: string) {
    const next = [...form.env_entries];
    const entry = next[idx];
    if (!entry) return;
    next[idx] = { ...entry, [field]: value };
    updateField("env_entries", next);
  }

  function addMCP() {
    const firstAvailable = availableMCPs.find(
      (m) => !form.mcp_bindings.some((b) => b.mcp_server_id === m.id),
    );
    if (!firstAvailable) return;
    updateField("mcp_bindings", [
      ...form.mcp_bindings,
      {
        mcp_server_id: firstAvailable.id,
        parameters_override: {},
        position: form.mcp_bindings.length,
      },
    ]);
  }

  function removeMCP(idx: number) {
    updateField(
      "mcp_bindings",
      form.mcp_bindings.filter((_, i) => i !== idx),
    );
  }

  function setMCPOverride(idx: number, raw: string) {
    const next = [...form.mcp_bindings];
    const entry = next[idx];
    if (!entry) return;
    try {
      next[idx] = { ...entry, parameters_override: JSON.parse(raw || "{}") };
      updateField("mcp_bindings", next);
      setError(null);
    } catch {
      setError(`Invalid JSON in MCP #${idx + 1} override`);
    }
  }

  function addSkill() {
    const firstAvailable = availableSkills.find(
      (s) => !form.skill_bindings.some((b) => b.skill_id === s.id),
    );
    if (!firstAvailable) return;
    updateField("skill_bindings", [
      ...form.skill_bindings,
      { skill_id: firstAvailable.id, position: form.skill_bindings.length },
    ]);
  }

  function removeSkill(idx: number) {
    updateField(
      "skill_bindings",
      form.skill_bindings.filter((_, i) => i !== idx),
    );
  }

  function buildPayload(): AgentCreatePayload {
    return {
      slug: form.slug,
      display_name: form.display_name,
      description: form.description,
      dockerfile_id: form.dockerfile_id,
      role_id: form.role_id,
      env_vars: envEntriesToObject(form.env_entries),
      timeout_seconds: form.timeout_seconds,
      workspace_path: form.workspace_path,
      network_mode: form.network_mode,
      graceful_shutdown_secs: form.graceful_shutdown_secs,
      force_kill_delay_secs: form.force_kill_delay_secs,
      mcp_bindings: form.mcp_bindings,
      skill_bindings: form.skill_bindings,
    };
  }

  async function handleSave() {
    setError(null);
    try {
      if (isNew) {
        const created = await createMutation.mutateAsync(buildPayload());
        navigate(`/agents/${created.id}`);
      } else {
        const { slug: _slug, ...updatePayload } = buildPayload();
        void _slug;
        await updateMutation.mutateAsync(updatePayload);
      }
    } catch (e) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 409) {
        setError(t("agent_editor.error_duplicate_slug"));
      } else if (err.response?.status === 400) {
        setError(t("agent_editor.error_invalid_reference"));
      } else {
        setError(err.response?.data?.detail ?? t("agent_editor.error_generic"));
      }
    }
  }

  async function handlePreview() {
    if (isNew || !id) return;
    const result = await previewQuery.refetch();
    if (result.data) {
      setPreview(result.data);
      setShowPreview(true);
    }
  }

  async function handleDuplicate() {
    if (isNew || !id) return;
    const slug = window.prompt(t("agents.duplicate_prompt_slug"));
    if (!slug) return;
    const displayName =
      window.prompt(t("agents.duplicate_prompt_name")) ?? slug;
    const copy = await duplicateMutation.mutateAsync({
      id,
      slug,
      displayName,
    });
    navigate(`/agents/${copy.id}`);
  }

  async function handleDelete() {
    if (isNew || !id) return;
    if (!window.confirm(t("agents.confirm_delete", { name: form.display_name })))
      return;
    await deleteMutation.mutateAsync(id);
    navigate("/agents");
  }

  if (!isNew && agentLoading) return <p>{t("secrets.loading")}</p>;

  const title = isNew
    ? t("agent_editor.title_new")
    : t("agent_editor.title_edit", { name: form.display_name });

  return (
    <div style={{ padding: "2rem", maxWidth: 1000 }}>
      <h1>{title}</h1>

      {error && (
        <p role="alert" style={{ color: "red" }}>
          {error}
        </p>
      )}

      <fieldset style={{ marginBottom: "1rem" }}>
        <legend>{t("agent_editor.section_general")}</legend>
        <label>
          {t("agent_editor.slug")}
          <input
            type="text"
            value={form.slug}
            onChange={(e) => updateField("slug", e.target.value)}
            disabled={!isNew}
          />
        </label>
        <label>
          {t("agent_editor.display_name")}
          <input
            type="text"
            value={form.display_name}
            onChange={(e) => updateField("display_name", e.target.value)}
          />
        </label>
        <label>
          {t("agent_editor.description")}
          <textarea
            value={form.description}
            onChange={(e) => updateField("description", e.target.value)}
            rows={2}
          />
        </label>
      </fieldset>

      <fieldset style={{ marginBottom: "1rem" }}>
        <legend>{t("agent_editor.section_dockerfile")}</legend>
        <select
          value={form.dockerfile_id}
          onChange={(e) => updateField("dockerfile_id", e.target.value)}
        >
          <option value="">—</option>
          {(dockerfiles ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.display_name} ({d.id})
            </option>
          ))}
        </select>
      </fieldset>

      <fieldset style={{ marginBottom: "1rem" }}>
        <legend>{t("agent_editor.section_role")}</legend>
        <select
          value={form.role_id}
          onChange={(e) => updateField("role_id", e.target.value)}
        >
          <option value="">—</option>
          {(roles ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {r.display_name} ({r.id})
            </option>
          ))}
        </select>
      </fieldset>

      <fieldset style={{ marginBottom: "1rem" }}>
        <legend>{t("agent_editor.section_mcps")}</legend>
        {form.mcp_bindings.map((b, idx) => (
          <div
            key={`${b.mcp_server_id}-${idx}`}
            style={{
              border: "1px solid #eee",
              padding: "0.5rem",
              marginBottom: "0.5rem",
            }}
          >
            <strong>{mcpName(b.mcp_server_id)}</strong>
            <label style={{ display: "block", marginTop: "0.25rem" }}>
              {t("agent_editor.mcp_override_label")}
              <textarea
                defaultValue={JSON.stringify(b.parameters_override, null, 2)}
                onBlur={(e) => setMCPOverride(idx, e.target.value)}
                rows={3}
                style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
              />
            </label>
            <button type="button" onClick={() => removeMCP(idx)}>
              {t("agent_editor.mcp_remove")}
            </button>
          </div>
        ))}
        <button type="button" onClick={addMCP}>
          {t("agent_editor.mcp_add")}
        </button>
      </fieldset>

      <fieldset style={{ marginBottom: "1rem" }}>
        <legend>{t("agent_editor.section_skills")}</legend>
        {form.skill_bindings.map((b, idx) => (
          <div
            key={`${b.skill_id}-${idx}`}
            style={{ display: "flex", gap: "0.5rem", marginBottom: "0.25rem" }}
          >
            <span>{skillName(b.skill_id)}</span>
            <button type="button" onClick={() => removeSkill(idx)}>
              {t("agent_editor.skill_remove")}
            </button>
          </div>
        ))}
        <button type="button" onClick={addSkill}>
          {t("agent_editor.skill_add")}
        </button>
      </fieldset>

      <fieldset style={{ marginBottom: "1rem" }}>
        <legend>{t("agent_editor.section_env")}</legend>
        {form.env_entries.map((entry, idx) => (
          <div
            key={idx}
            style={{ display: "flex", gap: "0.5rem", marginBottom: "0.25rem" }}
          >
            <input
              type="text"
              placeholder={t("agent_editor.env_key_placeholder")}
              value={entry.key}
              onChange={(e) => setEnv(idx, "key", e.target.value)}
            />
            <input
              type="text"
              placeholder={t("agent_editor.env_value_placeholder")}
              value={entry.value}
              onChange={(e) => setEnv(idx, "value", e.target.value)}
              style={{ flex: 1 }}
            />
            <button type="button" onClick={() => removeEnv(idx)}>
              {t("agent_editor.env_remove")}
            </button>
          </div>
        ))}
        <button type="button" onClick={addEnv}>
          {t("agent_editor.env_add")}
        </button>
      </fieldset>

      <fieldset style={{ marginBottom: "1rem" }}>
        <legend>{t("agent_editor.section_lifecycle")}</legend>
        <label>
          {t("agent_editor.timeout")}
          <input
            type="number"
            value={form.timeout_seconds}
            onChange={(e) =>
              updateField("timeout_seconds", Number(e.target.value))
            }
          />
        </label>
        <label>
          {t("agent_editor.workspace_path")}
          <input
            type="text"
            value={form.workspace_path}
            onChange={(e) => updateField("workspace_path", e.target.value)}
          />
        </label>
        <label>
          {t("agent_editor.network_mode")}
          <select
            value={form.network_mode}
            onChange={(e) =>
              updateField("network_mode", e.target.value as NetworkMode)
            }
          >
            <option value="bridge">bridge</option>
            <option value="host">host</option>
            <option value="none">none</option>
          </select>
        </label>
        <label>
          {t("agent_editor.graceful_shutdown")}
          <input
            type="number"
            value={form.graceful_shutdown_secs}
            onChange={(e) =>
              updateField("graceful_shutdown_secs", Number(e.target.value))
            }
          />
        </label>
        <label>
          {t("agent_editor.force_kill_delay")}
          <input
            type="number"
            value={form.force_kill_delay_secs}
            onChange={(e) =>
              updateField("force_kill_delay_secs", Number(e.target.value))
            }
          />
        </label>
      </fieldset>

      <div style={{ display: "flex", gap: "0.5rem" }}>
        <button type="button" onClick={handleSave}>
          {t("agent_editor.save")}
        </button>
        <button type="button" onClick={() => navigate("/agents")}>
          {t("agent_editor.cancel")}
        </button>
        {!isNew && (
          <>
            <button type="button" onClick={handlePreview}>
              {t("agent_editor.preview_button")}
            </button>
            <button type="button" onClick={handleDuplicate}>
              {t("agent_editor.duplicate_button")}
            </button>
            <button
              type="button"
              onClick={handleDelete}
              style={{ color: "red" }}
            >
              {t("agent_editor.delete_button")}
            </button>
          </>
        )}
      </div>

      {showPreview && preview && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            justifyContent: "center",
            alignItems: "flex-start",
            padding: "2rem",
            overflowY: "auto",
          }}
          onClick={() => setShowPreview(false)}
        >
          <div
            style={{
              background: "white",
              padding: "1.5rem",
              maxWidth: 900,
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h2>{t("agent_editor.preview_title")}</h2>
            {preview.validation_errors.length > 0 ? (
              <div style={{ color: "red" }}>
                <strong>{t("agent_editor.preview_errors")}</strong>
                <ul>
                  {preview.validation_errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <p style={{ color: "green" }}>
                {t("agent_editor.preview_no_errors")}
              </p>
            )}
            <h3>prompt.md</h3>
            <pre style={{ fontSize: 11, background: "#f5f5f5", padding: 8 }}>
              {preview.prompt_md}
            </pre>
            <h3>mcp.json</h3>
            <pre style={{ fontSize: 11, background: "#f5f5f5", padding: 8 }}>
              {JSON.stringify(preview.mcp_json, null, 2)}
            </pre>
            <h3>tools.json</h3>
            <pre style={{ fontSize: 11, background: "#f5f5f5", padding: 8 }}>
              {JSON.stringify(preview.tools_json, null, 2)}
            </pre>
            <h3>.env</h3>
            <pre style={{ fontSize: 11, background: "#f5f5f5", padding: 8 }}>
              {preview.env_file || "(empty)"}
            </pre>
            <h3>skills/</h3>
            <ul>
              {preview.skills.map((s) => (
                <li key={s.skill_id}>{s.name}</li>
              ))}
            </ul>
            <button type="button" onClick={() => setShowPreview(false)}>
              {t("agent_editor.preview_close")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
